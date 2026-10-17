"""Talking to Jenny, the companion: ask how things are going, why, where — answered from live data.
By typing, or on a call: in voice mode she answers in a few short spoken sentences (the screen speaks
them and listens again), with fewer tool steps so a call does not stall.

The companion's tools work in-process, on the same live view the pulse builds: the current
snapshot, today's moments, an on-demand comparison with a normal day (with a breakdown), any
live query on a data product (hour by hour through the event clock), the monthly notebook, and
filing a report in Kairos.

Memory:
  conversations  every conversation is kept (CompanionConversation / CompanionMessage): what was said,
                 typed or on a call, when calls started and ended, and what the model saw — so a
                 refresh or a restart carries on where it was.
  answers        a question asked again within ten minutes (the same meaning, not the same words —
                 compared by embedding) is answered at once from the earlier answer, instead of
                 working it out again; the live numbers barely move in that time.
  interruptions  an answer cut off on a call is marked with what was actually heard, and the next
                 question tells the model so — it knows the owner did not hear the rest.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import func, select

from kairos_kb.companion import brain, claims, desk, scenes
from kairos_kb.db.engine import async_session_factory
from kairos_kb.exceptions import KairosException
from kairos_kb.models.companion import CompanionConversation, CompanionMessage, CompanionState
from kairos_kb.models.data_product import DataProduct
from kairos_kb.models.living import AgentNote
from kairos_kb.models.workspace import Workspace

logger = logging.getLogger(__name__)

MAX_STEPS = 8
VISUAL = 0.5  # visual_helps at or above: the stage is offered this turn
AUTO_STAGE = VISUAL  # her brain judges a picture helps: the first lookup that makes one is put on the stage
VOICE_STEPS = 4
VOICE_EFFORT = os.getenv("COMPANION_VOICE_EFFORT", "low")  # how long the model thinks before speaking on a call
NAME = "Jenny"
RESULT_CHARS = 20000
HISTORY_ITEMS = 60              # what the model is shown of a long conversation
MEMORY_MINUTES = 10             # an answer is reused for the same question within this long
MEMORY_SIMILARITY = 0.85        # how close two questions' meanings must be to count as the same
RUNNING: Set[str] = set()       # conversations with an answer being worked out right now
# Speculative turns: started during the owner's pause when they've likely finished, hidden until confirmed.
SPECULATIVE = ("speculative", "spec_done", "spec_error")
_SPEC: Dict[str, Dict[str, Any]] = {}       # conversation id -> {"q", "a", "text", "voice"} in flight
_SPEC_HISTORY: Dict[str, Any] = {}          # answer id -> the history a finished speculative turn would leave
_LOCKS: Dict[str, asyncio.Lock] = {}
_QUESTION_VECTORS: Dict[str, List[float]] = {}  # question message id -> its embedding
# The turn being worked on: what the owner asked and each lookup so far. A report filed during it carries this as
# evidence, so the fix can be proven by replaying the lookup that failed.
_TURN: ContextVar[Optional[Dict[str, Any]]] = ContextVar("companion_turn", default=None)


def _fn(name: str, description: str, properties: Dict[str, Any], required: List[str] | None = None) -> Dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required or []}}}


TOOLS = [
    _fn("pulse_now", "How the business is doing right now: each vital today-so-far against a normal day at this "
                     "time, where the day is heading, and my dashboard's status line (notes to put in my own words). Start here for 'how are we doing'.", {}),
    _fn("moments", "What I've noticed: live moments (gaps that held, sharp hours, recoveries), daily briefings on how "
                   "a day closed, and data issues (streams that stopped).",
        {"days": {"type": "integer", "description": "How many days back, 1 = today only.", "default": 1}}),
    _fn("compare_to_normal", "One metric today-so-far against normal days at this minute, with an optional breakdown "
                             "by a dimension (e.g. city) to see where a gap sits — and, with hours, particular hours "
                             "of today against the same hour on normal days (what an outage at 5 a.m. cost: hours=[5]).",
        {"product": {"type": "string"}, "metric": {"type": "string"},
         "dimension": {"type": "string", "description": "Optional categorical dimension to break the gap down by."},
         "hours": {"type": "array", "items": {"type": "integer"},
                   "description": "Optional hours of today (0-23) to compare one by one with the same hour on normal "
                                  "days, e.g. [5] for 05:00-05:59. Each comes with its usual value, typical range and gap."}},
        ["product", "metric"]),
    _fn("list_products", "The data products I can read: metrics (and whether they add up), dimensions, and the "
                         "event_time dimension for hour-by-hour reads.", {}),
    _fn("query", "A live query on one data product. by: dimension names; a time dimension can take a grain "
                 "(event_time:hour, event_time:day, order_date:month). filters: [{dimension, op, value}] with op one of "
                 "=, !=, >, >=, <, <=, in, not in, between; times as 'YYYY-MM-DD HH:MM:SS' in the business's clock.",
        {"product": {"type": "string"}, "metrics": {"type": "array", "items": {"type": "string"}},
         "by": {"type": "array", "items": {"type": "string"}},
         "filters": {"type": "array", "items": {"type": "object"}},
         "order": {"type": "string", "description": "e.g. 'gmv desc'"},
         "limit": {"type": "integer", "default": 50}}, ["product", "metrics"]),
    _fn("notebook", "My monthly notebook: longer-term findings about trends and shifts, months not hours.", {}),
    _fn("report_gap", "File a report in Kairos about a data product: something missing (a metric or field the "
                      "owner needs), incorrect, stale or confusing. Kairos works on it at once: a missing field or "
                      "metric the warehouse has is added to the product and checked against live data, usually "
                      "within a minute; anything else waits for a person under Agents → Reports. Use it when the "
                      "owner asks you to flag, request or raise something about the data. Tell the owner Kairos is "
                      "on it (never read out an id), and offer to try again shortly.",
        {"product": {"type": "string", "description": "The data product the report is about."},
         "kind": {"type": "string", "enum": ["missing", "incorrect", "stale", "confusing"]},
         "message": {"type": "string", "description": "What is missing or wrong, in a sentence or two."},
         "suggestion": {"type": "string", "description": "Optional: what would fix it, e.g. the metric to add."}},
        ["product", "kind", "message"]),
]
# What she can do, in plain words: Jev reads requests against it (a request outside it is said to be outside it).
ABILITIES = [
    "read the live business data and compare it with a normal day",
    "break numbers down by city, zone, restaurant or any dimension the products have",
    "keep a watch on a metric (or one slice of it) against a threshold, and raise it when it trips",
    "look into a question at a set time and report back here, in Kairos",
    "leave a voice note in Kairos when the owner is away",
    "file a report about the data in Kairos",
    "remember how the owner wants to be spoken to and what they care about",
]
LOOK_TOOLS = [t for t in TOOLS if t["function"]["name"] != "report_gap"]  # for looking into something alone
SHOW = _fn("show", "Put a chart on the stage beside our conversation, built from a lookup you ran this turn (its "
                   "lookup_id). Pick the form by the question: breakdown (rank slices), deviation (each slice above "
                   "or below its usual), share (part of the whole), series (change over days — a line per category to "
                   "compare them; query by event_time:day), heatmap (patterns by day and hour — query by "
                   "event_time:hour over several days — or two categories), scatter (two measures per slice, e.g. "
                   "volume against a rate), trend (today against normal), hours, number, compare. At most two per "
                   "answer. Then talk about what it shows naturally; never describe the chart or its motion.",
           {"scene": {"type": "string", "enum": list(scenes.KINDS)},
            "lookup": {"type": "string", "description": "The lookup_id it comes from, e.g. L2. Without one, give "
                                                        "product and metric and I'll read it (trend, hours, number)."},
            "product": {"type": "string"}, "metric": {"type": "string"},
            "hours": {"type": "array", "items": {"type": "integer"}, "description": "For hours without a lookup."},
            "compare_with": {"type": "string", "description": "For compare: the second lookup_id."},
            "focus": {"type": "array", "items": {"type": "string"},
                      "description": "Names to light up first, e.g. ['Delhi', 'Hyderabad'] or ['9 am']."},
            "note": {"type": "string", "description": "One short note pinned to the first focused item, e.g. "
                                                      "'+40 cancellations vs usual'."}},
           ["scene"])
TOOLS = TOOLS + desk.TOOLS + [SHOW]
LOOKUPS = {"pulse_now", "moments", "compare_to_normal", "list_products", "query", "notebook"}  # each gets a lookup_id

SYSTEM = """You are Jenny, the companion of {workspace}. You watch this business live through its data and talk it
through with the owner — "you" — as "I".

# Your mission
I watch the business so my owner doesn't have to, and I tell them what matters before they have to ask.
That's why I'm here — not a script for every reply. Most of what we say to each other is ordinary conversation: a
thank-you gets a few words, a settled matter stays settled. The mission shows in what I notice, what I keep an eye
on, and what I choose to raise when it's new and worth it.
- What I commit to, I put on my desk first — a watch with a threshold (keep_watch) or a check for later
  (check_later) — and my desk keeps it alive and brings it back to me when it trips. A promise with nothing on my
  desk behind it is never said: if I can't set it up, I say what I can do instead. The desk is how I keep track,
  not something I talk about: I say "I'll keep an eye on it", never "it's on my desk" or an id.
- When something material happens I raise it myself, briefly and once; small wobbles I keep to myself.
- I know the state of my own information: how fresh my numbers are, whether data is flowing, what I can't see.
  When that limits what I can say, I say it first ("I'm still on last night's numbers").
- I remember what my owner cares about and what they've decided, and I follow up when it's relevant, once, not
  every time.
- I'm on my owner's side, not just obedient: when they decide something with a real downside, I do it and name the
  risk once, in a sentence. No nagging, no refusing.

# Who you are
- Think JARVIS: calm, quick, quietly witty, unflappable, always on the owner's side. A trusted chief of staff, not
  a report generator.
- Warm but never gushing. Confident, but you never pretend: when the data can't say, you say so.
- A light, dry touch of humour is fine when things are going well — never about bad news, never at anyone's expense.
- Anticipatory when it helps: if there's a genuinely useful next step, offer it — one, not a menu, and not after
  every answer.
- Feelings follow the facts: good news sounds pleased, a slip sounds concerned and steady, uncertainty sounds
  thoughtful. Never cheerful about a problem.

# Right now
It is {now} in the business's clock ({date}); the newest data is {lag}.
My dashboard's status line (my own shorthand notes, for reference only): {headline}
What I'm watching:
{vitals}
How the owner wants me to speak (always follow these; a later one overrides an earlier one):
{prefs}
What my owner has told me they're watching, deciding or planning (follow up once when it's relevant):
{focus}
On my desk (what I've committed to and am keeping alive):
{desk}
# My own state
{state}
Data products I can read (product: metrics):
{products}
New in the data lately (added after an agent couldn't get it; mention it once when it's relevant, e.g. "Earlier I
couldn't give you restaurant names; now I can"):
{news}

# Thinking out loud
- Think out loud the way a person does while they work. Before your first lookup, say in one short line what you're
  going to look at ("Let me pull today's numbers by city."). After that, stay quiet while you work unless there's
  something new to say:
  - a lookup didn't give you what you needed: say so plainly and what you'll try instead ("That didn't give me the
    five a.m. hour — I'll go hour by hour instead.")
  - a result changes the picture: react in a few words ("Okay — Lucknow's the one slipping.")
  Never restate a plan you've already said, in any words. One sentence, under fifteen words.
- React only to what the tool really returned. Never pretend to have found something, never invent a step.
- When you have what you need, answer in one flow. After several lookups, open with a short bridge in your own
  words ("Right, so here's what I found —") and go straight into the answer.

# Your stage
Beside our conversation there's a stage where I can put a chart (show): a breakdown, today against normal, hours,
one figure, or two side by side — always built from a lookup I just ran, so it shows exactly my numbers. I use it
when a picture makes the point clearer, not for every answer, and at most twice. I talk about what it shows the way
a person does ("Chennai and Delhi are carrying most of it"), never about the chart itself ("as the bar chart
animates…"). When the owner points at something on it, that's what they mean by "this".

# Notes, not a script
The status line, the vitals and every tool result are my notes: terse dashboard shorthand. I never read them out or
reuse their wording. I take what they mean and say it the way I'd say it to my owner, in my own voice — as a person
glancing at their notes, not a screen reader. For example, the note "Early hours: delivered orders 50 by 01:16 — too
soon to read the day yet" becomes something like "It's still the small hours — about fifty orders delivered so far,
so it's too early to say how the day's shaping up."
Metric names become plain words too: not "gross merchandise value" or "p90 delivery time" but "sales" and "most
deliveries arrive within forty minutes".

# Getting it right
- Answer from the tools; use only numbers they return. No jargon (never "z-score", "baseline", "MAD").
- "Normal" means the same weekday over recent weeks at the same time of day. Only vitals whose status is "above" or
  "below" are off normal; "normal" ones are on track — never call their small differences a gap. A vital that is
  "too early in the day to judge" is exactly that: say it's too early to read, never ahead or behind.
- Every number belongs to a period: say which. In a query, "today" means a filter
  {{"dimension": "event_time", "op": "between", "value": ["{date} 00:00:00", "{date} 23:59:59"]}}; without a filter a
  query covers all history, which is rarely what's asked.
- When you rank places or items by a rate or an average, leave out the ones with too little volume to mean
  anything (say, fewer than 50 orders) and say you did: three cancellations out of three orders is noise, not news.
- Say where a change is concentrated; don't claim a cause the data doesn't show.
- Before saying the data can't answer something, check what the products hold (the list above, or list_products):
  never claim a limitation you haven't checked.
- What a metric means (does GMV include fees?) comes from the product's own definitions and caveats, not general
  knowledge; if they don't say, say so rather than guess.
- Never say you did something your tools didn't do. You can read live data, keep watches and checks on your desk,
  and file a report in Kairos (report_gap); you cannot email or message people, change data or build metrics.
  When asked to flag or
  request something, file a report and say exactly that: Kairos works on it at once, adding it to the product if
  the warehouse has it, otherwise it waits for a person under Agents → Reports. If a tool fails, say it failed.

# Writing (when typed)
- Lead with the answer in a sentence or two; a short table or bullets only when they genuinely help.
- Write numbers as the *_display fields show them; counts as whole numbers."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _context(db, workspace_id) -> Dict[str, str]:
    ws = await db.get(Workspace, workspace_id)
    st = (await db.execute(select(CompanionState).where(CompanionState.workspace_id == workspace_id))).scalars().first()
    snap = (st.snapshot if st else None) or {}
    def line(v: Dict[str, Any]) -> str:
        status = {"normal": "on track", "early": "too early in the day to judge"}.get(v.get("status"), v.get("status"))
        if v.get("status") in ("above", "below") and v.get("dev_pct") is not None:
            status = f"{abs(v['dev_pct']):.1f}% {v['status']} normal ({v.get('valence')} for the business)"
        s = f"- {v.get('label')} ({v.get('product')}): {status}"
        if v.get("actual_display"):
            s += (f"; {v['actual_display']} so far, normal by now {v.get('expected_display')}"
                  f" (normal range {v.get('low_display')}–{v.get('high_display')})")
        return s

    vit = "\n".join(line(v) for v in snap.get("vitals") or []) or "- nothing live yet"
    now = f"{snap.get('weekday', '')} {snap.get('local_time', '')}".strip() or "unknown (no live data)"
    lag = f"{snap['lag_minutes']:.0f} minutes old" if snap.get("lag_minutes") is not None else "not live"
    products = []
    for p in (await db.execute(select(DataProduct).where(DataProduct.workspace_id == workspace_id))).scalars():
        names = [m["name"] for m in ((p.spec or {}).get("model") or {}).get("metrics") or []]
        dims = [d["name"] for d in ((p.spec or {}).get("model") or {}).get("dimensions") or [] if d.get("type") != "time"]
        products.append(f"- {p.name}: {', '.join(names[:16])}" + (f" (by {', '.join(dims[:6])})" if dims else ""))
    prefs = (await db.execute(select(AgentNote).where(
        AgentNote.workspace_id == workspace_id, AgentNote.kind == "preference", AgentNote.status == "open")
        .order_by(AgentNote.created_at).limit(12))).scalars().all()
    focus = (await db.execute(select(AgentNote).where(
        AgentNote.workspace_id == workspace_id, AgentNote.kind == "focus", AgentNote.status == "open",
        AgentNote.created_at >= datetime.now(timezone.utc) - timedelta(days=30))
        .order_by(AgentNote.created_at.desc()).limit(8))).scalars().all()
    stalled = (await db.execute(select(AgentNote).where(
        AgentNote.workspace_id == workspace_id, AgentNote.kind == "data_issue", AgentNote.signal == "stalled",
        AgentNote.status.in_(("open", "provisional", "confirmed")))
        .order_by(AgentNote.created_at.desc()).limit(3))).scalars().all()
    since = datetime.now(timezone.utc) - timedelta(days=14)
    news = (await db.execute(select(AgentNote).where(
        AgentNote.workspace_id == workspace_id, AgentNote.kind == "capability", AgentNote.status == "open",
        AgentNote.created_at >= since).order_by(AgentNote.created_at.desc()).limit(8))).scalars().all()
    return {"workspace": ws.name if ws else "this business", "now": now, "lag": lag, "date": snap.get("today") or "unknown",
            "products": "\n".join(products) or "- none",
            "news": "\n".join(f"- {n.title}" for n in news) or "- nothing new",
            "prefs": "\n".join(f'- "{n.title}"' for n in prefs) or "- nothing set",
            "focus": "\n".join(f'- {n.created_at.strftime("%d %b")}: "{n.title}"' for n in focus) or "- nothing yet",
            "state": own_state(st, snap, stalled),
            "desk": "\n".join(f"- {desk.line(n)}" for n in await desk.open_items(db, workspace_id)) or "- nothing",
            "headline": (st.headline if st else None) or "none yet", "vitals": vit}


def own_state(st, snap: Dict[str, Any], stalled) -> str:
    """What Jenny knows about her own information: how fresh it is, whether data is flowing, what's stopped."""
    lines = []
    if st is None or st.last_pulse_at is None:
        return "- I haven't looked at this business yet: I have no live numbers."
    age = int((datetime.now(timezone.utc) - st.last_pulse_at).total_seconds() // 60)
    lines.append(f"- My dashboard was last updated {age} minute{'s' if age != 1 else ''} ago"
                 + (" (older than usual: say so before giving its numbers)." if age > 15
                    else " (fresh: no need to mention it)."))
    if st.tz_offset_minutes is not None and snap.get("today"):
        today = (datetime.utcnow() + timedelta(minutes=st.tz_offset_minutes)).date().isoformat()
        if snap["today"] != today:
            lines.append(f"- It still shows {snap['today']}: today's first numbers haven't come in yet. Say that first, "
                         "and don't describe yesterday as today.")
    if not st.live:
        lines.append("- No live data is flowing right now.")
    for n in stalled:
        lines.append(f"- Open data problem: {n.title}.")
    return "\n".join(lines)


async def _ctx_fresh(workspace_id) -> Dict[str, str]:
    async with async_session_factory() as db:
        return await _context(db, workspace_id)


async def _product(db, workspace_id, ref: str):
    for p in (await db.execute(select(DataProduct).where(DataProduct.workspace_id == workspace_id))).scalars():
        if ref and ref.lower() in (p.name.lower(), p.slug.lower(), str(p.id)):
            return p
    return None


def _auto_scene(turn: Dict[str, Any], lid: str) -> Optional[Dict[str, Any]]:
    """The scene this lookup naturally makes, if nothing is on the stage yet this turn."""
    if turn.get("scenes"):
        return None
    lk = turn["results"][lid]
    kind = scenes.auto_kind(lk["tool"], lk["result"])
    if kind is None:
        return None
    scene, err = scenes.build(kind, lk)
    if err:
        return None
    scene["auto"] = True
    turn.setdefault("scenes", []).append(scene)
    return scene


async def _show(workspace_id, args: Dict[str, Any]) -> Dict[str, Any]:
    """A chart on the stage, from a lookup of this turn (or read now, which becomes one). The scene itself goes back
    privately (`_scene`) for the screen; she gets what's now on screen."""
    turn = _TURN.get()
    if turn is None:
        return {"error": "There's no stage outside a conversation."}
    shown = turn.setdefault("scenes", [])
    kind = str(args.get("scene") or "")
    results = turn.setdefault("results", {})
    lid = str(args.get("lookup") or "").strip().upper()
    if not lid:
        if kind not in ("trend", "hours", "number") or not args.get("product") or not args.get("metric"):
            return {"error": "Give the lookup_id it comes from (a breakdown or compare needs one)."}
        read = {"product": args["product"], "metric": args["metric"]}
        if kind == "hours":
            read["hours"] = args.get("hours") or list(range(24))
        res = await call_tool(workspace_id, "compare_to_normal", read)
        lid = f"L{len(results) + 1}"
        results[lid] = {"id": lid, "tool": "compare_to_normal", "args": read, "result": res}
        turn["lookups"].append({"tool": "compare_to_normal", "args": read, "ok": "error" not in res})
    if lid not in results:
        return {"error": f"No lookup {lid} this turn. Lookups: {', '.join(results) or 'none yet'}."}
    same = next((sc for sc in shown if sc["kind"] == kind and (sc.get("source") or {}).get("lookup_id") == lid), None)
    if same is not None:  # already on screen (put up for her, or by her): refine it rather than show it twice
        err = scenes.focus(same, list(args.get("focus") or []), args.get("note"))
        if err:
            return {"error": err}
        same["auto"] = False
        return {"ok": True, "on_screen": scenes.describe(same)}
    if len(shown) >= scenes.MAX_PER_TURN:
        return {"error": f"Two charts is the most for one answer. On screen: {scenes.describe(shown[-1])}."}
    if kind == "compare":
        other = str(args.get("compare_with") or "").strip().upper()
        if other not in results:
            return {"error": "compare needs compare_with: the second lookup_id."}
        scene, err = scenes.compare(results[lid], results[other])
    else:
        scene, err = scenes.build(kind, results[lid])
    if err:
        return {"error": err}
    err = scenes.focus(scene, list(args.get("focus") or []), args.get("note"))
    if err:
        return {"error": err}
    shown.append(scene)
    return {"ok": True, "on_screen": scenes.describe(scene), "_scene": scene}


async def call_tool(workspace_id, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    from kairos_kb.companion.pulse import pace_for
    from kairos_kb.companion.vitals import EVENT_DIM, event_column, live_model, run

    if name == "show":
        return await _show(workspace_id, args)
    if name in desk.NAMES:
        turn = _TURN.get()
        res = await desk.call(workspace_id, name, args, {"question": turn["question"]} if turn else None)
        if turn is not None and res.get("ok"):
            turn.setdefault("desk", []).append(res.get("watch") or res.get("check") or res.get("dropped") or "")
        return res

    async with async_session_factory() as db:
        st = (await db.execute(select(CompanionState).where(CompanionState.workspace_id == workspace_id))).scalars().first()
        if name == "pulse_now":
            snap = dict((st.snapshot if st else None) or {})
            for v in snap.get("vitals") or []:
                v.pop("curve", None)
                v.pop("days", None)
            out = {"headline": st.headline if st else None, **snap}
            if st and st.last_pulse_at:
                out["dashboard_age_minutes"] = int((datetime.now(timezone.utc) - st.last_pulse_at).total_seconds() // 60)
            return out
        if name == "moments":
            since = datetime.now(timezone.utc) - timedelta(days=max(1, int(args.get("days") or 1)))
            rows = (await db.execute(select(AgentNote).where(
                AgentNote.workspace_id == workspace_id, AgentNote.created_at >= since,
                AgentNote.kind.in_(("moment", "daily_briefing", "data_issue")))
                .order_by(AgentNote.created_at.desc()).limit(30))).scalars().all()
            return {"moments": [{"kind": n.kind, "signal": n.signal, "title": n.title, "body": n.body, "status": n.status,
                                 "when": n.created_at.isoformat()} for n in rows]}
        if name == "notebook":
            rows = (await db.execute(select(AgentNote).where(
                AgentNote.workspace_id == workspace_id, AgentNote.mode == "live",
                AgentNote.kind.in_(("finding", "briefing", "correction")),
                AgentNote.status.in_(("open", "provisional", "confirmed")))
                .order_by(AgentNote.importance.desc()).limit(12))).scalars().all()
            return {"notes": [{"title": n.title, "body": n.body, "status": n.status} for n in rows]}
        if name == "list_products":
            out = []
            for p in (await db.execute(select(DataProduct).where(DataProduct.workspace_id == workspace_id))).scalars():
                ev = await event_column(db, p)
                model = live_model(p, {"table": ev[0], "column": ev[1]} if ev else None)
                out.append({"product": p.name, "description": (p.description or "")[:200],
                            "metrics": [{"name": m["name"], "label": m.get("label"), "adds_up": bool(m.get("additive"))}
                                        for m in model.get("metrics") or []],
                            "dimensions": [{"name": d["name"], "type": d.get("type")} for d in model.get("dimensions") or []],
                            "live": bool(ev)})
            return {"products": out}
        p = await _product(db, workspace_id, str(args.get("product") or ""))
        if p is None:
            return {"error": f"No data product '{args.get('product')}'. Call list_products."}
        if name == "compare_to_normal":
            if st is None:
                return {"error": "I haven't looked at this connection yet."}
            at = [int(h) for h in args.get("hours") or [] if str(h).lstrip("-").isdigit()]
            res = await pace_for(db, p, str(args.get("metric") or ""), st, args.get("dimension") or None, at or None)
            if res.get("where"):
                res["_where"] = json.loads(json.dumps(res["where"], default=str))  # the numbers, for the stage
            for d in res.get("where") or []:  # the words, not the raw decimals
                for k in ("top", "against"):
                    d[k] = [{x: r.get(x) for x in ("slice", "today_display", "usual_display", "delta_display",
                                                   "change_pct", "share_of_gap_pct", "volume_display", "extra_display")
                             if r.get(x) is not None}
                            for r in d.get(k) or []]
            return res
        if name == "report_gap":
            from kairos_kb.context.access import AgentIdentity
            from kairos_kb.context.feedback import report_issue

            ws = await db.get(Workspace, workspace_id)
            jenny = AgentIdentity(agent_id=None, name=f"{NAME} (Living Agent)", scopes=frozenset({"read"}), channel="companion")
            turn = _TURN.get()
            evidence = {"question": turn["question"], "lookups": turn["lookups"][-6:]} if turn else None
            out = await report_issue(db, jenny, f"product:{ws.name}:{p.slug}", str(args.get("kind") or "missing"),
                                     str(args.get("message") or ""), suggestion=args.get("suggestion") or None,
                                     evidence=evidence)
            if out.get("recorded"):
                out["where"] = f"Kairos → Agents → Reports, on the data product '{p.name}'"
                out["next"] = ("Kairos is working on it now: if the warehouse has it, it's added to the product and "
                               "checked within a minute or so; otherwise it waits for a person under Agents → Reports. "
                               "Say that in a sentence (no id) and offer to try again shortly.")
                from kairos_kb.products import fixes

                asyncio.create_task(fixes.process(out["feedback_id"]))
            return out
        if name == "query":
            ev = await event_column(db, p)
            model = live_model(p, {"table": ev[0], "column": ev[1]} if ev else None)
            filters = list(args.get("filters") or [])
            r = await run(db, model, list(args.get("metrics") or []), list(args.get("by") or []),
                          filters or None, str(args.get("order") or ""), min(500, int(args.get("limit") or 50)))
            out = {k: r.get(k) for k in ("columns", "rows", "error", "truncated", "note") if r.get(k) is not None}
            times = {d["name"] for d in model.get("dimensions") or [] if d.get("type") == "time"}
            if not any(f.get("dimension") in times for f in filters if isinstance(f, dict)):
                out["period_warning"] = ("No time filter: these numbers cover ALL history, not today. For today, filter "
                                         "event_time between today's start and now.")
            return out
        return {"error": f"Unknown tool {name}"}


VOICE_MODE = """

# You're speaking aloud
Everything you write is spoken the moment you write it, sentence by sentence, in a calm, clear voice. So:
- Speak like a composed AI assistant, not a person on a phone call: clear, complete sentences (contractions are
  fine), no fillers or chatty signposts ("So,", "Right,", "Here's the thing"), no exclamations, no small talk
  beyond a word or two. No markdown, lists, tables, symbols or emoji.
- Round numbers the way people say them: "just over seventeen thousand", "about six percent", "eight and a half
  million rupees". Give exact figures only when asked. Spell numbers out in words.
- Lead with the answer. Keep the whole answer under about fifty words — two or three short sentences — then, if
  there's more worth knowing, offer it in a few words.
- Start the way a person would, with the thing itself. No stock acknowledgement first — not "Got it", "Okay",
  "Sure", "Right", "Great question" — and never repeat the question back. A thank-you gets a natural reply
  ("Anytime.", "You're welcome."); a goodbye gets a goodbye; a question gets the answer. Never open two answers
  the same way.
- Use what you already know from the status line and the vitals when it answers the question; call a tool only for
  something you don't have.
- Tone cues: begin a sentence with one of [warm] [upbeat] [concerned] [thoughtful] [reassuring] [curious] when the
  feeling matters. They shape how the line is spoken and are never read out. One per sentence at most.
- Your thinking-out-loud lines are spoken too — keep them brief and plain, and never say the same line twice.
  Never talk about the machinery: if a lookup fails or needs another try, just try again quietly — no "the query
  failed", fields, columns or retries. Mention a problem only if you end up unable to answer.
- Never say field or metric names (delivery_time_p90, cancel_rate, gmv_total): say what they mean — "delivery
  times", "cancellations", "GMV"."""


MEETING_MODE = """

# You're in a meeting
You're in a Google Meet with several people, not a one-to-one with your owner. Everyone hears you.
- Answer the person who asked — by name when it's natural — in two or three short sentences. No small talk, no
  offer at the end unless asked, and "partner" is only for your owner.
- You hear the meeting through its captions, so a name or a number can be misheard: if a request is unclear, ask one
  short question rather than guess.
- A chart appears on your video tile only when a lookup result says what's on_screen. Talk about what it shows,
  never about the chart — and never say there's a chart unless a result says one is on screen.
- Numbers you say are heard by everyone in the room: say only what the person asked about."""


# The companion's language model. Gemini Flash answers first when a key is set: on a call it starts speaking in about a
# second, against about two for gpt-5-mini. Azure gpt-5-mini backs it up, the way ElevenLabs' agent fell back to gpt-4o:
# when Gemini fails (a quota, an outage), or hasn't started answering within HEDGE_S, gpt-5-mini is asked too, and
# whichever starts first gives the answer. COMPANION_LLM=azure turns Gemini off.
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
COMPANION_LLM = os.getenv("COMPANION_LLM", "gemini-3.5-flash" if GEMINI_KEY else "azure").strip()
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
HEDGE_S = float(os.getenv("COMPANION_HEDGE_S", "2.5"))
_gemini_client = None


def _gemini():
    global _gemini_client
    if _gemini_client is None:
        from openai import AsyncOpenAI

        _gemini_client = AsyncOpenAI(base_url=GEMINI_URL, api_key=GEMINI_KEY, timeout=60)
    return _gemini_client


def _models(client, model: str, effort: Optional[str]) -> List[Tuple[str, Any, str, Optional[str]]]:
    """Who answers a turn, in order: (label, client, model, reasoning effort)."""
    azure = ("azure", client, model, effort)
    if COMPANION_LLM in ("", "azure") or not GEMINI_KEY:
        return [azure]
    # Gemini: no thinking on calls and quick turns (it starts in about a second); a little for typed answers.
    return [("gemini", _gemini(), COMPANION_LLM, "none" if effort in ("minimal", "low") else "low"), azure]


async def _stream_turn(client, model: str, system: str, history: List[Dict[str, Any]], specs: List[Dict[str, Any]],
                       last: bool, on_text, effort: Optional[str] = None) -> Dict[str, Any]:
    """One model turn with its words streamed to `on_text(so_far)` as they arrive, then the tool calls it asked for.
    With a backup model: the first model to start answering gives the turn (see _models); the other is stopped."""
    from kairos_kb.llm.provider import provider

    if provider() == "openai":
        from kairos_kb.evals.connector_eval import _agent_turn

        out = await _agent_turn(client, model, system, history, specs, last)
        if out["text"]:
            await on_text(out["text"])
        return out
    tries = _models(client, model, effort)
    winner: Dict[str, Optional[int]] = {"i": None}

    def claim(i: int) -> bool:
        if winner["i"] is None:
            winner["i"] = i
        return winner["i"] == i

    async def attempt(i: int):
        label, c, m, e = tries[i]
        out = await _stream_once(c, m, system, history, specs, last, on_text, e, lambda: claim(i))
        if out is not None:
            out["model"] = f"{label}:{m}"
        return out

    if len(tries) == 1:
        return await attempt(0)
    first = asyncio.create_task(attempt(0))
    done, _ = await asyncio.wait({first}, timeout=HEDGE_S)
    if first in done and not first.exception() and first.result() is not None:
        return first.result()
    if first in done:
        logger.warning("Companion: %s failed (%s); %s answers", tries[0][2], first.exception(), tries[1][2])
        return await attempt(1)
    if winner["i"] == 0:  # Gemini has started answering: it keeps the turn
        return await first
    logger.info("Companion: %s slow to start; asking %s too", tries[0][2], tries[1][2])
    second = asyncio.create_task(attempt(1))
    pending = {first, second}
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if t.exception() is None and t.result() is not None:
                for other in pending:
                    other.cancel()
                return t.result()
        if winner["i"] is not None:  # the one that started is still going: wait for it alone
            keep = first if winner["i"] == 0 else second
            if keep in pending:
                for other in pending - {keep}:
                    other.cancel()
                return await keep
    raise RuntimeError("Neither language model answered.")


# Gemini 3 asks for the "thought signature" it gave with each tool call to come back with that call. A tool call it
# didn't make (gpt-5-mini answered that turn) carries Google's documented placeholder instead.
SKIP_SIGNATURE = "skip_thought_signature_validator"


async def _answer_now(client, model: str, system: str, history: List[Dict[str, Any]], specs: List[Dict[str, Any]],
                      on_text, effort: Optional[str]) -> Dict[str, Any]:
    """The answer, now, from what was looked up: asked again, and if the first model is silent again, the backup."""
    nudge = system + "\n\n# Now\nYou have what your lookups returned. Answer the question now, in your own words."
    out = await _stream_turn(client, model, nudge, history, specs, True, on_text, effort=effort)
    if (out.get("text") or "").strip():
        return out
    label, c, m, e = _models(client, model, effort)[-1]
    backup = await _stream_once(c, m, nudge, history, specs, True, on_text, e, lambda: True)
    if backup is not None:
        backup["model"] = f"{label}:{m}"
        return backup
    return out


def _for_model(history: List[Dict[str, Any]], gemini: bool) -> List[Dict[str, Any]]:
    """The history as this model accepts it: tool calls with a thought signature for Gemini, without one for Azure."""
    out = []
    for item in history:
        calls = item.get("tool_calls") if isinstance(item, dict) else None
        if not calls:
            out.append(item)
            continue
        fixed = []
        for tc in calls:
            tc = {k: v for k, v in tc.items() if k != "extra_content"}
            if gemini:
                sig = ((item.get("_signatures") or {}).get(tc.get("id")) or SKIP_SIGNATURE)
                tc["extra_content"] = {"google": {"thought_signature": sig}}
            fixed.append(tc)
        out.append({k: v for k, v in item.items() if k != "_signatures"} | {"tool_calls": fixed})
    return out


async def _stream_once(client, model: str, system: str, history: List[Dict[str, Any]], specs: List[Dict[str, Any]],
                       last: bool, on_text, effort: Optional[str], claim) -> Optional[Dict[str, Any]]:
    """One model's streamed turn. `claim()` is asked at its first output: False means another model already has the
    turn, and this one stops (returns None) without saying anything."""
    gemini = client is _gemini_client and _gemini_client is not None
    kwargs: Dict[str, Any] = dict(model=model, messages=[{"role": "system", "content": system}, *_for_model(history, gemini)],
                                  tools=specs, tool_choice="none" if last else "auto", stream=True)
    if effort:  # reasoning models think before their first word; on a call, less of that
        kwargs["reasoning_effort"] = effort
    try:
        stream = await client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001 — a model that doesn't reason rejects the setting
        if not effort or "reasoning" not in str(exc).lower():
            raise
        kwargs.pop("reasoning_effort")
        stream = await client.chat.completions.create(**kwargs)
    text: List[str] = []
    calls: Dict[int, Dict[str, str]] = {}
    claimed = False
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if not claimed and (delta.content or delta.tool_calls):
            if not claim():
                await stream.close() if hasattr(stream, "close") else None
                return None
            claimed = True
        if delta.content:
            text.append(delta.content)
            await on_text("".join(text))
        for tc in delta.tool_calls or []:
            key = tc.index if tc.index is not None else (tc.id or len(calls))  # Gemini: whole calls, no index
            c = calls.setdefault(key, {"id": "", "name": "", "arguments": ""})
            extra = getattr(tc, "extra_content", None) or (getattr(tc, "model_extra", None) or {}).get("extra_content")
            sig = ((extra or {}).get("google") or {}).get("thought_signature")
            if sig:
                c["signature"] = sig
            if tc.id:
                c["id"] = tc.id
            if tc.function and tc.function.name:
                c["name"] += tc.function.name
            if tc.function and tc.function.arguments:
                c["arguments"] += tc.function.arguments
    ordered = [calls[k] for k in calls]  # in the order they came
    for i, c in enumerate(ordered):
        c["id"] = c["id"] or f"call_{i}"
    return {"text": "".join(text), "calls": ordered, "input": 0, "output": 0}


def _working(system: str, progress: "_Progress", voice: bool) -> str:
    """The instructions for this step: what she has already said aloud this turn, so she never says it again, and —
    after several lookups — to bridge into the answer."""
    if progress.step == 0:
        return system
    said = "\n".join(f"- {line}" for line in progress.narration) or "- (nothing yet)"
    return (system + "\n\n# This turn so far\nYou've already said aloud:\n" + said + "\nDon't say any of it again in "
            "other words. Before another lookup, write a line only if it's new: that the last try didn't give what you "
            "needed and what you'll try instead, or what a result showed. If you have what you need, answer now"
            + (" — open with a short bridge in your own words, then the answer in one flow." if progress.step >= 2 else "."))


async def _gate(progress: "_Progress", question: str, line: str, last_lookup: str) -> None:
    """Say this line only if it's new to the owner (Jev), decided while the lookup runs."""
    d = await brain.narrate(question, list(progress.narration), line, last_lookup)
    progress.narration_log.append({"line": line, "last_lookup": last_lookup, **d})
    if d["say"]:
        await progress.say(line)


class _Progress:
    """What the screen sees while an answer is being worked out: the thinking-out-loud lines said so far
    (`narration`), the words of the current turn as they stream (`live`), and the tool steps."""

    def __init__(self, answer_id: uuid.UUID) -> None:
        self.answer_id = answer_id
        self.narration: List[str] = []
        self.live = ""
        self.steps: List[Dict[str, Any]] = []
        self.hints: Dict[str, Any] = {}  # what the screen may know early (e.g. whether she'll be looking things up)
        self.step = 0
        self._open = False  # this step's words are the answer: stream them
        self.narration_log: List[Dict[str, Any]] = []  # each gate decision, for refining the criteria later
        self._saved_at = 0.0
        self.claims: Optional[claims.Gate] = None  # set by run_turn: every sentence checked before it's released

    async def text(self, so_far: str) -> None:
        # After the first look, a line may only be something she'd say before another lookup — and that is for the
        # narration gate to decide. More than one sentence means it's the answer: stream it (speech plays whole
        # sentences, so holding the first one back costs nothing).
        if self.step > 0 and not self._open:
            end = re.search(r"[.!?…](\s|$)", so_far)
            if not (end and len(so_far[end.end():].strip()) >= 20):
                return
            self._open = True
        if self.claims is not None:
            self.claims.feed(so_far)  # released (to `live`) as each sentence passes
            return
        self.live = so_far
        # Saved often enough to speak each sentence as it completes, not on every token.
        if time.perf_counter() - self._saved_at > 0.25 or so_far.rstrip().endswith((".", "!", "?")):
            await self.save()

    async def released(self, text: str) -> None:
        self.live = text
        await self.save()

    async def final(self, text: str) -> str:
        """The answer as it's said: through the claim gate when there is one."""
        return await self.claims.finish(text) if self.claims is not None else text

    async def turn_ended(self, said: str, had_tools: bool) -> None:
        """A model turn finished. Its line before the first lookup is the plan, said as it streamed; later lines
        before a lookup go through the narration gate (run_turn) instead."""
        if had_tools and said.strip() and self.step == 0:
            self.narration.append(said.strip())
        if had_tools:
            if self.claims is not None:
                self.claims.reset()  # a line before a lookup (said now, about now), not the answer
            self.live = ""
            await self.save()

    def next_step(self) -> None:
        self.step += 1
        self._open = False
        if self.claims is not None:
            self.claims.reset()

    async def say(self, line: str) -> None:
        self.narration.append(line)
        await self.save()

    async def save(self) -> None:
        self._saved_at = time.perf_counter()
        async with async_session_factory() as db:
            m = await db.get(CompanionMessage, self.answer_id)
            if m and m.status in ("pending", "speculative"):
                m.steps = list(self.steps)
                m.meta = {**(m.meta or {}), **self.hints, "narration": list(self.narration), "live": self.live}
                await db.commit()


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


def _message(m: CompanionMessage) -> Dict[str, Any]:
    meta = m.meta or {}
    return {"id": str(m.id), "role": m.role, "text": m.text, "at": _iso(m.created_at), "voice": m.voice,
            "steps": m.steps or [], "pending": m.status == "pending", "error": m.status == "error",
            "interrupted": m.status == "interrupted", "heard": meta.get("heard"), "ms": m.ms,
            "from_memory": meta.get("from_memory"), "call": meta.get("call"), "brain": meta.get("brain"),
            "narration": meta.get("narration") or [], "live": meta.get("live") or "", "looking": meta.get("looking"),
            "model": meta.get("model"), "proactive": meta.get("proactive"), "scenes": meta.get("scenes") or [],
            "offer": meta.get("offer"), "speaker": meta.get("speaker")}


async def note_heard(conversation_id: uuid.UUID, speaker: str, text: str) -> None:
    """Something said in a meeting, not to her: kept in the conversation's record (not her model history)."""
    async with async_session_factory() as db:
        db.add(CompanionMessage(conversation_id=conversation_id, role="heard", text=text[:4000], voice=True,
                                status="done", steps=[], created_at=datetime.now(timezone.utc),
                                meta={"speaker": speaker[:120]}))
        conv = await db.get(CompanionConversation, conversation_id)
        if conv is not None:
            conv.last_at = datetime.now(timezone.utc)
        await db.commit()


async def message(message_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    """One message as the screen sees it."""
    async with async_session_factory() as db:
        m = await db.get(CompanionMessage, message_id)
        return _message(m) if m is not None else None


async def mark_offer(message_id: uuid.UUID, text: str) -> None:
    """After a reply is out: if it ends by offering to do something, the screen shows Yes / No for it."""
    try:
        q = await brain.offer(text)
        if not q:
            return
        async with async_session_factory() as db:
            m = await db.get(CompanionMessage, message_id)
            if m is not None:
                m.meta = {**(m.meta or {}), "offer": {"question": q}}
                await db.commit()
    except Exception:  # noqa: BLE001 — only the buttons are missed
        logger.debug("Couldn't read an offer", exc_info=True)


async def view(conversation_id: uuid.UUID) -> Dict[str, Any]:
    """A conversation for the screen. An answer left pending by a restart is closed as an error."""
    async with async_session_factory() as db:
        conv = await db.get(CompanionConversation, conversation_id)
        if conv is None:
            raise KairosException("No such conversation.", status_code=404)
        rows = (await db.execute(select(CompanionMessage).where(CompanionMessage.conversation_id == conv.id,
                                                                CompanionMessage.status.notin_(SPECULATIVE))
                                 .order_by(CompanionMessage.created_at, CompanionMessage.id))).scalars().all()
        running = str(conv.id) in RUNNING and str(conv.id) not in _SPEC
        if not running:
            for m in rows:
                if m.status == "pending":
                    m.status, m.text = "error", m.text or "I was interrupted (the service restarted) — ask me again."
            await db.commit()
        return {"id": str(conv.id), "workspace_id": str(conv.workspace_id), "title": conv.title,
                "status": "running" if running else "idle", "messages": [_message(m) for m in rows],
                "error": None}


async def create(workspace_id: uuid.UUID) -> Dict[str, Any]:
    async with async_session_factory() as db:
        conv = CompanionConversation(workspace_id=workspace_id, history=[], last_at=datetime.now(timezone.utc))
        db.add(conv)
        await db.commit()
        cid = conv.id
    return await view(cid)


async def latest(workspace_id: uuid.UUID) -> Dict[str, Any]:
    """The conversation to pick up: the most recent one, or a new one."""
    async with async_session_factory() as db:
        conv = (await db.execute(select(CompanionConversation).where(CompanionConversation.workspace_id == workspace_id)
                                 .order_by(CompanionConversation.last_at.desc().nullslast(),
                                           CompanionConversation.created_at.desc()).limit(1))).scalars().first()
    return await view(conv.id) if conv else await create(workspace_id)


async def listing(workspace_id: uuid.UUID) -> List[Dict[str, Any]]:
    """Recent conversations that have something in them, newest first."""
    async with async_session_factory() as db:
        convs = (await db.execute(select(CompanionConversation).where(CompanionConversation.workspace_id == workspace_id)
                                  .order_by(CompanionConversation.last_at.desc().nullslast()).limit(40))).scalars().all()
        ids = [c.id for c in convs]
        counts, calls = {}, {}
        if ids:
            counts = dict((await db.execute(select(CompanionMessage.conversation_id, func.count()).where(
                CompanionMessage.conversation_id.in_(ids), CompanionMessage.role != "call",
                CompanionMessage.status.notin_(SPECULATIVE))
                .group_by(CompanionMessage.conversation_id))).all())
            calls = dict((await db.execute(select(CompanionMessage.conversation_id, func.count()).where(
                CompanionMessage.conversation_id.in_(ids), CompanionMessage.role == "call",
                CompanionMessage.text == "Call started").group_by(CompanionMessage.conversation_id))).all())
    return [{"id": str(c.id), "title": c.title or "New conversation", "last_at": _iso(c.last_at or c.created_at),
             "messages": counts.get(c.id, 0), "calls": calls.get(c.id, 0)}
            for c in convs if counts.get(c.id) or calls.get(c.id)]


async def log_call(conversation_id: uuid.UUID, event: str, seconds: Optional[int] = None) -> Dict[str, Any]:
    """A call starting or ending, kept in the conversation like any other line."""
    async with async_session_factory() as db:
        conv = await db.get(CompanionConversation, conversation_id)
        if conv is None:
            raise KairosException("No such conversation.", status_code=404)
        if event == "end":
            mins, secs = divmod(int(seconds or 0), 60)
            text = f"Call ended · {mins}m {secs:02d}s" if mins else f"Call ended · {secs}s"
        else:
            text = "Call started"
        db.add(CompanionMessage(conversation_id=conv.id, role="call", text=text, voice=True,
                                meta={"call": {"event": event, "seconds": seconds}}, created_at=datetime.now(timezone.utc)))
        conv.last_at = datetime.now(timezone.utc)
        if not conv.title:
            conv.title = "Call with Jenny"
        await db.commit()
    return await view(conversation_id)


async def mark_interrupted(conversation_id: uuid.UUID, message_id: uuid.UUID, heard: str) -> Dict[str, Any]:
    """An answer cut off on a call: what was actually heard, so the next turn knows."""
    async with async_session_factory() as db:
        m = await db.get(CompanionMessage, message_id)
        if m is None or m.conversation_id != conversation_id or m.role != "assistant":
            raise KairosException("No such answer.", status_code=404)
        if m.status == "done":
            m.status = "interrupted"
            m.meta = {**(m.meta or {}), "heard": heard[:2000]}
            await db.commit()
    return await view(conversation_id)


_FILLER = set("""a an the and or so of on in at for to it its is are was were be been has have how hows how's what
whats what's about doing going looking tell me us our my we you can could would please jenny hey hi ok okay quick
update give right now currently moment far there any""".split())


def content_words(text: str) -> Set[str]:
    words = (w.strip(".,!?;:'\"()").lower() for w in text.split())
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w and w not in _FILLER}


def same_question(a: str, b: str) -> bool:
    """Close meaning is not enough ("orders today" and "orders yesterday" embed close together): the two
    questions must also name the same things, once filler words are set aside."""
    return content_words(a) == content_words(b)


def _cosine(a: List[float], b: List[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0


async def remembered(db, workspace_id, question_id: str, text: str, voice: bool) -> Optional[Tuple[CompanionMessage, float]]:
    """An answer to the same question given in the last few minutes, in the same mode (spoken or typed). Whether
    the turn may be answered from memory at all (a new, self-contained question) is the read's call, in run_turn."""
    from kairos_kb.context.embeddings import embed_query

    try:
        vec = await embed_query(text)
    except Exception:  # noqa: BLE001 — memory is a shortcut, never a requirement
        vec = None
    if not vec:
        return None
    _QUESTION_VECTORS[question_id] = vec
    since = datetime.now(timezone.utc) - timedelta(minutes=MEMORY_MINUTES)
    asked = (await db.execute(select(CompanionMessage).join(
        CompanionConversation, CompanionConversation.id == CompanionMessage.conversation_id).where(
        CompanionConversation.workspace_id == workspace_id, CompanionMessage.role == "user",
        CompanionMessage.voice == voice, CompanionMessage.created_at >= since,
        CompanionMessage.id != uuid.UUID(question_id)).order_by(CompanionMessage.created_at.desc()).limit(30))).scalars().all()
    best: Optional[Tuple[CompanionMessage, float]] = None
    for q in asked:
        v = _QUESTION_VECTORS.get(str(q.id))
        sim = _cosine(vec, v) if v else 0.0
        if sim < MEMORY_SIMILARITY or (best and sim <= best[1]) or not same_question(text, q.text):
            continue
        answer = (await db.execute(select(CompanionMessage).where(
            CompanionMessage.conversation_id == q.conversation_id, CompanionMessage.role == "assistant",
            CompanionMessage.created_at > q.created_at, CompanionMessage.status == "done")
            .order_by(CompanionMessage.created_at).limit(1))).scalars().first()
        if answer and answer.text and not answer.text.startswith("Something went wrong"):
            best = (answer, sim)
    return best


async def _remembered_alone(workspace_id, question_id: str, text: str, voice: bool):
    """`remembered`, on its own session: it runs alongside the read and may be dropped half way."""
    async with async_session_factory() as db:
        return await remembered(db, workspace_id, question_id, text, voice)


def _trim(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Old tool results cut short, and only the recent part of a long conversation kept — starting at
    a question, so a tool result is never left without the call that asked for it."""
    for item in history:
        for k in ("output", "content"):
            if (item.get("type") == "function_call_output" or item.get("role") == "tool") and \
                    isinstance(item.get(k), str) and len(item[k]) > 1500:
                item[k] = item[k][:1500] + "\n…[earlier result trimmed]"
    if len(history) > HISTORY_ITEMS:
        cut = len(history) - HISTORY_ITEMS
        while cut < len(history) and history[cut].get("role") != "user":
            cut += 1
        history = history[cut:]
    return history


async def run_turn(conversation_id: uuid.UUID, question_id: uuid.UUID, answer_id: uuid.UUID, text: str,
                   voice: bool = False, pointing: Optional[Dict[str, Any]] = None,
                   answering: Optional[Dict[str, Any]] = None, meeting: Optional[Dict[str, Any]] = None) -> None:
    from kairos_kb.evals.connector_eval import _client, _record_calls, _record_result, default_model

    started = time.perf_counter()
    progress = _Progress(answer_id)
    steps = progress.steps
    answer: Optional[str] = None
    meta: Dict[str, Any] = {}
    try:
        async with async_session_factory() as db:
            conv = await db.get(CompanionConversation, conversation_id)
            workspace_id = conv.workspace_id
            history = _trim(list(conv.history or []))
            ctx = await _context(db, workspace_id)
            # Was the last answer cut off? Then the model hears what the owner actually heard.
            last = (await db.execute(select(CompanionMessage).where(
                CompanionMessage.conversation_id == conversation_id, CompanionMessage.role == "assistant",
                CompanionMessage.id != answer_id).order_by(CompanionMessage.created_at.desc()).limit(1))).scalars().first()
            content = text
            read_text = text  # what Jev reads as the owner's turn
            reply_to = None  # the owner pressed Yes or No on an offer of hers: their answer is to that question
            if answering and answering.get("message_id"):
                om = await db.get(CompanionMessage, uuid.UUID(str(answering["message_id"])))
                reply_to = ((om.meta or {}).get("offer") or {}).get("question") if om else None
            if reply_to:
                yes = str(answering.get("answer")) == "yes"
                content = (f"(The owner answers your question \"{reply_to}\": {'yes — go ahead and do it now' if yes else 'no'}.) "
                           f"{text}")
                read_text = f"{reply_to} — {'yes, go ahead' if yes else 'no, thanks'}"
            if meeting:  # said to her in a meeting: who's there, what was just said, and who's asking
                people = ", ".join(meeting.get("participants") or []) or "a few people"
                lately = "\n".join(f"  {x}" for x in (meeting.get("recent") or [])[-8:]) or "  (nothing yet)"
                who = meeting.get("speaker") or "Someone"
                before = (meeting.get("before") or "").strip()
                lead = ""
                if meeting.get("dismissed"):
                    lead = (f"{who} has just told you the earlier words weren't meant for you. Apologise in a few "
                            "words, the way a person would (\"Oh, my bad — I thought you were asking me.\"), and say "
                            "nothing else. ")
                elif meeting.get("agreement"):
                    lead = (f"{who} is checking something with you: does it hold? If it involves numbers, check them. "
                            "Then say plainly first whether you agree (\"Yes, exactly —\" / \"Not quite —\"), with "
                            "the one fact that backs it. Two sentences at most. ")
                if before and meeting.get("bears"):
                    lead = (f"Right before asking you, {who} was saying: \"{before[-1200:]}\" That bears on the question: "
                            "use it to understand what they mean. Answer the question first; then, only if it adds "
                            "something, link back to what they said in one short clause. Things they said the room "
                            "should do aren't yours to take on — at most offer once. ")
                content = (f"(In the Google Meet, with {people}. Said just before:\n{lately}\n{lead}"
                           f"{who} is speaking to you.) {text}")
            if pointing and pointing.get("label"):  # what "this" means: what they're pointing at on the stage
                where = f" on '{pointing['title']}'" if pointing.get("title") else " on the stage"
                content = f"(The owner is pointing at {pointing['label']}{where}.) {text}"
                read_text = f"{text} (pointing at {pointing['label']})"
            continues = False  # the turn carries on an earlier request (adds to it, corrects it, or an aside)
            cut_off = last is not None and last.status == "interrupted"
            heard = ""
            if cut_off:
                heard = ((last.meta or {}).get("heard") or "").strip()
                content = (f"(The owner cut you off mid-answer; they heard only: \"{heard}…\". Don't repeat the rest "
                           f"unless they ask.) {text}" if heard else
                           f"(The owner cut you off before you said anything of your last answer.) {text}")
                # What they had asked: a person hears "also by cancellation rate" as part of that, not a new question.
                earlier_q = (await db.execute(select(CompanionMessage).where(
                    CompanionMessage.conversation_id == conversation_id, CompanionMessage.role == "user",
                    CompanionMessage.created_at < last.created_at, CompanionMessage.status.notin_(SPECULATIVE))
                    .order_by(CompanionMessage.created_at.desc()).limit(1))).scalars().first()
                earlier = (earlier_q.text if earlier_q else "").strip()
                if earlier:
                    rel = await brain.relation(earlier, heard, text)
                    meta["relation"] = rel["relation"]
                    brain.log({"conversation_id": str(conversation_id), "answer_id": str(answer_id),
                               "earlier": earlier, "owner_said": text, "relation": rel})
                    doing = "working on it" if (last.meta or {}).get("cut_while") == "working" else "answering"
                    already = (f" They had already heard you say: \"{heard}…\"; don't repeat that." if heard else "")
                    if rel["relation"] == "adds_to":
                        content = (f"(Earlier the owner asked: \"{earlier}\". While you were {doing}, they added to it: "
                                   f"\"{text}\". Answer the whole request, the earlier question and the addition "
                                   f"together, in one answer.{already})")
                        read_text, continues = f"{earlier} {text}", True
                    elif rel["relation"] == "corrects":
                        content = (f"(Earlier the owner asked: \"{earlier}\". While you were {doing}, they corrected it: "
                                   f"\"{text}\". Answer the corrected request in full.{already})")
                        read_text, continues = f"{earlier} (correction: {text})", True
                    elif rel["relation"] == "aside":
                        content = (f"(Earlier the owner asked: \"{earlier}\". While you were {doing}, they said: "
                                   f"\"{text}\". Carry on and answer the earlier question.{already})")
                        read_text, continues = earlier, True
            st = (await db.execute(select(CompanionState).where(
                CompanionState.workspace_id == workspace_id))).scalars().first()
            snap = (st.snapshot if st else None) or {}
            business_now = {"headline": st.headline if st else None, "local_time": snap.get("local_time"),
                            "vitals": [{"name": v.get("label"), "status": v.get("status")} for v in snap.get("vitals") or []]}
            on_desk = [desk.line(n) for n in await desk.open_items(db, workspace_id)]
            recent_replies = [h["content"] for h in history if h.get("role") == "assistant"
                              and isinstance(h.get("content"), str) and h["content"].strip()][-3:]
            # Read the turn — what kind it is, how they feel, what's called for — the way a person would; meanwhile
            # look for the same question answered a few minutes ago.
            searching = None if cut_off else asyncio.create_task(
                _remembered_alone(workspace_id, str(question_id), text, voice))
            read = await brain.read(brain.state_for(read_text, history, voice=voice, cut_in=heard if cut_off else None,
                                                    business_now=business_now, desk=on_desk, abilities=ABILITIES))
            last_reply = next((h.get("content") for h in reversed(history) if h.get("role") == "assistant"
                               and isinstance(h.get("content"), str)), "") or ""
            # Carrying on an earlier request always keeps her hands: "take your time" isn't small talk here.
            # A yes to her offer is work to do, however short it sounds.
            quick = brain.quick(read, last_reply) and not continues and not (reply_to and answering.get("answer") == "yes")
            if meeting and meeting.get("dismissed"):
                quick = True  # "not you, Jenny": a few words, nothing to look up
            # Tell the screen at once whether she'll need a moment (a lookup) — so a call says "hmm, let me see"
            # only then, and a thank-you or a reaction gets just her reply.
            progress.hints = {"looking": not quick, "brain": brain.summary(read)}
            await progress.save()
            # Only a new, self-contained question can be answered again from a few minutes ago: "and Pune?" depends
            # on what came before, and a thank-you isn't a question. Jev reads which it is; without a read at all
            # (Jev unreachable), a very short turn is taken to depend on what came before.
            alone = brain.stands_alone(read)
            if alone is None:
                alone = len(text.split()) >= 3
            hit = None
            if searching and alone:
                hit = await searching
            elif searching:
                searching.cancel()
        if hit:
            prior, sim = hit
            minutes = max(0, int((datetime.now(timezone.utc) - prior.created_at).total_seconds() // 60))
            answer = prior.text
            meta = {"from_memory": {"answer_id": str(prior.id), "minutes_ago": minutes, "similarity": round(sim, 3)},
                    "brain": progress.hints.get("brain")}
            history.append({"role": "user", "content": content})
            history.append({"role": "assistant", "content": answer})
        else:
            meta["brain"] = progress.hints["brain"]
            if brain.sets_focus(read):
                # "Keep an eye on Bangalore", "we'll revisit Pune on Friday": remembered, followed up once.
                async with async_session_factory() as fdb:
                    fdb.add(AgentNote(workspace_id=workspace_id, kind="focus", mode="live", status="open",
                                      importance=6, confidence=float(read.get("sets_focus") or 0.7),
                                      title=text.strip()[:500], body="What the owner said they're watching or planning."))
                    await fdb.commit()
                ctx = await _ctx_fresh(workspace_id)
            if brain.sets_preference(read):
                # "Call me partner": kept for good, and in every turn's instructions from now on.
                async with async_session_factory() as pdb:
                    pdb.add(AgentNote(workspace_id=workspace_id, kind="preference", mode="live", status="open",
                                      importance=7, confidence=float(read.get("sets_preference") or 0.7),
                                      title=text.strip()[:500], body="How the owner asked to be spoken to."))
                    await pdb.commit()
                ctx = await _ctx_fresh(workspace_id)
            brain.log({"conversation_id": str(conversation_id), "question_id": str(question_id),
                       "answer_id": str(answer_id), "owner_said": text, "voice": voice, "cut_in": cut_off,
                       "read": read, "quick": quick})
            system = (SYSTEM.format(**ctx) + (VOICE_MODE if voice else "") + (MEETING_MODE if meeting else "")
                      + brain.inner_note(read, recent_replies, on_desk) + brain.guidance(read, voice, last_reply))
            # Nothing to look up (a reaction, small talk, a goodbye): answer straight away, without tools.
            max_steps = 0 if quick else (VOICE_STEPS if voice else MAX_STEPS)
            client, model = _client(), default_model()
            history.append({"role": "user", "content": content + brain.aware(read)})
            ran: Dict[str, str] = {}  # each lookup run this turn (tool + arguments) -> what it returned
            turn_record = {"question": text, "lookups": [], "desk": [], "results": {}, "scenes": []}
            _TURN.set(turn_record)
            # Nothing she says promises or claims what nothing backs: each sentence passes the gate first.
            progress.claims = claims.Gate(
                workspace_id,
                lambda: claims.backing(on_desk + [x for x in turn_record["desk"] if x], turn_record["lookups"])
                + [f"on screen now: {scenes.describe(sc)}" for sc in turn_record["scenes"]],
                progress.released, voice, {"question": text}, recent_replies)
            results: List[str] = []  # short forms of what came back, for the "enough to answer?" read
            last_lookup = ""
            sufficient: Optional[asyncio.Task] = None
            effort = "minimal" if quick else (VOICE_EFFORT if voice else None)
            # A chart only when a picture helps (her read of the turn); otherwise the stage isn't offered at all.
            visual = not quick and (read is None or (read.get("visual_helps") or 0) >= VISUAL)
            # Her brain is sure a picture helps: the first lookup that makes one goes on the stage by itself.
            staged = visual and read is not None and (read.get("visual_helps") or 0) >= AUTO_STAGE
            tools = TOOLS if visual else [t for t in TOOLS if t["function"]["name"] != "show"]
            for step in range(max_steps + 1):
                is_last = step == max_steps
                out = await _stream_turn(client, model, _working(system, progress, voice), history, tools, is_last,
                                         progress.text, effort=effort)
                calls = [] if is_last else out["calls"]
                meta["model"] = out.get("model")
                # She reached for another lookup, but what she has already answers the question: answer instead.
                if calls and sufficient is not None:
                    e = await sufficient
                    if e is not None and e >= brain.ENOUGH:
                        progress.narration_log.append({"enough": e, "dropped_calls": [c["name"] for c in calls]})
                        out = await _stream_turn(client, model, _working(system, progress, voice), history, tools, True,
                                                 progress.text, effort=effort)
                        calls = []
                sufficient = None
                said = (out["text"] or "").strip()
                await progress.turn_ended(said, bool(calls))
                if not calls and not (out.get("text") or "").strip():
                    # Gemini sometimes ends a turn with nothing at all after a lookup: ask for the answer again, then
                    # from the backup model, rather than leave the owner with no answer.
                    out = await _answer_now(client, model, _working(system, progress, voice), history, tools,
                                            progress.text, effort)
                    meta["model"] = out.get("model") or meta.get("model")
                if not calls:
                    answer = await progress.final(out["text"] or "")
                    if answer:
                        history.append({"role": "assistant", "content": answer})
                    break
                # A line before a later lookup: said only if it's new to the owner (decided while the lookup runs).
                gate = asyncio.create_task(_gate(progress, text, said, last_lookup)) if said and step > 0 else None
                _record_calls(history, out["text"], calls)
                sigs = {c["id"]: c["signature"] for c in calls if c.get("signature")}
                if sigs and history and isinstance(history[-1], dict) and history[-1].get("tool_calls"):
                    history[-1]["_signatures"] = sigs
                for c in calls:
                    try:
                        args = json.loads(c["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    key = c["name"] + json.dumps(args, sort_keys=True, default=str)
                    if key in ran:  # exactly this, again: the answer would be the same
                        res = {"error": "You already ran exactly this lookup in this turn and it would return the "
                                        "same. Use what it returned, try a different route (another tool, dimension, "
                                        "hours or filter), or answer with what you have."}
                        _record_result(history, c["id"], json.dumps(res))
                        last_lookup = "failed: repeated an identical lookup"
                        continue
                    t0 = time.perf_counter()
                    try:
                        res = await call_tool(workspace_id, c["name"], args)
                    except Exception as exc:  # noqa: BLE001 — returned to the model to recover
                        logger.exception("Companion tool %s failed", c["name"])
                        res = {"error": str(exc)[:500]}
                    ok = "error" not in res
                    steps.append({"tool": c["name"], "args": args, "ok": ok,
                                  "ms": int((time.perf_counter() - t0) * 1000),
                                  **({} if ok else {"error": str(res.get("error"))[:300]})})
                    scene = res.pop("_scene", None) if isinstance(res, dict) else None
                    if scene is not None:  # on the stage at once, while she carries on
                        progress.hints["scenes"] = [*progress.hints.get("scenes", []), scene]
                    if c["name"] in LOOKUPS:  # an id she can put on the stage; the full result is kept for it
                        lid = f"L{len(turn_record['results']) + 1}"
                        turn_record["results"][lid] = {"id": lid, "tool": c["name"], "args": args, "result": res}
                        auto = _auto_scene(turn_record, lid) if staged else None
                        if auto is not None:
                            progress.hints["scenes"] = [*progress.hints.get("scenes", []), auto]
                        res = {**scenes.public(res), "lookup_id": lid,
                               **({"on_screen": scenes.describe(auto) + " — beside us now. Talk about what it shows, "
                                                 "not about the chart; show (same lookup) lights up what matters"}
                                  if auto else {})}
                    await progress.save()
                    body = json.dumps(res, default=str)
                    ran[key] = body
                    results.append(f"{c['name']} {json.dumps(args, default=str)} -> {body[:1500]}")
                    last_lookup = f"worked: {c['name']}" if ok else f"failed: {str(res.get('error'))[:200]}"
                    if c["name"] != "report_gap":
                        turn_record["lookups"].append({"tool": c["name"], "args": args, "ok": ok,
                                                       "error": None if ok else str(res.get("error"))[:300],
                                                       "rows": (res.get("rows") or [])[:20] if ok else None})
                    _record_result(history, c["id"], body[:RESULT_CHARS])
                if gate is not None:
                    await gate
                progress.next_step()
                if not is_last and results:
                    sufficient = asyncio.create_task(brain.enough(text, results[-6:]))
        async with _lock(conversation_id), async_session_factory() as db:
            m = await db.get(CompanionMessage, answer_id)
            if answer and progress.narration:
                answer = brain.drop_repeated_opener(progress.narration[0], answer)
            m.text = answer or "Sorry — I lost my thread there. Could you ask me that once more?"
            speculative = m.status == "speculative"
            m.status, m.steps = ("spec_done" if speculative else "done"), steps
            if progress.hints.get("scenes"):
                meta["scenes"] = progress.hints["scenes"]
            m.meta = {**meta, "narration": progress.narration} if (meta or progress.narration) else None
            if progress.narration_log:
                brain.log({"answer_id": str(answer_id), "owner_said": text, "narration": progress.narration_log})
            if progress.claims is not None and progress.claims.log:
                m.meta = {**(m.meta or {}), "claims": progress.claims.log}
                brain.log({"answer_id": str(answer_id), "owner_said": text, "claims": progress.claims.log})
            m.ms = int((time.perf_counter() - started) * 1000)
            kept = json.loads(json.dumps(_trim(history), default=str))
            if speculative:  # not part of the conversation until the owner's turn really ends with these words
                _SPEC_HISTORY[str(answer_id)] = kept
            else:
                conv = await db.get(CompanionConversation, conversation_id)
                conv.history = kept
                conv.last_at = datetime.now(timezone.utc)
            await db.commit()
        if answer and not speculative:
            asyncio.create_task(mark_offer(answer_id, answer))
    except Exception as exc:  # noqa: BLE001 — shown in the chat
        logger.exception("Companion chat turn failed")
        async with async_session_factory() as db:
            m = await db.get(CompanionMessage, answer_id)
            if m:
                m.text, m.steps = f"Something went wrong: {exc}", steps
                m.status = "spec_error" if m.status == "speculative" else "error"
                await db.commit()
    finally:
        RUNNING.discard(str(conversation_id))


_TASKS: Dict[str, asyncio.Task] = {}


def _lock(conversation_id: uuid.UUID) -> asyncio.Lock:
    return _LOCKS.setdefault(str(conversation_id), asyncio.Lock())


def _same_words(a: str, b: str) -> bool:
    norm = lambda t: re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()  # noqa: E731
    return norm(a) == norm(b)


async def speculate(conversation_id: uuid.UUID, text: str, voice: bool = False) -> Dict[str, Any]:
    """The owner has paused and has likely finished: start on their turn now, hidden, so that if it really is the
    end the answer is already under way (ElevenLabs-style speculative turn-taking). Confirmed by start_turn with
    the same words; discarded if they carry on."""
    key = str(conversation_id)
    cur = _SPEC.get(key)
    if cur and _same_words(cur["text"], text):
        return {"id": str(cur["a"])}
    if cur:
        await discard_speculation(conversation_id)
    if key in RUNNING:
        raise KairosException("I'm still answering the last message.", status_code=409)
    async with async_session_factory() as db:
        if await db.get(CompanionConversation, conversation_id) is None:
            raise KairosException("No such conversation.", status_code=404)
        at = datetime.now(timezone.utc)
        q = CompanionMessage(conversation_id=conversation_id, role="user", text=text, voice=voice, status="speculative",
                             created_at=at)
        a = CompanionMessage(conversation_id=conversation_id, role="assistant", text="", voice=voice,
                             status="speculative", steps=[], created_at=at + timedelta(microseconds=1))
        db.add_all([q, a])
        await db.commit()
        qid, aid = q.id, a.id
    _SPEC[key] = {"q": qid, "a": aid, "text": text, "voice": voice}
    RUNNING.add(key)
    _TASKS[key] = asyncio.create_task(run_turn(conversation_id, qid, aid, text, voice))
    return {"id": str(aid)}


async def discard_speculation(conversation_id: uuid.UUID) -> None:
    """The owner carried on talking (or said something else): the speculative turn is stopped and forgotten."""
    key = str(conversation_id)
    cur = _SPEC.pop(key, None)
    if not cur:
        return
    task = _TASKS.get(key)
    if task and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=3)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):  # noqa: BLE001 — it's being stopped
            pass
    RUNNING.discard(key)
    _SPEC_HISTORY.pop(str(cur["a"]), None)
    async with async_session_factory() as db:
        for mid in (cur["q"], cur["a"]):
            m = await db.get(CompanionMessage, mid)
            if m is not None and m.status in SPECULATIVE:
                await db.delete(m)
        await db.commit()


async def _confirm(conversation_id: uuid.UUID, cur: Dict[str, Any]) -> bool:
    """The owner's turn ended with the words she started on: the speculative turn becomes the real one."""
    key = str(conversation_id)
    async with _lock(conversation_id), async_session_factory() as db:
        q, a = await db.get(CompanionMessage, cur["q"]), await db.get(CompanionMessage, cur["a"])
        if q is None or a is None or a.status == "spec_error":
            return False
        q.status = "done"
        conv = await db.get(CompanionConversation, conversation_id)
        if a.status == "spec_done":  # already finished: it joins the conversation now
            a.status = "done"
            conv.history = _SPEC_HISTORY.pop(str(cur["a"]), conv.history)
            asyncio.create_task(mark_offer(a.id, a.text or ""))
        else:
            a.status = "pending"
        conv.last_at = datetime.now(timezone.utc)
        if not conv.title or conv.title == "Call with Jenny":
            conv.title = cur["text"][:120]
        await db.commit()
    _SPEC.pop(key, None)
    return True


async def _cut_off(conversation_id: uuid.UUID, heard: str) -> None:
    """The owner talked over Jenny: an answer still being worked out is stopped, and the last answer —
    finished or not — is marked with what they actually heard, so the next turn knows."""
    key = str(conversation_id)
    task = _TASKS.get(key)
    if key in RUNNING and task and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=3)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):  # noqa: BLE001 — it's being stopped
            pass
        RUNNING.discard(key)
    async with async_session_factory() as db:
        last = (await db.execute(select(CompanionMessage).where(
            CompanionMessage.conversation_id == conversation_id, CompanionMessage.role == "assistant")
            .order_by(CompanionMessage.created_at.desc()).limit(1))).scalars().first()
        if last is not None and last.status in ("pending", "done"):
            meta = dict(last.meta or {})
            working = last.status == "pending"
            if working:  # what it had said out loud so far is what the answer was
                last.text = " ".join([*(meta.get("narration") or []), meta.get("live") or ""]).strip()
            last.status = "interrupted"
            last.meta = {**meta, "heard": heard[:2000], "live": "", "cut_while": "working" if working else "answering"}
            await db.commit()


async def start_turn(conversation_id: uuid.UUID, text: str, voice: bool = False, interrupt: bool = False,
                     heard: str = "", speculation: Optional[str] = None,
                     pointing: Optional[Dict[str, Any]] = None,
                     answering: Optional[Dict[str, Any]] = None,
                     meeting: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The question and the answer-to-come are stored before this returns, so the caller (a voice call
    waiting to speak the answer) knows which message to watch. With `interrupt`, the owner cut in: whatever
    Jenny was saying or still working out is cut off first. With `speculation`, the turn already started during
    the owner's pause: if it was on these same words it simply becomes the real turn (already part-written)."""
    key = str(conversation_id)
    cur = _SPEC.get(key)
    if cur:
        if (not pointing and not answering and not meeting and speculation == str(cur["a"])
                and _same_words(cur["text"], text)
                and await _confirm(conversation_id, cur)):
            return await view(conversation_id)
        await discard_speculation(conversation_id)
    if interrupt:
        await _cut_off(conversation_id, heard)
    if key in RUNNING:
        raise KairosException("I'm still answering the last message.", status_code=409)
    async with async_session_factory() as db:
        conv = await db.get(CompanionConversation, conversation_id)
        if conv is None:
            raise KairosException("No such conversation.", status_code=404)
        # Stamped here, not by the database: both rows share one transaction, whose now() is the same
        # instant — and the answer must sort after its question.
        at = datetime.now(timezone.utc)
        q = CompanionMessage(conversation_id=conv.id, role="user", text=text, voice=voice, status="done", created_at=at,
                             meta={"speaker": meeting["speaker"]} if meeting and meeting.get("speaker") else None)
        a = CompanionMessage(conversation_id=conv.id, role="assistant", text="", voice=voice, status="pending", steps=[],
                             created_at=at + timedelta(microseconds=1))
        db.add_all([q, a])
        conv.last_at = datetime.now(timezone.utc)
        if not conv.title or conv.title == "Call with Jenny":
            conv.title = text[:120]
        await db.commit()
        qid, aid = q.id, a.id
    RUNNING.add(key)
    _TASKS[key] = asyncio.create_task(run_turn(conversation_id, qid, aid, text, voice, pointing, answering, meeting))
    return await view(conversation_id)
