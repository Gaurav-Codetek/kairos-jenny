"""The Test screen: chat with an agent that reaches Kairos exactly as an outside agent does.

The agent connects over MCP HTTP to the connector the person picks (v1, v2, or one
connection's own endpoint), with its own key ("test-console"), and gets only what that
connector serves: the server's instructions and tool list. The person can switch the
connector at any point; the conversation carries on through the new one.

Two records of every turn:
  trace   what the agent did, from its side: each model step with tokens and time, each
          tool call with arguments, result and latency, the answer
  audit   what Kairos recorded, from the server's side: the activity log rows for the
          test-console agent (tool, channel, entities, tokens, cost, errors)

Sessions live in memory: this is a console for trying the product, not a record.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from kairos_kb.db.engine import async_session_factory

logger = logging.getLogger(__name__)

AGENT_NAME = "test-console"
SCOPES = ["read", "query", "files"]
MAX_STEPS = 15
MODEL_RESULT_CHARS = 30000
TRACE_RESULT_CHARS = 6000
# Tool results older than the last turn are cut to this in the model's history: the
# conversation keeps its memory without re-sending every result.
OLD_RESULT_CHARS = 1500

SYSTEM = """You are a data assistant for this company, connected to its data platform through Kairos,
a context server. You know nothing about the platform beyond what the server's tools tell you. Use the
tools to answer the user's questions accurately. This is a conversation: earlier turns are context.

In your answers: name the exact tables, data products, pipelines and columns you rely on, show numbers
the tools returned, state facts only when the tools support them, and say plainly when the tools do not
tell you something. Keep answers concise and use markdown tables for tabular results.

Server instructions:
{instructions}"""

SESSIONS: Dict[str, Dict[str, Any]] = {}
_KEY: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def agent_key() -> str:
    """The test console's own agent key: created on first use, rotated each time the API starts."""
    global _KEY
    if _KEY:
        return _KEY
    from kairos_kb.context.access import hash_key, new_key
    from kairos_kb.models.context import AgentClient

    key = new_key()
    async with async_session_factory() as db:
        agent = (await db.execute(select(AgentClient).where(AgentClient.name == AGENT_NAME))).scalars().first()
        if agent is None:
            agent = AgentClient(name=AGENT_NAME, description="The Test screen's chat agent.",
                                key_prefix=key[:12], key_hash=hash_key(key), scopes=SCOPES)
            db.add(agent)
        agent.key_prefix, agent.key_hash, agent.scopes, agent.revoked = key[:12], hash_key(key), SCOPES, False
        await db.commit()
    _KEY = key
    return key


async def connectors() -> List[Dict[str, Any]]:
    """Every MCP endpoint the console can talk through."""
    from kairos_kb.connectors.factory import slug_of
    from kairos_kb.mcp_server import server as v1
    from kairos_kb.mcp_server import server_v2 as v2
    from kairos_kb.mcp_server.connections import TOOL_NAMES
    from kairos_kb.models.workspace import Workspace

    listed = await v1.server.list_tools()
    out = [
        {"id": "v2", "label": "Kairos v2", "detail": "every connection · consolidated tools", "path": "/mcp-v2",
         "tools": len(v2.TOOL_NAMES), "platform": None},
        {"id": "v1", "label": "Kairos v1", "detail": "every connection · original tools", "path": "/mcp",
         "tools": len(getattr(listed, "tools", listed)), "platform": None},
    ]
    async with async_session_factory() as db:
        for ws in (await db.execute(select(Workspace).order_by(Workspace.name))).scalars():
            slug = await slug_of(db, ws)
            platform = ws.platform or "databricks"
            out.append({"id": f"c:{slug}", "label": ws.name, "detail": f"{platform} · this connection only",
                        "path": f"/mcp/c/{slug}", "tools": len(TOOL_NAMES.get(platform, [])), "platform": platform})
    return out


def new_session(connector: str) -> Dict[str, Any]:
    sid = str(uuid.uuid4())
    SESSIONS[sid] = {
        "id": sid, "connector": connector, "status": "idle", "created_at": _now(),
        "messages": [], "trace": [], "history": [], "turns": 0,
        "totals": {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0, "tool_errors": 0, "llm_steps": 0},
        "error": None,
    }
    return SESSIONS[sid]


def view(s: Dict[str, Any], after: int = 0) -> Dict[str, Any]:
    """The session for the screen; trace events from index `after` on."""
    return {k: v for k, v in s.items() if k not in ("history", "trace", "task")} | {
        "trace": s["trace"][after:], "trace_total": len(s["trace"])}


def switch(s: Dict[str, Any], connector: str) -> None:
    if connector == s["connector"]:
        return
    s["messages"].append({"id": str(uuid.uuid4()), "role": "system", "at": _now(),
                          "text": f"Switched connector: {s['connector']} → {connector}", "connector": connector})
    s["trace"].append({"type": "switch", "at": _now(), "from": s["connector"], "to": connector, "turn": s["turns"]})
    s["connector"] = connector


def _event(s: Dict[str, Any], **e) -> Dict[str, Any]:
    e.setdefault("at", _now())
    e.setdefault("turn", s["turns"])
    s["trace"].append(e)
    return e


def _trim_history(history: List[Dict[str, Any]]) -> None:
    """Cut old tool results so a long conversation stays affordable."""
    for item in history:
        for key in ("output", "content"):
            if item.get("type") == "function_call_output" or item.get("role") == "tool":
                v = item.get(key)
                if isinstance(v, str) and len(v) > OLD_RESULT_CHARS and not v.endswith("[earlier result trimmed]"):
                    item[key] = v[:OLD_RESULT_CHARS] + "\n…[earlier result trimmed]"


async def run_turn(s: Dict[str, Any], text: str) -> None:
    """One user message → the agent's tool loop over MCP → an answer. Everything lands in the trace."""
    from kairos_kb.evals.connector_eval import Connector, _agent_turn, _client, _record_calls, _record_result, default_model

    s["turns"] += 1
    turn = s["turns"]
    s["status"], s["error"] = "running", None
    s["messages"].append({"id": str(uuid.uuid4()), "role": "user", "text": text, "at": _now(),
                          "connector": s["connector"], "turn": turn})
    started = time.perf_counter()
    turn_tokens = {"input": 0, "output": 0}
    tools_used: List[str] = []
    try:
        key = await agent_key()
        t0 = time.perf_counter()
        async with Connector(s["connector"], key) as conn:
            _event(s, type="connect", connector=s["connector"], url=conn.url, tools=[t.name for t in conn.tools],
                   instructions_chars=len(conn.instructions), ms=int((time.perf_counter() - t0) * 1000))
            client = _client()
            model = default_model()
            system = SYSTEM.format(instructions=conn.instructions)
            history = s["history"]
            _trim_history(history)
            history.append({"role": "user", "content": text})
            specs = conn.specs()
            answer = None
            for step in range(MAX_STEPS + 1):
                last = step == MAX_STEPS
                t1 = time.perf_counter()
                out = await _agent_turn(client, model, system, history, specs, last)
                calls = [] if last else out["calls"]
                turn_tokens["input"] += out["input"]
                turn_tokens["output"] += out["output"]
                s["totals"]["input_tokens"] += out["input"]
                s["totals"]["output_tokens"] += out["output"]
                s["totals"]["llm_steps"] += 1
                _event(s, type="llm", step=step + 1, model=model, input_tokens=out["input"],
                       output_tokens=out["output"], ms=int((time.perf_counter() - t1) * 1000),
                       tool_calls=[c["name"] for c in calls], thought=(out["text"] or "")[:600] if calls else None)
                if not calls:
                    answer = out["text"]
                    if answer:
                        history.append({"role": "assistant", "content": answer})
                    break
                _record_calls(history, out["text"], calls)
                for c in calls:
                    try:
                        args = json.loads(c["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {"_unparsed": c["arguments"]}
                    t2 = time.perf_counter()
                    res = await conn.call(c["name"], args)
                    body = res["text"]
                    s["totals"]["tool_calls"] += 1
                    s["totals"]["tool_errors"] += 0 if res["ok"] else 1
                    tools_used.append(c["name"])
                    _event(s, type="tool_call", tool=c["name"], args=args, ok=res["ok"], local=res.get("local", False),
                           ms=int((time.perf_counter() - t2) * 1000), result_chars=len(body),
                           result=body[:TRACE_RESULT_CHARS], truncated=len(body) > TRACE_RESULT_CHARS)
                    _record_result(history, c["id"], body if len(body) <= MODEL_RESULT_CHARS
                                   else body[:MODEL_RESULT_CHARS] + "\n…[truncated]")
        ms = int((time.perf_counter() - started) * 1000)
        _event(s, type="answer", ms=ms, input_tokens=turn_tokens["input"], output_tokens=turn_tokens["output"],
               tools=tools_used, step_limit=answer is None)
        s["messages"].append({"id": str(uuid.uuid4()), "role": "assistant", "at": _now(), "turn": turn,
                              "connector": s["connector"], "ms": ms, "tools": tools_used,
                              "tokens": turn_tokens["input"] + turn_tokens["output"],
                              "text": answer or "I reached the step limit before finishing; ask me to continue."})
        s["status"] = "idle"
    except Exception as exc:  # noqa: BLE001 — shown in the chat and the trace
        logger.exception("Test console turn failed")
        _event(s, type="error", error=str(exc)[:800])
        s["messages"].append({"id": str(uuid.uuid4()), "role": "assistant", "at": _now(), "turn": turn,
                              "connector": s["connector"], "error": True, "text": f"Something went wrong: {exc}"})
        s["status"], s["error"] = "idle", str(exc)[:800]


def start_turn(s: Dict[str, Any], text: str) -> None:
    s["status"] = "running"
    s["task"] = asyncio.create_task(run_turn(s, text))


async def audit(s: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What Kairos recorded for the console's agent since this session began, oldest first."""
    from kairos_kb.models.context import AgentActivity

    since = datetime.fromisoformat(s["created_at"])
    async with async_session_factory() as db:
        rows = (await db.execute(select(AgentActivity).where(
            AgentActivity.agent_name == AGENT_NAME, AgentActivity.created_at >= since)
            .order_by(AgentActivity.created_at).limit(500))).scalars().all()
    return [{
        "id": str(r.id), "at": r.created_at.isoformat(), "channel": r.channel, "tool": r.tool,
        "arguments": r.arguments, "entities": r.entity_ids or [], "ok": r.ok, "error": r.error,
        "duration_ms": r.duration_ms, "result_size": r.result_size,
        "args_tokens": r.args_tokens, "result_tokens": r.result_tokens, "est_cost_usd": r.est_cost_usd,
    } for r in rows]
