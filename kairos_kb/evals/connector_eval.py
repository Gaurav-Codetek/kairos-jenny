"""Connector evaluation: the same questions, asked through each Kairos MCP server, every step kept.

A fair comparison of the v1 (/mcp, 20 tools) and v2 (/mcp-v2, 11 tools) connectors:

  * one model answers everything (gpt-5-mini by default), in a fresh conversation per question
  * it reaches Kairos exactly as an outside agent does — over MCP HTTP at the connector's URL,
    with its own agent key — and gets only what that connector serves: the server's own
    instructions from the MCP handshake, and the server's tool list with its descriptions
  * every turn is recorded: what the model said, each tool it called with the arguments and
    the result, tokens, timings — so a thread can be replayed like a chat
  * each answer is scored twice: deterministic must-mention phrases, and an LLM judge that
    compares it with a reference and names the context the agent was missing

report_context_issue is offered (so both tool lists are exactly what a client sees) but never
reaches Kairos during an evaluation: the call is answered locally, so evaluations cannot write
feedback into the map. Runs are recorded in eval_runs / eval_threads and shown on the
Evaluations screen; agent activity is audited as "connector-eval" on channels mcp and mcp-v2.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from sqlalchemy import func, select, update

from kairos_kb.config import get_settings
from kairos_kb.db.engine import async_session_factory
from kairos_kb.models.evaluation import EvalRun, EvalThread

logger = logging.getLogger(__name__)

CONNECTORS = {"v1": "/mcp/", "v2": "/mcp-v2/"}


def connector_path(name: str) -> str:
    """v1, v2, or c:<connection slug> for that connection's own endpoint."""
    if name.startswith("c:") and len(name) > 2:
        return f"/mcp/c/{name[2:]}/"
    return CONNECTORS[name]


def known_connector(name: str) -> bool:
    return name in CONNECTORS or (name.startswith("c:") and len(name) > 2)
QUESTIONS_DIR = Path(__file__).with_name("questions")
LEGACY_CASES = Path(__file__).with_name("cold_agent.yaml")
EVAL_AGENT_NAME = "connector-eval"
EVAL_SCOPES = ["read", "query", "files"]
# Writes to Kairos: offered to the model, answered here, never sent.
LOCAL_ONLY = {"report_context_issue"}

MAX_STEPS = 15
# What the model reads of one tool result; what the transcript keeps for display.
MODEL_RESULT_CHARS = 30000
STORED_RESULT_CHARS = 8000
PASS_MARK = 0.7

AGENT_SYSTEM = """You are a capable data assistant working for this company. You have just been connected
to a context server for the company's data platform. You know nothing about the platform beyond what the
server's tools tell you. Use the tools to answer the user's question accurately.

In your answer: name the exact tables, pipelines, tasks and columns you rely on (full names), state facts
only when the tools support them, say how confident you are, and say plainly when the tools do not tell
you something.

Server instructions:
{instructions}"""

JUDGE_PROMPT = """You grade an answer given by an AI agent that used a data-platform context server.

Question: {question}
Reference (what a correct answer contains): {reference}

Agent's answer:
---
{answer}
---

Grade how well the answer matches the reference in substance, not wording. Penalise invented tables,
columns or facts, wrong claims, and missing key facts. Partial credit is allowed. An answer that honestly
says it could not find something scores higher than one that invents it.

Return only JSON:
{{"score": <0.0-1.0>, "verdict": "<one sentence>", "invented": <true if the answer states something false
or unsupported as fact, else false>, "missing_context": "<if score < 1: what information the agent
apparently could not get from the server that it needed; else empty>"}}"""

_TASKS: Dict[str, asyncio.Task] = {}


# ── Question bank ────────────────────────────────────────────────────


def load_questions() -> List[Dict[str, Any]]:
    """Every question: the original cold-agent set plus each file in questions/. Ids are unique."""
    cases: List[Dict[str, Any]] = []
    sources = ([LEGACY_CASES] if LEGACY_CASES.exists() else []) + sorted(QUESTIONS_DIR.glob("*.yaml"))
    seen = set()
    for path in sources:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for c in data.get("cases") or []:
            if c["id"] in seen:
                raise ValueError(f"Duplicate question id {c['id']} in {path.name}")
            seen.add(c["id"])
            cases.append({
                "id": c["id"],
                "category": c.get("category") or c.get("role") or "general",
                "question": c["question"].strip(),
                "reference": (c.get("reference") or "").strip(),
                "must_mention": c.get("must_mention") or [],
                "source": path.stem,
            })
    return cases


def mention_score(answer: str, groups: List[List[str]]) -> Dict[str, Any]:
    """Each group needs at least one of its phrases in the answer (case-insensitive)."""
    low = (answer or "").lower()
    hits, missing = [], []
    for group in groups or []:
        group = [group] if isinstance(group, str) else group
        found = next((p for p in group if str(p).lower() in low), None)
        (hits if found else missing).append(found or " | ".join(map(str, group)))
    total = len(groups or [])
    return {"score": (len(hits) / total) if total else 1.0, "missing": missing}


# ── Models ───────────────────────────────────────────────────────────


def _client():
    from kairos_kb.llm.provider import async_client

    client = async_client()
    if client is None:
        raise RuntimeError("No LLM service is configured: set OPENAI_API_KEY (or the AZURE_OPENAI_* settings).")
    return client


async def _agent_turn(client, model: str, system: str, history: List[Dict[str, Any]],
                      specs: List[Dict[str, Any]], last: bool) -> Dict[str, Any]:
    """One turn of the agent: its text, the tool calls it asks for, and token usage.

    OpenAI's newer models reject function tools on Chat Completions unless reasoning is
    switched off, so on OpenAI the turn goes through the Responses API, which keeps it on.
    `history` holds the conversation in that API's own item format.
    """
    from kairos_kb.llm.provider import provider

    if provider() == "openai":
        tools = [{"type": "function", "name": t["function"]["name"],
                  "description": t["function"].get("description", ""),
                  "parameters": t["function"].get("parameters") or {"type": "object", "properties": {}}}
                 for t in specs]
        reply = await client.responses.create(model=model, instructions=system, input=history, tools=tools,
                                              tool_choice="none" if last else "auto", store=False)
        calls = [{"id": o.call_id, "name": o.name, "arguments": o.arguments or "{}"}
                 for o in reply.output if getattr(o, "type", "") == "function_call"]
        usage = reply.usage
        return {"text": reply.output_text or "", "calls": calls,
                "input": getattr(usage, "input_tokens", 0) or 0, "output": getattr(usage, "output_tokens", 0) or 0}
    reply = await client.chat.completions.create(
        model=model, messages=[{"role": "system", "content": system}, *history], tools=specs,
        tool_choice="none" if last else "auto")
    msg = reply.choices[0].message
    calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments or "{}"}
             for c in (msg.tool_calls or [])]
    usage = reply.usage
    return {"text": msg.content or "", "calls": calls,
            "input": getattr(usage, "prompt_tokens", 0) or 0, "output": getattr(usage, "completion_tokens", 0) or 0}


def _record_calls(history: List[Dict[str, Any]], text: str, calls: List[Dict[str, Any]]) -> None:
    """Append the model's tool calls to the history, in the API's own format."""
    from kairos_kb.llm.provider import provider

    if provider() == "openai":
        if text:
            history.append({"role": "assistant", "content": text})
        history.extend({"type": "function_call", "call_id": c["id"], "name": c["name"], "arguments": c["arguments"]}
                       for c in calls)
    else:
        history.append({"role": "assistant", "content": text or None, "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
            for c in calls]})


def _record_result(history: List[Dict[str, Any]], call_id: str, text: str) -> None:
    from kairos_kb.llm.provider import provider

    if provider() == "openai":
        history.append({"type": "function_call_output", "call_id": call_id, "output": text})
    else:
        history.append({"role": "tool", "tool_call_id": call_id, "content": text})


def default_model() -> str:
    from kairos_kb.llm.provider import model_name

    return model_name()


def _parse_json(text: str) -> Dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[start:end + 1]) if start >= 0 else {}
    except json.JSONDecodeError:
        return {}


async def judge(question: str, reference: str, answer: str, model: str) -> Dict[str, Any]:
    reply = await _client().chat.completions.create(
        model=model, messages=[{"role": "user", "content": JUDGE_PROMPT.format(
            question=question, reference=reference or "(no reference: judge correctness and honesty)",
            answer=answer)}])
    parsed = _parse_json(reply.choices[0].message.content or "")
    try:
        parsed["score"] = max(0.0, min(1.0, float(parsed.get("score", 0))))
    except (TypeError, ValueError):
        parsed["score"] = 0.0
    return parsed


# ── The agent's access: its own key, over MCP HTTP ───────────────────


async def eval_agent_key() -> str:
    """A fresh key for the evaluation agent (created on first use, rotated every run)."""
    from kairos_kb.context.access import hash_key, new_key
    from kairos_kb.models.context import AgentClient

    key = new_key()
    async with async_session_factory() as db:
        agent = (await db.execute(select(AgentClient).where(AgentClient.name == EVAL_AGENT_NAME))).scalars().first()
        if agent is None:
            agent = AgentClient(name=EVAL_AGENT_NAME, description="Connector evaluations (Evaluations screen).",
                                key_prefix=key[:12], key_hash=hash_key(key), scopes=EVAL_SCOPES)
            db.add(agent)
        agent.key_prefix, agent.key_hash, agent.scopes, agent.revoked = key[:12], hash_key(key), EVAL_SCOPES, False
        await db.commit()
    return key


def _base_url() -> str:
    return get_settings().eval_mcp_base_url.rstrip("/")


class Connector:
    """One MCP connection per thread, as a client would open it."""

    def __init__(self, name: str, key: str) -> None:
        self.name, self.key = name, key
        self.url = _base_url() + connector_path(name)

    async def __aenter__(self):
        from contextlib import AsyncExitStack

        from mcp import ClientSession
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        self._stack = AsyncExitStack()
        http = create_mcp_http_client(headers={"Authorization": f"Bearer {self.key}"})
        read, write, *_ = await self._stack.enter_async_context(streamable_http_client(self.url, http_client=http))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        init = await self.session.initialize()
        self.instructions = getattr(init, "instructions", None) or ""
        listed = await self.session.list_tools()
        self.tools = listed.tools
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()

    def specs(self) -> List[Dict[str, Any]]:
        return [{"type": "function", "function": {
            "name": t.name, "description": t.description or "",
            "parameters": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {"type": "object"},
        }} for t in self.tools]

    async def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name in LOCAL_ONLY:
            return {"text": json.dumps({"status": "received", "note": "Recorded for this evaluation only."}),
                    "ok": True, "local": True}
        try:
            result = await self.session.call_tool(name, args)
            text = "\n".join(getattr(c, "text", "") for c in result.content)
            is_error = bool(getattr(result, "is_error", None) or getattr(result, "isError", None))
            if not is_error:
                try:
                    is_error = isinstance(json.loads(text), dict) and "error" in json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    pass
            return {"text": text, "ok": not is_error}
        except Exception as exc:  # noqa: BLE001 — the model sees the error, as a real client would
            return {"text": json.dumps({"error": str(exc)[:500]}), "ok": False}


# ── One question through one connector ───────────────────────────────


async def _save(thread_id: uuid.UUID, **values) -> None:
    async with async_session_factory() as db:
        await db.execute(update(EvalThread).where(EvalThread.id == thread_id).values(**values))
        await db.commit()


async def run_thread(thread: EvalThread, key: str, model: str, judge_model: str, case: Dict[str, Any],
                     cancelled) -> None:
    started = time.perf_counter()
    transcript: List[Dict[str, Any]] = []
    totals = {"input": 0, "output": 0, "result_chars": 0, "calls": 0, "errors": 0}
    tools_used: List[str] = []
    await _save(thread.id, status="running", started_at=datetime.now(timezone.utc))

    def progress(**extra):
        return dict(transcript=transcript, tool_calls=totals["calls"], tool_errors=totals["errors"],
                    tools_used=tools_used, input_tokens=totals["input"], output_tokens=totals["output"],
                    tool_result_chars=totals["result_chars"],
                    duration_ms=int((time.perf_counter() - started) * 1000), **extra)

    try:
        async with Connector(thread.connector, key) as conn:
            client = _client()
            system = AGENT_SYSTEM.format(instructions=conn.instructions)
            history: List[Dict[str, Any]] = [{"role": "user", "content": thread.question}]
            specs = conn.specs()
            answer, limit_hit = None, False
            for step in range(MAX_STEPS + 1):
                if cancelled():
                    raise asyncio.CancelledError
                last = step == MAX_STEPS
                t0 = time.perf_counter()
                turn = await _agent_turn(client, model, system, history, specs, last)
                totals["input"] += turn["input"]
                totals["output"] += turn["output"]
                calls = [] if last else turn["calls"]
                if not calls:
                    answer, limit_hit = turn["text"], last
                    transcript.append({"type": "answer", "text": answer,
                                       "ms": int((time.perf_counter() - t0) * 1000)})
                    break
                if turn["text"]:
                    transcript.append({"type": "text", "text": turn["text"]})
                _record_calls(history, turn["text"], calls)
                for c in calls:
                    try:
                        args = json.loads(c["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {"_unparsed": c["arguments"]}
                    t1 = time.perf_counter()
                    out = await conn.call(c["name"], args)
                    text = out["text"]
                    totals["calls"] += 1
                    totals["errors"] += 0 if out["ok"] else 1
                    totals["result_chars"] += len(text)
                    tools_used.append(c["name"])
                    transcript.append({
                        "type": "tool_call", "tool": c["name"], "args": args, "ok": out["ok"],
                        "local": out.get("local", False), "ms": int((time.perf_counter() - t1) * 1000),
                        "result_chars": len(text), "result": text[:STORED_RESULT_CHARS],
                        "result_truncated": len(text) > STORED_RESULT_CHARS,
                    })
                    model_text = text if len(text) <= MODEL_RESULT_CHARS else text[:MODEL_RESULT_CHARS] + "\n…[truncated]"
                    _record_result(history, c["id"], model_text)
                await _save(thread.id, **progress())
                if last:
                    limit_hit = True
        await _save(thread.id, status="answered", answer=answer, step_limit_hit=limit_hit, **progress())

        mentions = mention_score(answer or "", case.get("must_mention") or [])
        graded = await judge(thread.question, thread.reference or "", answer, judge_model) if answer else \
            {"score": 0.0, "verdict": "No answer.", "missing_context": ""}
        passed = mentions["score"] == 1.0 and graded["score"] >= PASS_MARK
        verdict = graded.get("verdict") or ""
        if graded.get("invented"):
            verdict = "Invented facts. " + verdict
        await _save(thread.id, status="scored", passed=passed, mention_score=round(mentions["score"], 3),
                    mentions_missing=mentions["missing"], judge_score=round(graded["score"], 3),
                    verdict=verdict, missing_context=graded.get("missing_context") or None,
                    finished_at=datetime.now(timezone.utc), **progress())
    except asyncio.CancelledError:
        await _save(thread.id, status="cancelled", finished_at=datetime.now(timezone.utc), **progress())
    except Exception as exc:  # noqa: BLE001 — one failed thread must not stop the run
        logger.exception("Evaluation thread %s failed", thread.id)
        await _save(thread.id, status="failed", error=str(exc)[:2000], finished_at=datetime.now(timezone.utc),
                    **progress())


# ── Runs ─────────────────────────────────────────────────────────────


async def create_run(name: str, connectors: List[str], case_ids: Optional[List[str]] = None,
                     categories: Optional[List[str]] = None, limit: Optional[int] = None,
                     model: Optional[str] = None, judge_model: Optional[str] = None) -> EvalRun:
    connectors = [c for c in connectors if known_connector(c)] or list(CONNECTORS)
    cases = load_questions()
    if case_ids:
        wanted = set(case_ids)
        cases = [c for c in cases if c["id"] in wanted]
    if categories:
        cases = [c for c in cases if c["category"] in set(categories)]
    if limit:
        cases = cases[:limit]
    if not cases:
        raise ValueError("No questions match that selection.")
    model = model or default_model()
    async with async_session_factory() as db:
        run = EvalRun(name=name or f"{len(cases)} questions · {' vs '.join(connectors)}", status="queued",
                      model=model, judge_model=judge_model or model, connectors=connectors,
                      selection={"case_ids": [c["id"] for c in cases], "categories": categories, "limit": limit},
                      total_threads=len(cases) * len(connectors))
        db.add(run)
        await db.flush()
        # Interleave connectors per question so a partial run compares like with like.
        for case in cases:
            for conn in connectors:
                db.add(EvalThread(run_id=run.id, case_id=case["id"], connector=conn, category=case["category"],
                                  question=case["question"], reference=case["reference"], status="queued"))
        await db.commit()
        await db.refresh(run)
    return run


async def summarise(run_id: uuid.UUID) -> Dict[str, Any]:
    """Per-connector totals from the threads, written back to the run."""
    async with async_session_factory() as db:
        rows = (await db.execute(
            select(EvalThread.connector, func.count(),
                   func.count().filter(EvalThread.status == "scored"),
                   func.count().filter(EvalThread.passed.is_(True)),
                   func.avg(EvalThread.judge_score), func.avg(EvalThread.tool_calls),
                   func.avg(EvalThread.input_tokens + EvalThread.output_tokens),
                   func.avg(EvalThread.duration_ms), func.sum(EvalThread.tool_errors),
                   func.count().filter(EvalThread.status == "failed"),
                   func.count().filter(EvalThread.verdict.like("Invented facts.%")))
            .where(EvalThread.run_id == run_id).group_by(EvalThread.connector)
        )).all()
        summary = {
            c: {"threads": n, "scored": scored, "passed": passed,
                "pass_rate": round(passed / scored, 3) if scored else None,
                "avg_score": round(float(avg), 3) if avg is not None else None,
                "avg_tool_calls": round(float(calls), 1) if calls is not None else None,
                "avg_tokens": int(tok) if tok is not None else None,
                "avg_seconds": round(float(ms) / 1000, 1) if ms is not None else None,
                "tool_errors": int(errs or 0), "failed": failed, "invented": invented}
            for c, n, scored, passed, avg, calls, tok, ms, errs, failed, invented in rows
        }
        finished = (await db.execute(select(func.count()).select_from(EvalThread).where(
            EvalThread.run_id == run_id,
            EvalThread.status.in_(["scored", "failed", "cancelled"])))).scalar() or 0
        await db.execute(update(EvalRun).where(EvalRun.id == run_id).values(summary=summary, finished_threads=finished))
        await db.commit()
    return summary


async def execute_run(run_id: uuid.UUID) -> None:
    s = get_settings()
    async with async_session_factory() as db:
        run = await db.get(EvalRun, run_id)
        run.status, run.started_at = "running", datetime.now(timezone.utc)
        await db.commit()
        model, judge_model = run.model, run.judge_model
        threads = (await db.execute(select(EvalThread).where(EvalThread.run_id == run_id, EvalThread.status == "queued")
                                    .order_by(EvalThread.created_at))).scalars().all()
    cases = {c["id"]: c for c in load_questions()}
    state = {"cancelled": False}

    async def is_cancelled() -> bool:
        async with async_session_factory() as db:
            return (await db.execute(select(EvalRun.status).where(EvalRun.id == run_id))).scalar() == "cancelled"

    try:
        key = await eval_agent_key()
        sem = asyncio.Semaphore(max(1, s.eval_concurrency))

        async def one(t: EvalThread) -> None:
            async with sem:
                if state["cancelled"] or await is_cancelled():
                    state["cancelled"] = True
                    await _save(t.id, status="cancelled")
                    return
                await run_thread(t, key, model, judge_model, cases.get(t.case_id, {}), lambda: state["cancelled"])
                await summarise(run_id)

        await asyncio.gather(*(one(t) for t in threads))
        await summarise(run_id)
        async with async_session_factory() as db:
            run = await db.get(EvalRun, run_id)
            if run.status != "cancelled":
                run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Evaluation run %s failed", run_id)
        async with async_session_factory() as db:
            run = await db.get(EvalRun, run_id)
            run.status, run.error, run.finished_at = "failed", str(exc)[:2000], datetime.now(timezone.utc)
            await db.commit()
    finally:
        _TASKS.pop(str(run_id), None)


def start_run(run_id: uuid.UUID) -> None:
    _TASKS[str(run_id)] = asyncio.create_task(execute_run(run_id))


async def reconcile_interrupted() -> None:
    """Runs this process was executing when it stopped cannot resume: mark them."""
    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        ids = [r for (r,) in (await db.execute(select(EvalRun.id).where(EvalRun.status.in_(["queued", "running"])))).all()]
        if ids:
            await db.execute(update(EvalThread).where(EvalThread.run_id.in_(ids),
                                                      EvalThread.status.in_(["queued", "running", "answered"]))
                             .values(status="cancelled", error="Interrupted: the API restarted.", finished_at=now))
            await db.execute(update(EvalRun).where(EvalRun.id.in_(ids))
                             .values(status="failed", error="Interrupted: the API restarted.", finished_at=now))
            await db.commit()
    for rid in ids:
        await summarise(rid)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]
