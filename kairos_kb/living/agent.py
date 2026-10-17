"""The living agent: watches the business through its data products, notices, waits, remembers, tells.

One look (a run) at a connection:

  1. watch list   derived from the data products on first use (see watch.py)
  2. observe      each watched metric's monthly series, stored as it stood at this look
  3. mature       recent periods are held back while they may still change — the measured
                  maturity when the agent has looked enough times, its industry prior before
                  that — and a partial current month is never compared with full ones
  4. detect       statistics on the settled series (detect.py); recent provisional periods
                  are checked with a higher bar and reported as provisional
  5. triage       a change on a product whose contracts are broken, or whose pipelines
                  just failed, is reported as a data issue, not a business change
  6. explain      the change broken down by the watch's slices: where it moved
  7. remember     the same signal on the same period updates its note instead of repeating;
                  a provisional note is confirmed when the period settles and the signal
                  holds, or withdrawn with a correction when it does not
  8. tell         a briefing and notes in an assistant's voice, written by the LLM from the
                  computed facts only; every number it writes is checked against the facts

Replay walks the history month by month as if each month-end were today, so its behaviour
can be seen (and measured) before anyone relies on it. History that was already restated
cannot be replayed: a replay shows waiting, not revision.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.db.engine import async_session_factory
from kairos_kb.living import detect as D
from kairos_kb.living.maturity import maturity
from kairos_kb.living.watch import add_months, derive, is_partial, latest_day, month_end, read_series
from kairos_kb.models.data_product import DataProduct
from kairos_kb.models.living import AgentNote, AgentRun, MetricObservation, Watch
from kairos_kb.models.workspace import Workspace

logger = logging.getLogger(__name__)

PROVISIONAL_SENSITIVITY = 1.5   # stronger evidence asked of a period that may still change
STALE_MONTHS = 4                # data that stops this long before today is not "now"
TOP_SLICES = 200


def _fmt(v: Optional[float]) -> str:
    if v is None:
        return "-"
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:.2f}B"
    if a >= 1e6:
        return f"{v / 1e6:.2f}M"
    if a >= 1e4:
        return f"{v / 1e3:.1f}k"
    if a >= 100:
        return f"{v:,.0f}"
    return f"{v:.3g}" if a < 1 else f"{v:.2f}"


def _month(d: date) -> str:
    return d.strftime("%b %Y")


def valence(direction: str, good: str) -> str:
    if good == "neutral":
        return "neutral"
    return "good" if (direction == "up") == (good == "up") else "bad"


def importance(sig: D.Signal, val: str) -> int:
    base = min(5.0, abs(sig.impact_pct or 10) / 5) + min(3.0, sig.score / 4)
    return int(max(1, min(10, round(base + (2 if val == "bad" else 0)))))


# ── triage: data or business? ─────────────────────────────────────────


async def data_health(db: AsyncSession, p: DataProduct) -> Dict[str, Any]:
    """What could make this product's recent numbers wrong rather than real."""
    from kairos_kb.products.service import contracts_of

    c = await contracts_of(db, p)
    problems = [f"{x['contract']} {x['status']} on {x['port'].split('.')[-1]}: {x.get('detail') or ''}"
                for x in c["contracts"] if x["status"] in ("broken",) or
                (x["contract"] == "pipeline" and x["status"] == "breached")]
    return {"health": c["health"]["status"], "problems": problems[:5]}


# ── explain: where did it move ─────────────────────────────────────────


async def where_it_moved(db: AsyncSession, p: DataProduct, w: Watch, period: date,
                         baseline_periods: List[date]) -> List[Dict[str, Any]]:
    """Per slice dimension: the slices that moved most between the baseline and the period."""
    out = []
    if not baseline_periods:
        return out
    for dim in (w.slices or [])[:2]:
        try:
            series, _ = await read_series(db, p, w, slice_dim=dim, periods=(min(baseline_periods), period))
        except ValueError:
            continue
        rows = []
        for key, pts in series.items():
            d = dict(pts)
            now_v = d.get(period)
            base = [d[b] for b in baseline_periods if b in d]
            if now_v is None and not base:
                continue
            base_v = sum(base) / len(base) if base else 0.0
            rows.append({"slice": key, "value": now_v or 0.0, "baseline": round(base_v, 4),
                         "delta": round((now_v or 0.0) - base_v, 4), "change_pct": D.pct(now_v or 0.0, base_v)})
        if not rows:
            continue
        total_delta = sum(r["delta"] for r in rows)
        rows.sort(key=lambda r: -abs(r["delta"]))
        top = rows[:4]
        if w_additive(p, w) and total_delta:
            for r in top:
                r["share_of_change_pct"] = round(r["delta"] / total_delta * 100, 1)
        out.append({"dimension": dim, "slices_compared": len(rows), "top": top})
    return out


def w_additive(p: DataProduct, w: Watch) -> bool:
    m = next((m for m in ((p.spec or {}).get("model") or {}).get("metrics") or [] if m["name"] == w.metric), {})
    return bool(m.get("additive"))


# ── words ──────────────────────────────────────────────────────────────


def title_for(p: DataProduct, w: Watch, sig: D.Signal) -> str:
    label = w.label or w.metric
    m = _month(sig.period)
    if sig.detail.get("scaled") and sig.kind != "trend":
        return f"{label} moved from {_fmt(sig.baseline)} to {_fmt(sig.value)} ({m})"
    if sig.kind in ("spike", "drop"):
        return f"{label} {'jumped' if sig.direction == 'up' else 'fell'} {abs(sig.impact_pct or 0):.1f}% in {m}"
    if sig.kind == "trend":
        return f"{label} has been {'rising' if sig.direction == 'up' else 'falling'} for {sig.detail.get('periods')} months"
    if sig.kind == "shift":
        return f"{label} moved to a {'higher' if sig.direction == 'up' else 'lower'} level since {_month(date.fromisoformat(sig.detail['since']))}"
    if sig.kind == "crossing":
        return f"{label} turned {'positive' if sig.direction == 'up' else 'negative'} in {m}"
    return f"{label} {'reached its highest' if sig.direction == 'up' else 'fell to its lowest'} on record in {m}"


def plain_body(p: DataProduct, w: Watch, f: Dict[str, Any]) -> str:
    """The note in plain words from the facts alone (used in replays, and when the LLM's numbers do not check)."""
    s = f["signal"]
    parts = []
    label = w.label or w.metric
    pct_note = f" ({s['impact_pct']:+.1f}%)" if s.get("impact_pct") is not None else ""
    if s["kind"] in ("spike", "drop"):
        how_far = (f"{abs(s['impact_pct']):.1f}% " if s.get("impact_pct") is not None else "")
        parts.append(f"{label} was {_fmt(s['value'])} in {_month(date.fromisoformat(s['period']))}, "
                     f"{how_far}{'above' if s['direction'] == 'up' else 'below'} its usual "
                     f"{_fmt(s['baseline'])} over the previous {s.get('window', 12)} months.")
    elif s["kind"] == "trend":
        parts.append(f"{label} went from {_fmt(s['baseline'])} to {_fmt(s['value'])}{pct_note} over {s['periods']} months"
                     + (f", {s['streak']} months in a row" if s.get("streak", 0) >= 3 else "") + ".")
    elif s["kind"] == "shift":
        parts.append(f"{label} has averaged {_fmt(s['value'])} since {_month(date.fromisoformat(s['since']))}, "
                     f"against {_fmt(s['baseline'])} before{pct_note}.")
    elif s["kind"] == "crossing":
        parts.append(f"{label} went from {_fmt(s['from'])} to {_fmt(s['to'])}.")
    else:
        parts.append(f"{label} was {_fmt(s['value'])}, its {'highest' if s['direction'] == 'up' else 'lowest'} "
                     f"on record (previous {'high' if s['direction'] == 'up' else 'low'}: {_fmt(s['previous_record'])}).")
    for extra in f.get("also") or []:
        parts.append(f"It also shows a {extra['kind']} ({extra['impact_pct']:+.1f}%)." if extra.get("impact_pct") is not None
                     else f"It also shows a {extra['kind']}.")
    if f.get("valence") in ("good", "bad"):
        parts.append("That is a move in the right direction." if f["valence"] == "good" else "That is a move in the wrong direction.")
    for d in f.get("where") or []:
        top = d["top"][:2]
        if top:
            bits = ", ".join(f"{t['slice']} ({_fmt(t['delta'])}"
                             + (f", {t['share_of_change_pct']:.0f}% of the change" if "share_of_change_pct" in t else "")
                             + ")" for t in top)
            parts.append(f"By {d['dimension']}: most of it is {bits}.")
    if f.get("catch_up"):
        parts.insert(0, "Catching up on the recent past:")
    if f.get("as_of_last_data"):
        parts.append(f"This is as of {_month(date.fromisoformat(f['as_of_last_data']))}, the newest data there is — "
                     "not necessarily what is happening now.")
    if f.get("held_for_data"):
        parts.append("I'm holding this until the failing loads behind it run cleanly again.")
    elif f.get("status") == "provisional":
        parts.append(f"I'm treating this as provisional: {f['maturity']['reason']} I'll look again once "
                     f"{_month(date.fromisoformat(s['period']))} has settled.")
    seasonal = s.get("seasonal")
    if seasonal and s["kind"] not in ("spike", "drop"):
        parts.append(f"Against the same month last year it is {seasonal['yoy_pct']:+.1f}%.")
    return " ".join(parts)


_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def numbers_check(text: str, facts: Any) -> bool:
    """Every number the LLM wrote must be one the facts hold (as written, or within 1% once scaled)."""
    blob = json.dumps(facts, default=str)
    known = []
    for m in _NUM.findall(blob):
        try:
            known.append(float(m.replace(",", "")))
        except ValueError:
            pass
    for raw in _NUM.findall(text):
        x = float(raw.replace(",", ""))
        if abs(x) < 13 or raw in blob:   # small counts, ordinals, months and years pass
            continue
        if 1900 <= x <= 2100:
            continue
        ok = any(abs(x - k) <= max(0.011 * abs(k), 0.051) or
                 any(abs(x * s - k) <= 0.011 * abs(k) for s in (1e3, 1e6, 1e9)) for k in known)
        if not ok:
            return False
    return True


async def narrate(findings: List[Dict[str, Any]], context: Dict[str, Any]) -> Tuple[Dict[int, Dict[str, str]], Optional[str]]:
    """({index: {title, body}}, briefing) in an assistant's voice, or ({}, None) when unavailable."""
    from pydantic import BaseModel

    from kairos_kb.llm.provider import chat_model

    llm = chat_model()
    if llm is None or not (findings or context.get("quiet")):
        return {}, None

    class Note(BaseModel):
        index: int
        title: str
        body: str

    class Out(BaseModel):
        briefing: str
        notes: List[Note]

    system = (
        "You are a thoughtful business analyst and personal assistant who watches this company's numbers. "
        "Write like a trusted colleague: warm, calm, plain words, no hype, no jargon like 'z-score'. "
        "Use ONLY numbers that appear in the facts given; do not compute new ones. Say clearly when something "
        "is provisional and why you are waiting, when something is a data problem rather than a business change, "
        "and when a move is good or bad for the business. Describe where a change came from as where it is "
        "concentrated, never as a proven cause. Write numbers as the *_display fields show them (79.0M, 11.2k). "
        "When a finding has as_of_last_data, say plainly that it is as of that month because newer data has not "
        "arrived. "
        "Return exactly one note per finding, with the same index, about that finding's metric only. Each note: "
        "a title that says what happened (e.g. 'Market NRx up 12.5% since June'), then 2-4 sentences. Never write "
        "field names (change_pct, impact, baseline, periods_at_new_level), never write raw unrounded numbers, and "
        "write percentages with one decimal. When a finding has catch_up, say it is from the recent past. The "
        "briefing: 3-6 sentences opening with what matters most, then what you are waiting on (late data, failing "
        "loads, thin history), then what is steady. Speak as 'I'. Write months as the *_display fields do "
        "(Apr 2020), never ISO dates; never mention a note's status word (open, provisional); when impact_pct is "
        "absent give the before and after values instead of a percent.")
    human = json.dumps({"context": context, "findings": [{"index": i, **f} for i, f in enumerate(findings)]},
                       default=str)[:60000]
    try:
        out = await llm.with_structured_output(Out).ainvoke([("system", system), ("human", human)])
    except Exception:  # noqa: BLE001 — the plain words stand in
        logger.exception("Narration failed")
        return {}, None
    notes = {}
    for n in out.notes:
        if not 0 <= n.index < len(findings):
            continue
        f = findings[n.index]
        label = str(f.get("label") or f.get("metric") or "").lower()
        about_it = any(word in n.title.lower() for word in re.findall(r"[a-z]{3,}", label)[:3]) if label else True
        if about_it and numbers_check(n.title + " " + n.body, f):
            notes[n.index] = {"title": n.title[:500], "body": n.body}
    briefing = out.briefing if numbers_check(out.briefing, {"f": findings, "c": context}) else None
    return notes, briefing


# ── one look ───────────────────────────────────────────────────────────


async def ensure_watches(db: AsyncSession, ws: Workspace) -> int:
    made = 0
    for p in (await db.execute(select(DataProduct).where(DataProduct.workspace_id == ws.id))).scalars().all():
        has = (await db.execute(select(Watch.id).where(Watch.product_id == p.id).limit(1))).first()
        if not has:
            made += len(await derive(db, p))
            await db.commit()
    return made


async def look(db: AsyncSession, ws: Workspace, run: AgentRun, *, as_of: Optional[date] = None,
               cache: Optional[Dict[str, Any]] = None, mode: str = "live", narrate_notes: bool = True,
               progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """One look at the business. as_of=None: today, on live data; a date: as if that day were today (replay)."""
    progress = progress or (lambda _m: None)
    stats = {"watches": 0, "quiet": 0, "new": 0, "updated": 0, "confirmed": 0, "withdrawn": 0,
             "provisional": 0, "data_issues": 0, "partial_periods": 0, "errors": 0}
    products = {p.id: p for p in (await db.execute(select(DataProduct).where(DataProduct.workspace_id == ws.id))).scalars()}
    watches = (await db.execute(select(Watch).where(Watch.workspace_id == ws.id, Watch.status == "active")
                                .order_by(Watch.product_id, Watch.metric))).scalars().all()
    look_time = datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc) if as_of else datetime.now(timezone.utc)
    health_cache: Dict[Any, Dict[str, Any]] = {}
    created: List[Tuple[AgentNote, Dict[str, Any], Watch, DataProduct]] = []
    quiet_names: List[str] = []
    stale_products: Dict[Any, Tuple[DataProduct, date, date]] = {}
    thin: Dict[Any, Tuple[DataProduct, List[str]]] = {}
    data_held: Dict[Any, Tuple[DataProduct, Dict[str, Any], List[str]]] = {}

    for w in watches:
        p = products.get(w.product_id)
        if p is None:
            continue
        stats["watches"] += 1
        progress(f"Looking at {p.name} · {w.label or w.metric}")
        try:
            key = str(w.id)
            if cache is not None and key in cache:
                full, prov = cache[key]
            else:
                series, prov = await read_series(db, p, w)
                full = series.get("", [])
                if cache is not None:
                    cache[key] = (full, prov)
        except Exception as exc:  # noqa: BLE001 — one metric failing never stops the look
            logger.warning("Could not read %s.%s: %s", p.name, w.metric, exc)
            stats["errors"] += 1
            continue
        series = [(d, v) for d, v in full if as_of is None or d <= date(as_of.year, as_of.month, 1)]
        if len(series) < 7:
            if mode == "live":
                thin.setdefault(p.id, (p, []))[1].append(
                    f"{w.label or w.metric} ({len(series)} month{'s' if len(series) != 1 else ''})")
            stats["quiet"] += 1
            continue

        # Store this look's values (live looks only: they are the evidence of how numbers mature).
        if mode == "live":
            for d, v in series:
                db.add(MetricObservation(watch_id=w.id, slice="", period=d, value=v, as_of=look_time))

        # Maturity: hold back what may still change; never compare a partial month.
        mat = await maturity(db, w) if mode == "live" else {
            "measured": False, "settle_periods": w.settle_periods, "reason": w.settle_reason, "looks": 0, "curve": []}
        partial = None
        if ":" in w.time_dim:
            until = as_of or await latest_day(db, p, w)
            if until and is_partial(series[-1][0], until):
                partial = {"period": series[-1][0].isoformat(), "data_until": until.isoformat()}
                series = series[:-1]
                stats["partial_periods"] += 1
        k = int(mat["settle_periods"] or 0)
        settled = series[:-k] if k else series
        recent = series[-k:] if k else []

        signals: List[Tuple[D.Signal, str]] = []
        if len(settled) >= 7:
            signals += [(s, "open") for s in D.detect(settled, min_impact=w.min_impact_pct, sensitivity=w.sensitivity)]
        for i in range(len(recent)):
            upto = settled + recent[: i + 1]
            for s in D.detect(upto, min_impact=w.min_impact_pct, sensitivity=w.sensitivity * PROVISIONAL_SENSITIVITY):
                if s.kind in ("spike", "drop", "crossing", "record"):
                    signals.append((s, "provisional"))

        # First look at this metric: catch up on the last six settled months, as a person new to the job would —
        # the one strongest event, not every month that still shows it.
        if mode == "live" and not (await db.execute(select(AgentNote.id).where(
                AgentNote.watch_id == w.id, AgentNote.mode == "live").limit(1))).first():
            past: List[D.Signal] = []
            for cut in range(1, 7):
                sub = settled[:-cut]
                if len(sub) < 7:
                    break
                past += [s for s in D.detect(sub, min_impact=w.min_impact_pct, sensitivity=w.sensitivity)
                         if s.kind in ("spike", "drop", "record", "crossing", "shift")]
            if past:
                signals.append((max(past, key=lambda s: s.score), "open"))

        # Memory: what this agent already said about this metric.
        existing = (await db.execute(select(AgentNote).where(
            AgentNote.watch_id == w.id, AgentNote.mode == mode,
            AgentNote.run_id == (run.id if mode == "replay" else AgentNote.run_id),
            AgentNote.status.in_(("open", "provisional", "confirmed", "grouped")),
            AgentNote.kind.in_(("finding", "data_issue"))))).scalars().all()
        seen_keys = set()

        if p.id not in health_cache:
            health_cache[p.id] = await data_health(db, p) if mode == "live" else {"health": "healthy", "problems": []}
        health = health_cache[p.id]

        # Stale data is not "now": said once for the product, and what it shows is framed as of its last month.
        ref = as_of or date.today()
        stale = bool(series) and (ref.year - series[-1][0].year) * 12 + ref.month - series[-1][0].month > STALE_MONTHS
        if stale and mode == "replay":
            stats["quiet"] += 1
            continue  # a replayed month only hears about data that was current then
        if stale:
            prev = stale_products.get(p.id)
            lo, hi = (min(prev[1], series[-1][0]), max(prev[2], series[-1][0])) if prev else (series[-1][0], series[-1][0])
            stale_products[p.id] = (p, lo, hi)

        # One note per underlying event: the strongest signal leads, the others ride along. A shift or trend
        # is the same event whichever month it was seen from, when it began within two months of another.
        def event_month(s: D.Signal) -> date:
            return date.fromisoformat(s.detail["since"]) if s.kind in ("shift", "trend") and s.detail.get("since") else s.period

        merged: List[Tuple[D.Signal, str, List[D.Signal]]] = []
        for sig, status in sorted(signals, key=lambda x: -x[0].score):
            em = event_month(sig)
            for i, (lead, st, also) in enumerate(merged):
                lm = event_month(lead)
                if abs((em.year - lm.year) * 12 + em.month - lm.month) <= 2:
                    also.append(sig)
                    break
            else:
                merged.append((sig, status, []))

        for sig, status, also in merged:
            note_key = (sig.kind, sig.period)
            seen_keys.add(note_key)
            seen_keys.update((a.kind, a.period) for a in also)
            val = valence(sig.direction, w.good_direction)
            kind = "finding"
            held = bool(health["problems"]) and sig.period >= add_months(series[-1][0], -2)
            if held:
                status = "provisional"
                data_held.setdefault(p.id, (p, health, []))[2].append(w.label or w.metric)
            prior = next((n for n in existing if same_event(n, sig) or any(same_event(n, a) for a in also)), None)
            if prior:
                if prior.status == "provisional" and status == "open":
                    prior.status = "confirmed"
                    prior.facts = {**(prior.facts or {}), "confirmed_at": look_time.isoformat()}
                    stats["confirmed"] += 1
                    # Said out loud, at the moment it happened: the wait is over and it held.
                    conf = AgentNote(workspace_id=ws.id, run_id=run.id, mode=mode, watch_id=w.id, product_id=p.id,
                                     kind="finding", signal="confirmed", period=prior.period, as_of=look_time,
                                     importance=max(3, prior.importance), confidence=0.9, status="open",
                                     supersedes_id=prior.id,
                                     title=f"Confirmed: {prior.title}",
                                     body=(f"I held this back while {_month(prior.period)} settled. It has now, and "
                                           f"the change is still there, so I'm treating it as real. "
                                           + plain_body(p, w, {**(prior.facts or {}), "status": "open",
                                                               "held_for_data": False})),
                                     facts={**(prior.facts or {}), "status": "open", "confirms": str(prior.id),
                                            "confirmed_kind": prior.signal})
                    db.add(conf)
                    created.append((conf, conf.facts, w, p))
                else:
                    stats["updated"] += 1
                continue
            base_periods = [d for d, _ in settled[-4:-1]] if sig.kind in ("spike", "drop", "record", "crossing") else \
                [date.fromisoformat(sig.detail.get("since"))] if sig.detail.get("since") else []
            if sig.kind == "shift" and sig.detail.get("since"):
                since = date.fromisoformat(sig.detail["since"])
                base_periods = [d for d, _ in series if d < since][-3:]
            where = await where_it_moved(db, p, w, sig.period, base_periods) if (mode == "live" or narrate_notes) else []
            sd = sig.as_dict()
            sd["period_display"] = _month(sig.period)
            if sd.get("since"):
                sd["since_display"] = _month(date.fromisoformat(sd["since"]))
            if sd.get("scaled"):
                sd.pop("impact_pct", None)  # a percent of a negative or zero baseline reads backwards
            for k2 in ("value", "baseline", "previous_record", "from", "to"):
                if isinstance(sd.get(k2), (int, float)):
                    sd[f"{k2}_display"] = _fmt(sd[k2])
            for d in where:
                for t in d["top"]:
                    t["delta_display"], t["value_display"] = _fmt(t["delta"]), _fmt(t["value"])
            facts = {"product": p.name, "metric": w.metric, "label": w.label, "signal": sd,
                     "also": [{"kind": a.kind, "impact_pct": a.impact_pct} for a in also], "held_for_data": held,
                     "valence": val, "good_direction": w.good_direction, "status": status, "where": where,
                     "maturity": {k2: mat.get(k2) for k2 in ("measured", "settle_periods", "reason", "looks")},
                     "partial": partial, "data_health": health, "query": prov,
                     "series_tail": [[d.isoformat(), v] for d, v in series[-14:]]}
            if stale:
                facts["as_of_last_data"] = series[-1][0].isoformat()
            if settled and sig.period < settled[-1][0]:
                facts["catch_up"] = True
            note = AgentNote(workspace_id=ws.id, run_id=run.id, mode=mode, watch_id=w.id, product_id=p.id,
                             kind=kind, signal=sig.kind, title=title_for(p, w, sig), facts=facts,
                             period=sig.period, as_of=look_time,
                             importance=max(1, importance(sig, val) - (3 if stale else 0)),
                             confidence=0.5 if status == "provisional" else min(0.95, 0.6 + sig.score / 40),
                             status=status)
            note.body = plain_body(p, w, facts)
            db.add(note)
            created.append((note, facts, w, p))
            stats["provisional" if status == "provisional" else "new"] += 1

        # A provisional note whose period has now settled without the signal: withdraw it, and say so.
        settled_periods = {d for d, _ in settled}
        for n in existing:
            if n.status == "provisional" and n.period in settled_periods and (n.signal, n.period) not in seen_keys:
                n.status = "withdrawn"
                stats["withdrawn"] += 1
                corr = AgentNote(workspace_id=ws.id, run_id=run.id, mode=mode, watch_id=w.id, product_id=p.id,
                                 kind="correction", signal=n.signal, period=n.period, as_of=look_time,
                                 title=f"Correction: {w.label or w.metric} for {_month(n.period)} settled back to normal",
                                 body=(f"Earlier I flagged {w.label or w.metric} for {_month(n.period)} as provisional. "
                                       "Now that the month has settled, the change is no longer there, so I'm withdrawing it."),
                                 facts={"withdrawn": str(n.id), "series_tail": [[d.isoformat(), v] for d, v in series[-14:]]},
                                 importance=4, confidence=0.8, status="open", supersedes_id=n.id)
                db.add(corr)
        if not signals:
            stats["quiet"] += 1
            quiet_names.append(f"{p.name} · {w.label or w.metric}")
    # Metrics that moved together are one story: three or more with the same kind of change, the same
    # direction, in the same month (or a shift or trend that began within two months), become one note.
    # The members stay in memory (status "grouped") so the agent does not repeat any of them.
    def bucket(note: AgentNote, facts: Dict[str, Any]) -> Tuple[str, str, str]:
        sig = facts.get("signal") or {}
        kind = facts.get("confirmed_kind") and f"confirmed:{facts['confirmed_kind']}" or note.signal or ""
        month = sig.get("since") if note.signal in ("shift", "trend") and sig.get("since") else str(note.period)
        if month and month != "None":
            d = date.fromisoformat(month[:10])
            month = f"{d.year}-{(d.month - 1) // 3}"   # within the same quarter-ish window
        return kind, sig.get("direction") or "", month

    groups: Dict[Tuple[str, str, str], List[Tuple[AgentNote, Dict[str, Any], Watch, DataProduct]]] = {}
    for item in created:
        note, facts = item[0], item[1]
        if note.kind == "finding" and note.signal not in ("crossing",):
            groups.setdefault(bucket(note, facts), []).append(item)
    grouped_out: List[Tuple[AgentNote, Dict[str, Any], Watch, DataProduct]] = []
    for (kind, direction, _m), items in groups.items():
        if len(items) < 3:
            continue
        items.sort(key=lambda x: -x[0].importance)
        lead_note, lead_facts, lead_w, lead_p = items[0]
        members = []
        for note, facts, w, p in items:
            sig = facts.get("signal") or {}
            members.append({"label": w.label or w.metric, "product": p.name, "watch_id": str(w.id),
                            "impact_pct": sig.get("impact_pct"), "value_display": sig.get("value_display"),
                            "baseline_display": sig.get("baseline_display"), "valence": facts.get("valence")})
            note.status = "grouped"
        names = [m["label"] for m in members]
        what = {"record": "hit new highs" if direction == "up" else "hit new lows",
                "shift": "moved to a higher level" if direction == "up" else "moved to a lower level",
                "trend": "kept rising" if direction == "up" else "kept falling",
                "spike": "jumped", "drop": "fell"}.get(kind.split(":")[-1], "changed together")
        when = _month(lead_note.period) if lead_note.period else ""
        confirmed = kind.startswith("confirmed:")
        title = (f"{'Confirmed: ' if confirmed else ''}{', '.join(names[:3])}"
                 f"{f' and {len(names) - 3} more' if len(names) > 3 else ''} {what}"
                 + (f" since {_month(date.fromisoformat(lead_facts['signal']['since']))}"
                    if kind in ("shift", "trend") and (lead_facts.get("signal") or {}).get("since") else f" in {when}"))
        lines = [f"- {m['label']} ({m['product']}): {m['baseline_display'] or ''} → {m['value_display'] or ''}"
                 + (f" ({m['impact_pct']:+.1f}%)" if isinstance(m.get("impact_pct"), (int, float)) else "")
                 for m in members]
        story = AgentNote(workspace_id=ws.id, run_id=run.id, mode=mode, watch_id=lead_w.id, product_id=lead_p.id,
                          kind="finding", signal=f"group:{kind}", period=lead_note.period, as_of=look_time,
                          importance=min(10, lead_note.importance + 1), confidence=lead_note.confidence,
                          status="provisional" if all(n.status == "provisional" for n, *_ in items) else "open",
                          title=title,
                          body=(f"These moved together, so I'm telling you once: {len(members)} metrics "
                                f"{what}. " + ("I'd read them as one change in the business rather than "
                                               f"{len(members)} separate ones.\n\n" if not confirmed else "\n\n")
                                + "\n".join(lines)),
                          facts={**lead_facts, "members": members, "grouped": len(members)})
        db.add(story)
        grouped_out.append((story, story.facts, lead_w, lead_p))
    created = [c for c in created if c[0].status != "grouped"] + grouped_out

    # Said once per product: data that stopped long ago, and loads that are failing right now.
    for p, first_last, last in stale_products.values():
        if not await _said_recently(db, ws.id, p.id, "stale", mode, run):
            spread = (f" (some of its metrics stop as early as {_month(first_last)})" if first_last != last else "")
            db.add(AgentNote(workspace_id=ws.id, run_id=run.id, mode=mode, product_id=p.id, kind="data_issue",
                             signal="stale", period=last, as_of=look_time, importance=5, confidence=0.95,
                             status="open", title=f"{p.name}: no new data since {_month(last)}",
                             body=(f"The newest data behind {p.name} is from {_month(last)}{spread}, so I'm "
                                   "reading what it shows as of then, not as what is happening now. If it should "
                                   "still be loading, the pipelines that feed it are worth checking."),
                             facts={"product": p.name, "last_period": last.isoformat(),
                                    "earliest_last_period": first_last.isoformat()}))
            stats["data_issues"] += 1
    for p, names in thin.values():
        if not await _said_recently(db, ws.id, p.id, "thin_history", mode, run):
            db.add(AgentNote(workspace_id=ws.id, run_id=run.id, mode=mode, product_id=p.id, kind="data_issue",
                             signal="thin_history", as_of=look_time, importance=4, confidence=0.95, status="open",
                             title=f"{p.name}: too little history to watch some metrics",
                             body=(f"I can't watch {', '.join(names[:5])} yet: there is too little monthly history "
                                   "to know what normal looks like (I need at least seven months). If these should "
                                   "have more history, the tables behind them may hold only a recent load."),
                             facts={"product": p.name, "metrics": names}))
            stats["data_issues"] += 1
    for p, health, held in data_held.values():
        if not await _said_recently(db, ws.id, p.id, "failing_loads", mode, run):
            db.add(AgentNote(workspace_id=ws.id, run_id=run.id, mode=mode, product_id=p.id, kind="data_issue",
                             signal="failing_loads", as_of=look_time, importance=7, confidence=0.9, status="open",
                             title=f"{p.name}: recent numbers are on hold — loads are failing",
                             body=(f"Before reading the latest {p.name} numbers: " + "; ".join(health["problems"][:3])
                                   + f". I'm holding what I noticed on {', '.join(sorted(set(held))[:5])} until "
                                   "those run cleanly, so a broken load isn't mistaken for a business change."),
                             facts={"product": p.name, "problems": health["problems"], "held": sorted(set(held))}))
            stats["data_issues"] += 1
    await db.flush()

    # Words: the LLM writes from the computed facts (live), the plain words stand otherwise.
    if narrate_notes and created:
        progress("Writing it up")
        notes, briefing = await narrate([f for _, f, _, _ in created],
                                        {"as_of": look_time.date().isoformat(), "quiet": quiet_names[:30],
                                         "stats": stats})
        for i, (note, _f, _w, _p) in enumerate(created):
            if i in notes:
                note.title, note.body = notes[i]["title"], notes[i]["body"]
                note.facts = {**(note.facts or {}), "written_by": "llm (numbers checked)"}
        if briefing:
            db.add(AgentNote(workspace_id=ws.id, run_id=run.id, mode=mode, kind="briefing",
                             title=f"Briefing · {look_time.date().strftime('%d %b %Y')}", body=briefing,
                             facts={"stats": stats}, as_of=look_time, importance=6, confidence=0.8, status="open"))
    await db.flush()
    return stats


def _event_month(kind: Optional[str], period: Optional[date], since: Optional[str]) -> Optional[date]:
    if kind in ("shift", "trend") and since:
        return date.fromisoformat(since)
    return period


def same_event(n: AgentNote, sig: D.Signal) -> bool:
    """A remembered note and a new signal describe the same change: same kind, and for a shift or a
    trend the same start (within two months); otherwise the same month."""
    if n.signal != sig.kind:
        return False
    a = _event_month(n.signal, n.period, ((n.facts or {}).get("signal") or {}).get("since"))
    b = _event_month(sig.kind, sig.period, sig.detail.get("since"))
    if not a or not b:
        return False
    gap = abs((a.year - b.year) * 12 + a.month - b.month)
    return gap <= 2 if sig.kind in ("shift", "trend") else gap == 0


async def _said_recently(db: AsyncSession, workspace_id, product_id, signal: str, mode: str, run: AgentRun) -> bool:
    """Whether an open note of this kind already stands for the product (so it is not repeated every look)."""
    q = select(AgentNote.id).where(AgentNote.workspace_id == workspace_id, AgentNote.product_id == product_id,
                                   AgentNote.signal == signal, AgentNote.status == "open", AgentNote.mode == mode)
    if mode == "replay":
        q = q.where(AgentNote.run_id == run.id)
    return (await db.execute(q.limit(1))).first() is not None


async def execute(run_id: uuid.UUID, *, start: Optional[date] = None, end: Optional[date] = None,
                  progress: Optional[Callable[[str], None]] = None) -> None:
    """Drive one run to the end: a live look, or a replay over [start, end] month by month."""
    progress = progress or (lambda _m: None)
    async with async_session_factory() as db:
        run = await db.get(AgentRun, run_id)
        ws = await db.get(Workspace, run.workspace_id)
        try:
            progress("Setting up the watch list")
            made = await ensure_watches(db, ws)
            if run.mode == "live":
                stats = await look(db, ws, run, progress=progress)
                stats["watches_created"] = made
            else:
                await db.execute(delete(AgentNote).where(AgentNote.workspace_id == ws.id, AgentNote.mode == "replay"))
                cache: Dict[str, Any] = {}
                stats = {"steps": [], "watches_created": made}
                step = date(start.year, start.month, 1)
                last = date(end.year, end.month, 1)
                while step <= last:
                    progress(f"Replaying {step.strftime('%b %Y')}")
                    s = await look(db, ws, run, as_of=month_end(step), cache=cache, mode="replay",
                                   narrate_notes=False, progress=lambda _m: None)
                    stats["steps"].append({"as_of": month_end(step).isoformat(), **s})
                    run.stats = json.loads(json.dumps(stats))  # a new object: in-place changes are not saved
                    await db.commit()
                    step = add_months(step, 1)
                stats["totals"] = {k: sum(s[k] for s in stats["steps"]) for k in
                                   ("new", "provisional", "confirmed", "withdrawn", "data_issues")}
            run.status, run.stats, run.finished_at = "completed", json.loads(json.dumps(stats)), datetime.now(timezone.utc)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — shown on the screen
            logger.exception("Living agent run failed")
            await db.rollback()
            run = await db.get(AgentRun, run_id)
            run.status, run.error, run.finished_at = "failed", str(exc)[:1000], datetime.now(timezone.utc)
            await db.commit()


_TASKS: Dict[str, Dict[str, Any]] = {}


def start(run_id: uuid.UUID, **kw) -> Dict[str, Any]:
    state = {"run_id": str(run_id), "step": "Starting"}

    def progress(msg: str) -> None:
        state["step"] = msg

    _TASKS[str(run_id)] = state
    state["task"] = asyncio.create_task(execute(run_id, progress=progress, **kw))
    return state


def step_of(run_id: uuid.UUID) -> Optional[str]:
    s = _TASKS.get(str(run_id))
    return s["step"] if s and not s["task"].done() else None
