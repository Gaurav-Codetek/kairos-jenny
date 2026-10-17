"""Jack: the same live business, through an ElevenLabs Agent instead of Jenny's own pipeline.

An experiment beside Jenny, switched on from the companion panel, that changes nothing of hers. ElevenLabs runs the
whole conversation (listening, turn-taking, its own hosted language model, the voice); Kairos gives it only:

  tools   the data products and the live pulse, nothing else: pulse_now, list_products, query, compare_to_normal.
          They are *client* tools: the agent's model asks for one, the browser runs it against Kairos and hands back
          the result. So Kairos never has to be reachable from the internet, and the API key never leaves the server.
  prompt  who Jack is and how to use the tools; the business's clock, date and products come in as dynamic
          variables at the start of each call.

The agent and its tools are created in the ElevenLabs account on first use and kept in data/jack.json; when the
configuration here changes they are made again.

Settings: ELEVENLABS_API_KEY (needs the ElevenLabs Agents permission, read and write), JACK_LLM (gemini-2.5-flash),
JACK_VOICE (a voice name or id; Raju, an Indian English voice), JACK_TTS_MODEL (eleven_v4_turbo), JACK_ENABLED (off
unless 1: no agent calls are made until it's switched on).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import httpx

from kairos_kb.companion import voice
from kairos_kb.exceptions import KairosException

logger = logging.getLogger(__name__)

API = "https://api.elevenlabs.io/v1"
STATE = Path(os.getenv("JACK_STATE", "data/jack.json"))
LLM = os.getenv("JACK_LLM", "gemini-2.5-flash").strip()
VOICE = os.getenv("JACK_VOICE", "Raju").strip()
TTS_MODEL = os.getenv("JACK_TTS_MODEL", "eleven_v4_turbo").strip()
RESULT_CHARS = 8000
# Off unless switched on: Jack was an experiment to learn from (his calls are kept in the companion history).
ENABLED = os.getenv("JACK_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
_making = asyncio.Lock()  # two calls starting at once must not make two agents

# Only the data products and the live pulse: what Jack may see of Kairos.
TOOLS = ("pulse_now", "list_products", "query", "compare_to_normal")
# Raju: "Natural Conversationalist", an Indian English voice from the ElevenLabs library.
MALE_PREMADE = {"raju": "pzxut4zZz4GImZNlqQ3H", "george": "JBFqnCBsd6RMkjVDRZzb", "brian": "nPczCjzI2devNBz1zQrb", "daniel": "onwK4e9ZLuTAKqWW03F9",
                "liam": "TX3LPaxmHKxFdv7VOQHJ", "chris": "iP95p4xoKVk53GoZ742B", "will": "bIHbv24MWmeRgasZH58o"}


def _string(desc: str) -> Dict[str, Any]:
    return {"type": "string", "description": desc}


TOOL_CONFIGS: List[Dict[str, Any]] = [
    {"type": "client", "name": "pulse_now", "expects_response": True, "response_timeout_secs": 30,
     "description": ("The live dashboard: how the business is doing right now. Each vital today-so-far against a normal "
                     "day at this time, where the day is heading, and the current headline. Start here for 'how are "
                     "we doing'."),
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"type": "client", "name": "list_products", "expects_response": True, "response_timeout_secs": 30,
     "description": "The data products: their metrics (and whether they add up) and dimensions. Read before querying.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"type": "client", "name": "query", "expects_response": True, "response_timeout_secs": 60,
     "description": ("A live query on one data product. Use metric and dimension names exactly as list_products gives "
                     "them. A time dimension can take a grain: event_time:hour, order_date:day."),
     "parameters": {"type": "object", "required": ["product", "metrics"], "properties": {
         "product": _string("The data product, e.g. Sales."),
         "metrics": _string("Comma-separated metric names, e.g. gmv,orders."),
         "by": _string("Optional comma-separated dimensions to group by, e.g. city or event_time:hour."),
         "filters": _string("Optional JSON array of filters: [{\"dimension\": \"city\", \"op\": \"=\", \"value\": "
                            "\"Pune\"}]. ops: = != > >= < <= in between; times as 'YYYY-MM-DD HH:MM:SS' in the "
                            "business's clock; for today use event_time between today's start and now."),
         "order": _string("Optional, e.g. 'gmv desc'."),
         "limit": _string("Optional row limit, default 20."),
     }}},
    {"type": "client", "name": "compare_to_normal", "expects_response": True, "response_timeout_secs": 60,
     "description": ("One metric today-so-far against normal days at this minute, optionally broken down by a dimension "
                     "(city) to see where a gap sits, or for particular hours of today against the same hour on normal "
                     "days."),
     "parameters": {"type": "object", "required": ["product", "metric"], "properties": {
         "product": _string("The data product, e.g. Sales."),
         "metric": _string("One metric name, e.g. delivered_orders."),
         "dimension": _string("Optional dimension to break the gap down by, e.g. city."),
         "hours": _string("Optional comma-separated hours of today (0-23), e.g. 5 for 05:00-05:59."),
     }}},
]

PROMPT = """You are Jack, a voice assistant for {{workspace}}. You talk with the owner about how their business is
doing, using only what your tools return.

# Right now
It is {{now}} in the business's clock ({{today}}).
Data products: {{products}}

# How you work
- You can see the business only through your tools: pulse_now (the live dashboard), list_products, query and
  compare_to_normal. Never state a number you didn't get from a tool, and say so plainly when the data can't tell.
- "How are we doing" starts with pulse_now. To compare with a normal day, use compare_to_normal. For anything else,
  read list_products, then query with the exact metric and dimension names.
- For "today", filter event_time between today's start and now.
- Speak like a composed assistant: clear, short answers, two or three sentences, the answer first. Round numbers the
  way people say them and spell them out. Never say field names (gmv_total, delivery_time_p90): say what they mean.
- Before a lookup you may say one short line ("Let me check the live numbers."); don't repeat it.
- Write plain spoken words only: no bracketed tags or stage directions such as [slow] or [pause]."""

FIRST_MESSAGE = "Hi, it's Jack. What would you like to know about the business?"


def _key() -> str:
    if not voice.ELEVEN_KEY:
        raise KairosException("Jack needs an ElevenLabs API key (ELEVENLABS_API_KEY in .env).", status_code=400)
    return voice.ELEVEN_KEY


def _check(r: httpx.Response, doing: str) -> Dict[str, Any]:
    if r.status_code == 401 and "missing_permissions" in r.text:
        raise KairosException("Your ElevenLabs API key needs the ElevenLabs Agents permission (read and write) for "
                              "Jack. Turn it on for the key in the ElevenLabs dashboard, then try again.", status_code=400)
    if r.status_code >= 400:
        raise KairosException(f"ElevenLabs refused {doing}: {r.status_code} {r.text[:300]}", status_code=502)
    return r.json() if r.content else {}


async def _voice_id(client: httpx.AsyncClient) -> str:
    want = VOICE.lower()
    if want in MALE_PREMADE:
        return MALE_PREMADE[want]
    try:
        r = await client.get(f"{API}/voices", headers={"xi-api-key": _key()})
        for v in (r.json().get("voices") or []) if r.status_code == 200 else []:
            if v.get("voice_id") == VOICE or (v.get("name") or "").lower().split(" - ")[0] == want:
                return v["voice_id"]
    except (httpx.HTTPError, ValueError):
        pass
    return VOICE  # taken as an id


def _fingerprint() -> str:
    return hashlib.sha1(json.dumps([PROMPT, FIRST_MESSAGE, LLM, VOICE, TTS_MODEL]).encode()).hexdigest()[:12]


def _tools_fingerprint() -> str:
    return hashlib.sha1(json.dumps(TOOL_CONFIGS).encode()).hexdigest()[:12]


def _load() -> Dict[str, Any]:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


async def ensure_agent() -> str:
    """Jack's agent in the ElevenLabs account, made (or made again, when the configuration changed) on first use."""
    async with _making:
        state = _load()
        fp, tfp = _fingerprint(), _tools_fingerprint()
        if state.get("agent_id") and state.get("fingerprint") == fp and state.get("tools_fingerprint") == tfp:
            return state["agent_id"]
        return await _make(state, fp, tfp)


async def _make(state: Dict[str, Any], fp: str, tfp: str) -> str:
    """Create Jack's agent, or update the one he has (new tools only when their definitions changed)."""
    async with httpx.AsyncClient(timeout=30) as client:
        headers = {"xi-api-key": _key()}
        tool_ids = list(state.get("tool_ids") or [])
        if not tool_ids or (state.get("tools_fingerprint") or tfp) != tfp:
            tool_ids = []
            for cfg in TOOL_CONFIGS:
                made = _check(await client.post(f"{API}/convai/tools", headers=headers, json={"tool_config": cfg}),
                              f"to create the {cfg['name']} tool")
                tool_ids.append(made["id"])
        config = {
            "agent": {"first_message": FIRST_MESSAGE, "language": "en",
                      "prompt": {"prompt": PROMPT, "llm": LLM, "temperature": 0.3, "tool_ids": tool_ids}},
            "tts": {"model_id": TTS_MODEL, "voice_id": await _voice_id(client)},
            "turn": {"turn_eagerness": "normal"},
        }
        agent_id = state.get("agent_id")
        if agent_id:
            r = await client.patch(f"{API}/convai/agents/{agent_id}", headers=headers, json={"conversation_config": config})
            if r.status_code == 404:
                agent_id = None  # deleted in the dashboard: make him again
            else:
                _check(r, "to update Jack")
        if not agent_id:
            made = _check(await client.post(f"{API}/convai/agents/create", headers=headers,
                                            json={"name": "Jack (Kairos)", "conversation_config": config}), "to create Jack")
            agent_id = made["agent_id"]
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"agent_id": agent_id, "tool_ids": tool_ids, "fingerprint": fp, "tools_fingerprint": tfp}),
                     encoding="utf-8")
    logger.info("Jack's ElevenLabs agent %s is up to date (%s, %s)", agent_id, LLM, VOICE)
    return agent_id


async def session(workspace_id) -> Dict[str, Any]:
    """What the browser needs to start a call with Jack: a short-lived conversation token (WebRTC) and the business's
    clock, date and products for the prompt."""
    from sqlalchemy import select

    from kairos_kb.companion.chat import _context
    from kairos_kb.db.engine import async_session_factory
    from kairos_kb.models.data_product import DataProduct

    if not ENABLED:
        raise KairosException("Jack (the ElevenLabs agent) is switched off. Set JACK_ENABLED=1 in .env to use him again.",
                              status_code=400)
    agent_id = await ensure_agent()
    async with httpx.AsyncClient(timeout=20) as client:
        tok = _check(await client.get(f"{API}/convai/conversation/token", params={"agent_id": agent_id},
                                      headers={"xi-api-key": _key()}), "a conversation token")
    async with async_session_factory() as db:
        ctx = await _context(db, workspace_id)
        names = [p.name for p in (await db.execute(select(DataProduct).where(DataProduct.workspace_id == workspace_id))).scalars()]
    return {"agent_id": agent_id, "conversation_token": tok.get("token"),
            "dynamic_variables": {"workspace": ctx["workspace"], "now": ctx["now"], "today": ctx["date"],
                                  "products": ", ".join(names) or "none"},
            "llm": LLM, "voice": VOICE}


def _list(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


async def run_tool(workspace_id, name: str, args: Dict[str, Any]) -> str:
    """One of Jack's tools, run for the browser. Only the data products and the live pulse."""
    from kairos_kb.companion.chat import call_tool

    if name not in TOOLS:
        return json.dumps({"error": f"Jack has no tool called {name}."})
    a = dict(args or {})
    if name == "query":
        filters = a.get("filters")
        if isinstance(filters, str) and filters.strip():
            try:
                filters = json.loads(filters)
            except ValueError:
                return json.dumps({"error": "filters must be a JSON array, e.g. [{\"dimension\": \"city\", \"op\": \"=\", "
                                            "\"value\": \"Pune\"}]"})
        a = {"product": a.get("product"), "metrics": _list(a.get("metrics")), "by": _list(a.get("by")),
             "filters": filters or [], "order": a.get("order") or "",
             "limit": int(str(a.get("limit") or 20)) if str(a.get("limit") or "20").isdigit() else 20}
    elif name == "compare_to_normal":
        a = {"product": a.get("product"), "metric": a.get("metric"), "dimension": a.get("dimension") or None,
             "hours": [int(h) for h in _list(a.get("hours")) if h.isdigit()]}
    from kairos_kb.companion.scenes import public

    res = await call_tool(workspace_id, name, a)
    return json.dumps(public(res), default=str)[:RESULT_CHARS]


async def keep_call(workspace_id, call: Dict[str, Any]) -> str:
    """A Jack call (an ElevenLabs conversation record) kept in Kairos as a companion conversation, so Jack's calls sit
    beside Jenny's in the history: every line with its time in the call, his lookups on the answer that used them, and
    the call's start and end. Returns the conversation id."""
    from datetime import datetime, timedelta, timezone

    from kairos_kb.db.engine import async_session_factory
    from kairos_kb.models.companion import CompanionConversation, CompanionMessage

    start = datetime.fromtimestamp((call.get("metadata") or {}).get("start_time_unix_secs") or 0, tz=timezone.utc)
    seconds = int((call.get("metadata") or {}).get("call_duration_secs") or 0)
    title = (call.get("analysis") or {}).get("call_summary_title") or "Call"
    source = {"source": "jack", "elevenlabs_conversation": call.get("conversation_id")}
    async with async_session_factory() as db:
        conv = CompanionConversation(workspace_id=workspace_id, title=f"Jack · {title}"[:255], history=[],
                                     last_at=start + timedelta(seconds=seconds))
        db.add(conv)
        await db.flush()
        db.add(CompanionMessage(conversation_id=conv.id, role="call", text="Call started (Jack, ElevenLabs agent)",
                                voice=True, status="done", created_at=start,
                                meta={**source, "call": {"event": "start", "seconds": None}}))
        history, steps = [], []
        for i, turn in enumerate(call.get("transcript") or []):
            for tc in turn.get("tool_calls") or []:
                steps.append({"tool": tc.get("tool_name"), "args": tc.get("params_as_json"), "ok": True})
            for tr in turn.get("tool_results") or []:
                if tr.get("is_error") and steps:
                    steps[-1]["ok"] = False
            text = (turn.get("message") or "").strip()
            if not text:
                continue
            role = "user" if turn.get("role") == "user" else "assistant"
            at = start + timedelta(seconds=float(turn.get("time_in_call_secs") or 0), microseconds=i)
            db.add(CompanionMessage(conversation_id=conv.id, role=role, text=text, voice=True,
                                    status="interrupted" if turn.get("interrupted") else "done",
                                    steps=steps if role == "assistant" else [], created_at=at,
                                    meta={**source, "time_in_call": turn.get("time_in_call_secs")}))
            history.append({"role": role, "content": text})
            if role == "assistant":
                steps = []
        mins, secs = divmod(seconds, 60)
        db.add(CompanionMessage(conversation_id=conv.id, role="call", text=f"Call ended · {mins}m {secs:02d}s", voice=True,
                                status="done", created_at=start + timedelta(seconds=seconds, microseconds=999),
                                meta={**source, "call": {"event": "end", "seconds": seconds}}))
        conv.history = history
        await db.commit()
        return str(conv.id)
