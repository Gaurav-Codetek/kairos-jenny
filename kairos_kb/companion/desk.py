"""Jenny's desk: what she has committed to, kept alive by the server.

When Jenny says she'll keep an eye on something, it isn't a figure of speech: it goes on her desk as a spec the
heartbeat runs, and only then may she say it (see claims.py — a promise nothing on the desk backs never reaches the
owner). Two kinds of item:

  watch   a metric (or one slice of it: cancellations in Bangalore) against a threshold — today's value, or its gap
          from normal — read on every pulse until it ends, the whole time. It crosses the line only when it is clearly
          past it on two checks in a row (one noisy reading isn't news); she looks into it and tells the owner. Clearly
          past: a few percent beyond the line, and for a rate, beyond its sampling noise at today's volume (6.4% on 125
          orders isn't below 6.5%); a rate on too few orders to mean anything (just after midnight) doesn't move the
          watch at all. Hovering at the line is neither a crossing nor a coming back. It keeps
          watching: when it holds back on the right side she says so (if she'd told them it crossed), a second crossing
          within the hour is noted rather than interrupting again, and at the close of each business day (and when
          the watch ends) she leaves a summary — how often it crossed and when, how long it stayed over, its peak, and
          where it closed.
  check   a question to look into at a set time ("which zones are driving cancellations — at eleven"): at that time
          she investigates and raises the answer.

Items are validated when they're made: the product is live, the metric and slice exist, the threshold is in the
metric's own units and not already crossed, and the time is in the future. What can't be watched can't be promised.
Stored as AgentNote(kind="desk"): title is the item in words, facts holds the spec and its running state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from kairos_kb.db.engine import async_session_factory
from kairos_kb.models.companion import CompanionState
from kairos_kb.models.living import AgentNote

logger = logging.getLogger(__name__)

KIND = "desk"
HOLD_CHECKS = 2            # a watch crosses (or comes back) when that holds on this many checks in a row
REALERT_MIN = 60           # a new crossing within this long of the last alert is noted, not raised again
DAY_READINGS = 600         # readings kept for the day (one per pulse)
MAX_HOURS = 7 * 24         # a watch lasts at most a week
UNIT_RATIO = 30            # a threshold this many times off the current value is in the wrong units
MARGIN = 0.03              # a reading counts as past the line (or back) only this far beyond it, relative to the line
MIN_VOLUME = 100           # a rate on fewer events than this (orders behind a cancellation rate) doesn't move a watch

# What she always does, without anything on the desk: claims about these are true.
STANDING = [
    "I look at the live numbers every few minutes, all day, by myself",
    "I raise material changes myself — on a call at a pause, or as a voice note when the owner is away",
    "I say when a data stream stops or comes back",
    "I remember what the owner tells me they care about",
]


def _fn(name: str, description: str, properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}}


TOOLS = [
    _fn("keep_watch", "Put a watch on my desk: a metric (optionally one slice of it) against a threshold, checked on "
                      "every pulse until it ends; when it trips I look into it and tell the owner. Use it BEFORE saying "
                      "you'll watch, alert or ping about something. threshold is in the metric's own units (call "
                      "compare_to_normal first if unsure: a rate may be 0.07, not 7). It returns the current value.",
        {"product": {"type": "string"}, "metric": {"type": "string"},
         "condition": {"type": "string", "enum": ["above", "below"]},
         "threshold": {"type": "number"},
         "basis": {"type": "string", "enum": ["value", "vs_normal_pct"],
                   "description": "value: today's value so far. vs_normal_pct: its gap from a normal day at this time, "
                                  "in percent (e.g. -15 = fifteen percent below normal). Default value."},
         "dimension": {"type": "string", "description": "Optional, with slice: the dimension, e.g. city."},
         "slice": {"type": "string", "description": "Optional: one value of the dimension, e.g. Bangalore."},
         "hours": {"type": "number", "description": "How long to keep watching. Default: until the end of today."},
         "note": {"type": "string", "description": "The watch in the owner's words, e.g. 'cancellations above 8%'."}},
        ["product", "metric", "condition", "threshold", "note"]),
    _fn("check_later", "Put a check on my desk: a question I'll look into myself at a set time and then tell the owner "
                       "what I found. Use it BEFORE saying you'll check something later.",
        {"question": {"type": "string", "description": "What to find out, e.g. 'which zones drive the cancellations'."},
         "in_minutes": {"type": "integer", "description": "Minutes from now (5 to 1440)."},
         "at": {"type": "string", "description": "Or a time today in the business's clock, 'HH:MM'."}},
        ["question"]),
    _fn("desk", "What's on my desk: the watches and checks I've committed to, with their ids and latest readings.", {},
        []),
    _fn("drop_watch", "Take an item off my desk (the owner no longer wants it).",
        {"id": {"type": "string", "description": "The item's id (or its first characters) from desk."}}, ["id"]),
]
NAMES = {t["function"]["name"] for t in TOOLS}


# ── reading the desk ─────────────────────────────────────────────────


async def open_items(db, workspace_id) -> List[AgentNote]:
    return list((await db.execute(select(AgentNote).where(
        AgentNote.workspace_id == workspace_id, AgentNote.kind == KIND, AgentNote.status == "open")
        .order_by(AgentNote.created_at))).scalars().all())


def line(n: AgentNote) -> str:
    """The item in words, as she'd say it to herself."""
    f = n.facts or {}
    until = f.get("until_local")
    if f.get("type") == "check":
        return f"check at {f.get('at_local')}: {n.title}"
    last = (f.get("last") or {}).get("display")
    crossings = len(f.get("episodes") or [])
    state = []
    if last:
        state.append(f"now {last}")
    if crossings:
        state.append(f"crossed {crossings} time{'s' if crossings != 1 else ''} today")
    if f.get("state") == "crossed":
        state.append("over the line right now")
    return f"watching {n.title}" + (f" until {until}" if until else "") + (f" ({'; '.join(state)})" if state else "")


async def lines(workspace_id) -> List[str]:
    async with async_session_factory() as db:
        return [line(n) for n in await open_items(db, workspace_id)]


def view(n: AgentNote) -> Dict[str, Any]:
    f = n.facts or {}
    return {"id": str(n.id), "type": f.get("type"), "title": n.title, "status": n.status, "line": line(n),
            "spec": f.get("spec"), "last": f.get("last"), "until": f.get("until_local"), "at": f.get("at_local"),
            "origin": f.get("origin"), "outcome": f.get("outcome"), "created_at": n.created_at.isoformat(),
            "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            "state": f.get("state"), "day": f.get("day"), "episodes": f.get("episodes") or [],
            "readings": [[r["t"], r["v"]] for r in (f.get("history") or []) if isinstance(r, dict) and "t" in r],
            "summaries": (f.get("summaries") or [])[-3:]}


async def listing(workspace_id) -> List[Dict[str, Any]]:
    """Open items, and what closed in the last day."""
    since = datetime.now(timezone.utc) - timedelta(days=1)
    async with async_session_factory() as db:
        rows = (await db.execute(select(AgentNote).where(
            AgentNote.workspace_id == workspace_id, AgentNote.kind == KIND)
            .order_by(AgentNote.created_at.desc()).limit(60))).scalars().all()
    return [view(n) for n in rows if n.status == "open" or (n.updated_at or n.created_at) >= since]


# ── the business clock ───────────────────────────────────────────────


def _local_now(st: CompanionState) -> datetime:
    return datetime.utcnow() + timedelta(minutes=st.tz_offset_minutes or 0)


def _to_utc(local: datetime, st: CompanionState) -> datetime:
    return (local - timedelta(minutes=st.tz_offset_minutes or 0)).replace(tzinfo=timezone.utc)


async def _state(db, workspace_id) -> Optional[CompanionState]:
    return (await db.execute(select(CompanionState).where(CompanionState.workspace_id == workspace_id))).scalars().first()


# ── evaluating a watch ───────────────────────────────────────────────


_COUNT = re.compile(r"^\s*COUNT\s*\(", re.I)


def volume_metric(model: Dict[str, Any], m: Dict[str, Any]) -> Optional[str]:
    """The count a rate is taken over (orders, behind a cancellation rate): an additive COUNT(...) metric on the same
    table whose expression is the rate's denominator. None for anything that isn't a ratio, or has no such count."""
    if m.get("additive") or (m.get("unit") or "") != "ratio":
        return None
    expr = (m.get("expression") or "").replace(" ", "").upper()
    for x in model.get("metrics") or []:
        own = (x.get("expression") or "").replace(" ", "").upper()
        if (x is not m and x.get("additive") and x.get("base_table") == m.get("base_table")
                and _COUNT.match(x.get("expression") or "") and own and own in expr):
            return x["name"]
    return None


async def evaluate(db, workspace_id, spec: Dict[str, Any], st: CompanionState) -> Dict[str, Any]:
    """The watched value now: {"value", "display"} — and, for a rate, "n": the events it's taken over today — or
    {"error"}."""
    from kairos_kb.companion import chat
    from kairos_kb.companion.pulse import _between, pace_for, show
    from kairos_kb.companion.vitals import event_column, live_model, num, run

    p = await chat._product(db, workspace_id, spec["product"])
    if p is None:
        return {"error": f"No data product '{spec['product']}'."}
    ev = await event_column(db, p)
    model = live_model(p, {"table": ev[0], "column": ev[1]}) if ev else None
    m = next((x for x in (model or {}).get("metrics") or [] if x["name"].lower() == spec["metric"].lower()), None)
    vol = volume_metric(model, m) if model and m and spec.get("basis", "value") == "value" else None
    local = _local_now(st)
    today = _between(datetime.combine(local.date(), time.min), local)
    if spec.get("slice"):
        if not ev:
            return {"error": f"{p.name} isn't live."}
        if m is None:
            return {"error": f"No metric '{spec['metric']}' on {p.name}."}
        r = await run(db, model, [m["name"]] + ([vol] if vol else []), [spec["dimension"]], filters=today, limit=3000)
        if r.get("error"):
            return {"error": r["error"]}
        rows = {str(row[0]).lower(): row for row in r.get("rows") or []}
        row = rows.get(str(spec["slice"]).lower())
        if row is None:
            some = ", ".join(str(x[0]) for x in (r.get("rows") or [])[:8])
            return {"error": f"No '{spec['slice']}' in {spec['dimension']} today. Some values: {some}."}
        value = num(row[1])
        out = {"value": value, "display": show(value, m.get("unit") or "", m["name"]), "slice": str(row[0])}
        if vol and len(row) > 2 and num(row[2]) is not None:
            out["n"] = num(row[2])
        return out
    res = await pace_for(db, p, spec["metric"], st)
    if res.get("error"):
        return {"error": res["error"]}
    if spec.get("basis") == "vs_normal_pct":
        dev = res.get("dev_pct")
        if dev is None:
            return {"error": "No normal to compare with at this hour yet."}
        return {"value": float(dev), "display": f"{dev:+.1f}% against normal ({res.get('actual_display')})"}
    out = {"value": res.get("actual"), "display": res.get("actual_display") or str(res.get("actual"))}
    if vol:
        r = await run(db, model, [vol], None, filters=today)
        rows = r.get("rows") or []
        if not r.get("error") and rows and num(rows[0][0]) is not None:
            out["n"] = num(rows[0][0])
    return out


def crossed(spec: Dict[str, Any], value: Optional[float], margin: float = 0.0) -> bool:
    """Over the line — by at least `margin` when one is given."""
    if value is None:
        return False
    t = spec["threshold"]
    return value > t + margin if spec["condition"] == "above" else value < t - margin


def back(spec: Dict[str, Any], value: Optional[float], margin: float = 0.0) -> bool:
    """On the right side of the line, by at least `margin`."""
    if value is None:
        return False
    t = spec["threshold"]
    return value < t - margin if spec["condition"] == "above" else value > t + margin


def margin(spec: Dict[str, Any], value: float, n: Optional[float] = None) -> float:
    """How far past the line a reading must be to count: a few percent of the line, and for a rate taken over n
    events, its sampling noise (one standard error) — 6.4% on 125 orders is 6.5% give or take two points."""
    out = abs(spec["threshold"]) * MARGIN
    if n and 0.0 <= value <= 1.0:
        out = max(out, math.sqrt(value * (1.0 - value) / n))
    return out


# ── the tools ────────────────────────────────────────────────────────


async def call(workspace_id, name: str, args: Dict[str, Any], origin: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    async with async_session_factory() as db:
        if name == "desk":
            return {"desk": [{"id": str(n.id)[:8], "item": line(n)} for n in await open_items(db, workspace_id)],
                    "standing_duties": STANDING}
        if name == "drop_watch":
            key = str(args.get("id") or "").strip().lower()
            for n in await open_items(db, workspace_id):
                if key and str(n.id).startswith(key):
                    n.status = "cancelled"
                    n.facts = {**(n.facts or {}), "outcome": "taken off the desk"}
                    await db.commit()
                    return {"ok": True, "dropped": line(n)}
            return {"error": f"Nothing open on the desk with id '{key}'. Call desk."}
        st = await _state(db, workspace_id)
        if st is None or st.tz_offset_minutes is None:
            return {"error": "I don't know this business's clock yet (no live data seen), so I can't keep time for it."}
        if name == "keep_watch":
            return await _keep_watch(db, workspace_id, st, args, origin)
        if name == "check_later":
            return await _check_later(db, workspace_id, st, args, origin)
    return {"error": f"Unknown desk tool {name}"}


async def _keep_watch(db, workspace_id, st, args, origin) -> Dict[str, Any]:
    from kairos_kb.companion import chat
    from kairos_kb.companion.vitals import event_column, live_model

    p = await chat._product(db, workspace_id, str(args.get("product") or ""))
    if p is None:
        return {"error": f"No data product '{args.get('product')}'. Call list_products."}
    ev = await event_column(db, p)
    if not ev:
        return {"error": f"{p.name} doesn't record when events happen, so it can't be watched live."}
    model = live_model(p, {"table": ev[0], "column": ev[1]})
    metric = next((x["name"] for x in model.get("metrics") or []
                   if x["name"].lower() == str(args.get("metric") or "").lower()), None)
    if metric is None:
        return {"error": f"No metric '{args.get('metric')}' on {p.name}.",
                "metrics": [x["name"] for x in model.get("metrics") or []]}
    condition = args.get("condition")
    if condition not in ("above", "below"):
        return {"error": "condition must be 'above' or 'below'."}
    try:
        threshold = float(args.get("threshold"))
    except (TypeError, ValueError):
        return {"error": "threshold must be a number."}
    basis = args.get("basis") or "value"
    dimension, slice_ = (args.get("dimension") or None), (args.get("slice") or None)
    if slice_:
        dims = {d["name"].lower(): d["name"] for d in model.get("dimensions") or []}
        if not dimension or str(dimension).lower() not in dims:
            return {"error": f"A slice needs its dimension; {p.name} has: {', '.join(dims.values())}."}
        dimension = dims[str(dimension).lower()]
        if basis != "value":
            return {"error": "A slice can be watched on its value, not its gap from normal."}
    spec = {"product": p.name, "metric": metric, "condition": condition, "threshold": threshold, "basis": basis,
            "dimension": dimension, "slice": slice_}
    now = await evaluate(db, workspace_id, spec, st)
    if now.get("error"):
        return {"error": f"I can't read that, so I can't watch it: {now['error']}"}
    value = now.get("value")
    if slice_ and now.get("slice"):
        spec["slice"] = now["slice"]
    if basis == "value" and value and threshold and (abs(threshold / value) > UNIT_RATIO or abs(value / threshold) > UNIT_RATIO):
        return {"error": (f"The threshold {threshold:g} looks like the wrong units: {metric} is {value:g} now (shown as "
                          f"{now['display']}). Give the threshold in the same units as {value:g}."), "now": now["display"]}
    if crossed(spec, value):
        return {"error": (f"It's already {condition} that now ({now['display']}): tell the owner that rather than "
                          "watching for it, or pick a threshold it hasn't crossed."), "now": now["display"]}
    local = _local_now(st)
    hours = args.get("hours")
    until_local = (local + timedelta(hours=min(float(hours), MAX_HOURS)) if hours
                   else datetime.combine(local.date(), time(23, 59)))
    note = str(args.get("note") or "").strip()[:300] or f"{metric} {condition} {threshold:g}"
    title = note + (f" in {spec['slice']}" if slice_ and spec["slice"].lower() not in note.lower() else "")
    facts = {"type": "watch", "spec": spec, "until": _to_utc(until_local, st).isoformat(),
             "until_local": until_local.strftime("%a %H:%M"), "origin": origin or {},
             "last": {"at": datetime.now(timezone.utc).isoformat(), "value": value, "display": now["display"]},
             **new_day(local.date().isoformat()),
             "history": [{"t": local.strftime("%H:%M"), "v": value, "d": now["display"]}]}
    for n in await open_items(db, workspace_id):  # the same watch again: updated, not doubled
        s = (n.facts or {}).get("spec") or {}
        if (n.facts or {}).get("type") == "watch" and all(
                str(s.get(k) or "").lower() == str(spec.get(k) or "").lower()
                for k in ("product", "metric", "condition", "basis", "dimension", "slice")):
            n.title, n.facts = title, facts
            await db.commit()
            return {"ok": True, "updated": True, "id": str(n.id)[:8], "watch": line(n), "now": now["display"]}
    n = AgentNote(workspace_id=workspace_id, kind=KIND, mode="live", status="open", importance=6, confidence=1.0,
                  signal="watch", title=title[:500], body=json.dumps(spec), facts=facts)
    db.add(n)
    await db.commit()
    return {"ok": True, "id": str(n.id)[:8], "watch": line(n), "now": now["display"],
            "next": ("Done: I check it on every pulse and tell the owner when it trips. Tell them in your own words "
                     "that you'll keep an eye on it — not 'watch set', 'desk' or an id.")}


async def _check_later(db, workspace_id, st, args, origin) -> Dict[str, Any]:
    question = str(args.get("question") or "").strip()
    if not question:
        return {"error": "What should I find out?"}
    local = _local_now(st)
    if args.get("at"):
        try:
            hh, mm = (int(x) for x in str(args["at"]).split(":")[:2])
            at = datetime.combine(local.date(), time(hh, mm))
        except (ValueError, TypeError):
            return {"error": "at must be 'HH:MM' in the business's clock."}
        if at <= local:
            at += timedelta(days=1)
    else:
        mins = int(args.get("in_minutes") or 0)
        if not 5 <= mins <= 1440:
            return {"error": "Give in_minutes between 5 and 1440, or at as 'HH:MM'."}
        at = local + timedelta(minutes=mins)
    if at - local > timedelta(hours=24):
        return {"error": "I can schedule a check up to a day ahead."}
    facts = {"type": "check", "question": question, "at": _to_utc(at, st).isoformat(),
             "at_local": at.strftime("%a %H:%M"), "origin": origin or {}}
    n = AgentNote(workspace_id=workspace_id, kind=KIND, mode="live", status="open", importance=6, confidence=1.0,
                  signal="check", title=question[:500], body=question, facts=facts)
    db.add(n)
    await db.commit()
    return {"ok": True, "id": str(n.id)[:8], "check": line(n),
            "next": ("Done: at that time I look into it myself and tell the owner here what I found. Tell them in "
                     "your own words when you'll come back to it — not 'check set', 'desk' or an id.")}


# ── the heartbeat: keeping the desk alive ──────────────────────────────


def new_day(day: str, carry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A watch's state for a fresh business day. Over the line at midnight carries on as a crossing from 00:00 (already
    told)."""
    out: Dict[str, Any] = {"day": day, "history": [], "episodes": [], "state": "clear", "held": 0, "clear_n": 0}
    if carry and carry.get("state") == "crossed":
        last = (carry.get("history") or [{}])[-1]
        out.update(state="crossed", held=HOLD_CHECKS, episodes=[{"from": "00:00", "to": None, "peak": last.get("v"),
                                                               "peak_d": last.get("d"), "peak_at": "00:00",
                                                               "told": True}])
    return out


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def step(f: Dict[str, Any], value: float, display: str, clock: str, now: datetime,
         n: Optional[float] = None) -> List[str]:
    """One reading of a watch (business-clock "HH:MM"; n: the events a rate is taken over, when known): updates its
    day in place and returns what happened — "cross" (newly over the line, worth telling), "cross_quiet" (over again
    within the hour), "back" (back on the right side after a crossing she told the owner about)."""
    spec = f["spec"]
    reading = {"t": clock, "v": value, "d": display, **({"n": n} if n is not None else {})}
    f.setdefault("history", []).append(reading)
    f["history"] = f["history"][-DAY_READINGS:]
    if n is not None and n < MIN_VOLUME:
        reading["thin"] = True  # kept for the record; too few events to say which side of the line it's on
        return []
    gap = margin(spec, value, n)
    over, clear = crossed(spec, value, gap), back(spec, value, gap)
    # Clearly over, clearly back, or at the line (neither: nothing builds up toward a crossing or a return).
    f["held"] = (f.get("held") or 0) + 1 if over else 0
    f["clear_n"] = (f.get("clear_n") or 0) + 1 if clear else 0
    episodes = f.setdefault("episodes", [])
    events: List[str] = []
    if f.get("state", "clear") == "clear" and f["held"] >= HOLD_CHECKS:
        f["state"] = "crossed"
        started = f["history"][-HOLD_CHECKS]["t"] if len(f["history"]) >= HOLD_CHECKS else clock
        episodes.append({"from": started, "to": None, "peak": value, "peak_d": display, "peak_at": clock, "told": False})
        last = f.get("last_alert")
        if not last or now - datetime.fromisoformat(last) >= timedelta(minutes=REALERT_MIN):
            episodes[-1]["told"] = True
            f["last_alert"] = now.isoformat()
            events.append("cross")
        else:
            events.append("cross_quiet")
    elif f.get("state") == "crossed" and episodes:
        ep = episodes[-1]
        if ep.get("peak") is None or (value > ep["peak"] if spec["condition"] == "above" else value < ep["peak"]):
            ep.update(peak=value, peak_d=display, peak_at=clock)
        if f["clear_n"] >= HOLD_CHECKS:
            f["state"] = "clear"
            ep["to"] = f["history"][-HOLD_CHECKS]["t"] if len(f["history"]) >= HOLD_CHECKS else clock
            if ep.get("told"):
                events.append("back")
    return events


def summarize(f: Dict[str, Any], title: str, day_label: str, closing: bool = True) -> str:
    """How a watch's day went, in plain words (the facts she'll put in her own voice)."""
    spec, hist, eps = f["spec"], f.get("history") or [], f.get("episodes") or []
    if not hist:
        return f"{title} — {day_label}: no readings came in."
    above = spec["condition"] == "above"
    side = "above" if above else "below"
    last = hist[-1]
    end_t = "the close" if closing else last["t"]
    if eps:
        spans = ", ".join(f"{e['from']}–{e['to'] or end_t}" for e in eps)
        total = sum(max(0, _mins(e["to"] or last["t"]) - _mins(e["from"])) for e in eps)
        dur = f"{total // 60} h {total % 60} min" if total >= 60 else f"{total} min"
        peak = max(eps, key=lambda e: e.get("peak") or 0) if above else min(eps, key=lambda e: e.get("peak") or 0)
        body = (f"crossed {len(eps)} time{'s' if len(eps) != 1 else ''} ({spans}), {side} the line for about {dur} "
                f"in all; peak {peak.get('peak_d')} at {peak.get('peak_at')}")
    else:
        solid = [r for r in hist if not r.get("thin")] or hist  # a rate on a handful of orders was never close
        near = max(solid, key=lambda r: r["v"]) if above else min(solid, key=lambda r: r["v"])
        body = f"never crossed; closest was {near['d']} at {near['t']}"
    return f"{title} — {day_label}: {body}; {'closed' if closing else 'now'} at {last['d']}."


_REVIEW_LOCKS: Dict[str, asyncio.Lock] = {}


async def review(workspace_id) -> int:
    """One review at a time per business (a crossing or a day close is told once)."""
    lock = _REVIEW_LOCKS.setdefault(str(workspace_id), asyncio.Lock())
    async with lock:
        return await _review(workspace_id)


async def _review(workspace_id) -> int:
    """After each pulse: read every open watch (it keeps watching after a crossing), run every check that's due,
    close each watch's business day with a summary, and end what has run its time. Returns how many things she has to
    tell (each becomes a moment she raises)."""
    now = datetime.now(timezone.utc)
    told = 0
    async with async_session_factory() as db:
        st = await _state(db, workspace_id)
        items = await open_items(db, workspace_id)
        if st is None or not items:
            return 0
        local = _local_now(st)
        today, clock = local.date().isoformat(), local.strftime("%H:%M")
        due: List[tuple] = []
        for n in items:
            f = dict(n.facts or {})
            if f.get("type") == "check":
                if datetime.fromisoformat(f["at"]) <= now:
                    n.status = "running"
                    due.append((n.id, "check", n.title, f, None))
                continue
            if "day" not in f:  # a watch from before watches kept their day
                f.update(new_day(today))
            if f["day"] != today:  # the business day closed: its summary, then a fresh day
                label = datetime.fromisoformat(f["day"]).strftime("%a %d %b")
                text = summarize(f, n.title, label)
                f["summaries"] = (f.get("summaries") or [])[-13:] + [{"day": f["day"], "text": text}]
                f["outcome"] = text
                due.append((n.id, "summary", n.title, dict(f), text))
                f.update(new_day(today, f))
            if datetime.fromisoformat(f["until"]) <= now:  # its time is up: the day so far, and done
                text = summarize(f, n.title, local.strftime("%a %d %b") + " (watch ended)", closing=False)
                f["summaries"] = (f.get("summaries") or [])[-13:] + [{"day": f["day"], "text": text}]
                n.status, f["outcome"] = "expired", text
                if f.get("history"):
                    due.append((n.id, "summary", n.title, dict(f), text))
                n.facts = f
                continue
            r = await evaluate(db, workspace_id, f["spec"], st)
            if r.get("error"):
                f["last"] = {"at": now.isoformat(), "error": r["error"]}
                n.facts = f
                continue
            f["last"] = {"at": now.isoformat(), "value": r["value"], "display": r["display"],
                         **({"n": r["n"]} if r.get("n") is not None else {})}
            for ev in step(f, r["value"], r["display"], clock, now, r.get("n")):
                if ev in ("cross", "back"):
                    due.append((n.id, ev, n.title, dict(f), None))
            n.facts = f
        await db.commit()
    for nid, kind, title, f, text in due:
        try:
            await _fire(workspace_id, nid, kind, title, f, text)
            told += 1
        except Exception:  # noqa: BLE001 — a check is tried again on the next pulse
            logger.exception("Desk item %s failed", nid)
            if kind == "check":
                async with async_session_factory() as db:
                    n = await db.get(AgentNote, nid)
                    if n is not None:
                        n.status = "open"
                        await db.commit()
    return told


async def _fire(workspace_id, note_id, kind: str, title: str, f: Dict[str, Any], text: Optional[str] = None) -> None:
    """Something to tell: a watch crossed (looked into first), came back, or closed its day; or a check is due (looked
    into). Each leaves a moment for her to raise (initiative): on a call, or as a voice note."""
    last = (f.get("last") or {}).get("display")
    ep = (f.get("episodes") or [{}])[-1]
    if kind == "cross":
        findings = await investigate(workspace_id, (
            f"A watch on your desk crossed its line: {title} — it's now {last} (line: {f['spec']['condition']} "
            f"{f['spec']['threshold']:g}), held over {HOLD_CHECKS} checks since {ep.get('from')}. Look into it: where "
            "it sits, since when, and whether it's spreading or one outlier."))
        moment = ("watch_tripped", 8, f"Watch crossed: {title} (now {last})", findings)
    elif kind == "back":
        body = (f"Back on the other side of the line: {title} no longer holds — it's now {last}. It held from "
                f"{ep.get('from')} to {ep.get('to')}, at its furthest {ep.get('peak_d')} at {ep.get('peak_at')}. "
                "I'm still watching it.")
        moment = ("watch_recovered", 6, f"Watch cleared: {title} no longer holds (now {last})", body)
    elif kind == "summary":
        moment = ("watch_summary", 6, f"Day summary: {title}", text or "")
    else:
        findings = await investigate(workspace_id, f"A check on your desk is due. Find out: {f['question']}")
        moment = ("check_done", 7, f"Checked as promised: {title}", findings)
    signal, importance, headline, body = moment
    async with async_session_factory() as db:
        n = await db.get(AgentNote, note_id)
        if n is None:
            return
        if kind == "check":
            n.status = "done"
            n.facts = {**(n.facts or {}), "outcome": body[:2000], "fired_at": datetime.now(timezone.utc).isoformat()}
        elif kind == "cross":
            n.facts = {**(n.facts or {}), "outcome": body[:2000]}
        db.add(AgentNote(workspace_id=workspace_id, kind="moment", mode="live", status="open", signal=signal,
                         importance=importance, confidence=0.9, title=headline[:500], body=body[:4000],
                         facts={"investigation": body[:4000], "desk_item": str(note_id)}))
        await db.commit()


# ── looking into something, alone ───────────────────────────────────────

INVESTIGATE = """

# Looking into something by myself
Nobody is waiting on this: I'm working it out on my own before I tell my owner. I use my tools to find where it
sits (break it down by the dimensions that matter), since when, and whether it's spreading or one outlier — two to
four lookups, no more. Then I write my findings as plain notes for myself: two to four sentences with the numbers
that matter, what I'm sure of, and what I couldn't tell — one short paragraph, no heading or bullets. No greeting,
no offer, no questions."""


async def investigate(workspace_id, brief: str, steps: int = 4) -> str:
    """Her own tool loop on a question, no owner in it; returns her findings (notes, not words for the owner)."""
    from kairos_kb.companion import chat
    from kairos_kb.evals.connector_eval import _client, _record_calls, _record_result, default_model

    async with async_session_factory() as db:
        ctx = await chat._context(db, workspace_id)
    system = chat.SYSTEM.format(**ctx) + INVESTIGATE
    tools = [t for t in chat.LOOK_TOOLS]
    history: List[Dict[str, Any]] = [{"role": "user", "content": brief}]

    async def quiet(_t: str) -> None:
        return None

    client, model = _client(), default_model()
    text, looked = "", 0
    for _ in range(steps):
        out = await chat._stream_turn(client, model, system, history, tools, False, quiet, "low")
        calls = out["calls"]
        text = (out.get("text") or "").strip()
        if not calls:
            break
        _record_calls(history, out["text"], calls)
        sigs = {c["id"]: c["signature"] for c in calls if c.get("signature")}
        if sigs and isinstance(history[-1], dict) and history[-1].get("tool_calls"):
            history[-1]["_signatures"] = sigs
        for c in calls:
            try:
                args = json.loads(c["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                res = await chat.call_tool(workspace_id, c["name"], args)
            except Exception as exc:  # noqa: BLE001 — back to the model to recover
                res = {"error": str(exc)[:300]}
            _record_result(history, c["id"], json.dumps(chat.scenes.public(res), default=str)[:chat.RESULT_CHARS])
            looked += 1
    if looked:  # what she found, written up (a line like "pulling it by city…" is a plan, not findings)
        history.append({"role": "user", "content": "Now write your findings: one short paragraph of two to four "
                                                   "sentences with the numbers that matter, what you're sure of and "
                                                   "what you couldn't tell. No heading, no bullets."})
        out = await chat._stream_turn(client, model, system, history, tools, True, quiet, "low")
        text = (out.get("text") or "").strip() or text
    return text or "I couldn't get far enough to say more than the reading itself."
