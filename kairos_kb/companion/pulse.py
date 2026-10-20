"""The companion's pulse: one look at how the business is doing right now.

  1. clock      the newest event in the data, and the time zone its timestamps are written in
                (inferred once from a live stream, or set by a person). Data whose newest event
                is more than a day and a half old is not live: the companion says so and looks
                rarely.
  2. pace       each vital today-so-far against normal days at the same minute (pace.py). The
                comparison stops at the newest event the data has reached, so the few minutes a
                pipeline takes to land rows never read as a dip.
  3. judge      normal, above or below; how strongly; good or bad for the business.
  4. remember   a gap becomes a moment only when it holds for two looks in a row (or is very
                strong); the same moment is updated as the day goes on, never repeated; when the
                number is back to normal for two looks the moment is resolved, and said so. A
                sharp break in the last full hour, and a stream that stops, are moments too.
  5. explain    where a gap sits: today's slices (cities, restaurants) against their usual share.
  6. tell       a one-line headline of how things stand, rewritten only when the picture changes
                (or every half hour); each new moment in plain words; and once a day, after
                midnight, how yesterday closed. The LLM writes from computed facts only, and
                every number it writes is checked against them.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.companion import pace as P
from kairos_kb.companion.vitals import EVENT_DIM, choose, live_model, num, run, ts
from kairos_kb.living.agent import _fmt, numbers_check
from kairos_kb.models.companion import CompanionPulse, CompanionState
from kairos_kb.models.data_product import DataProduct
from kairos_kb.models.living import AgentNote, Watch
from kairos_kb.models.workspace import Workspace

logger = logging.getLogger(__name__)

LIVE_WINDOW = timedelta(hours=36)
STALL_MINUTES = 20
RECOVERED_TOLD = 7  # a stream coming back after she told the owner it stopped: raised (initiative.RAISE_AT and up)
# Not live: still looked at every half hour (JENNY_IDLE_INTERVAL_S), so a stream that comes back is noticed soon.
NOT_LIVE_INTERVAL = int(os.getenv("JENNY_IDLE_INTERVAL_S", str(30 * 60)))
# The headline carries today's running numbers, so it is rewritten on every live look.
KEEP_PULSES = timedelta(days=3)
F = "%Y-%m-%d %H:%M:%S"
_RATE_CACHE: Dict[Tuple[str, str, str, Tuple[str, ...]], Dict[str, Optional[float]]] = {}


# ── words for numbers ───────────────────────────────────────────────


def show(v: Optional[float], unit: str = "", metric: str = "") -> str:
    if v is None:
        return "–"
    u, m = (unit or "").lower(), (metric or "").lower()
    if u in ("ratio", "rate", "share", "fraction") or (re.search(r"rate|share|ratio", m) and abs(v) <= 1.5):
        return f"{v * 100:.1f}%"
    if u in ("minutes", "minute", "min") or re.search(r"time_min|minutes|_min$", m):
        return f"{v:.1f} min"
    if (u == "count" or re.search(r"orders?$|count|units|qty|quantity", m)) and abs(v) < 1e4:
        return f"{v:,.0f}"  # whole things are counted whole
    return _fmt(v)


def _clock(t: datetime) -> str:
    return t.strftime("%H:%M")


def infer_offset(data_now: datetime, utc_now: datetime) -> Optional[int]:
    """Minutes ahead of UTC the data's clock runs, from a live stream's newest event (rounded up to
    the quarter hour, since the newest event is a little behind the present). None when not live."""
    diff = (data_now - utc_now).total_seconds() / 60
    if not -14 * 60 <= diff <= 14 * 60 + 5:
        return None
    return int(math.ceil(diff / 15) * 15)


# ── reading ─────────────────────────────────────────────────────────


async def data_clock(db: AsyncSession, model: Dict[str, Any], metric: str) -> Optional[datetime]:
    """The newest event time the data holds."""
    utc = datetime.utcnow()
    for flt in ([{"dimension": EVENT_DIM, "op": ">=", "value": (utc - timedelta(days=3)).strftime(F)}], None):
        r = await run(db, model, [metric], [EVENT_DIM], filters=flt, order=f"{EVENT_DIM} desc", limit=1)
        rows = r.get("rows") or []
        if rows and ts(rows[0][0]):
            return ts(rows[0][0])
    return None


def _between(a: datetime, b: datetime) -> List[Dict[str, Any]]:
    return [{"dimension": EVENT_DIM, "op": "between", "value": [a.strftime(F), b.strftime(F)]}]


async def hourly(db: AsyncSession, model: Dict[str, Any], metrics: List[str], start: datetime, cut: datetime
                 ) -> Tuple[Dict[str, Dict[datetime, float]], Optional[str]]:
    """Hour-by-hour values from start to cut. Read in windows of five weeks: the SQL guard returns at
    most 1,000 rows, and eight weeks of hours is more than that."""
    out: Dict[str, Dict[datetime, float]] = {m: {} for m in metrics}
    a = start
    while a <= cut:
        b = min(cut, a + timedelta(days=35) - timedelta(seconds=1))
        r = await run(db, model, metrics, [f"{EVENT_DIM}:hour"], filters=_between(a, b), limit=1000)
        if r.get("error"):
            return {}, r["error"]
        if r.get("truncated"):
            logger.warning("Hourly read cut short between %s and %s", a, b)
        for row in r.get("rows") or []:
            t = ts(row[0])
            if t is None:
                continue
            for i, m in enumerate(metrics):
                v = num(row[1 + i])
                if v is not None:
                    out[m][t] = v
        a = b + timedelta(seconds=1)
    return out, None


async def values_until(db: AsyncSession, model: Dict[str, Any], metrics: List[str], a: datetime, b: datetime
                       ) -> Dict[str, Optional[float]]:
    r = await run(db, model, metrics, [], filters=_between(a, b), limit=1)
    rows = r.get("rows") or []
    return {m: (num(rows[0][i]) if rows else None) for i, m in enumerate(metrics)}


async def daily(db: AsyncSession, model: Dict[str, Any], metrics: List[str], start: datetime, end: datetime
                ) -> Dict[str, Dict[date, float]]:
    r = await run(db, model, metrics, [f"{EVENT_DIM}:day"], filters=_between(start, end), limit=200)
    out: Dict[str, Dict[date, float]] = {m: {} for m in metrics}
    for row in r.get("rows") or []:
        t = ts(row[0])
        for i, m in enumerate(metrics):
            v = num(row[1 + i])
            if t is not None and v is not None:
                out[m][t.date()] = v
    return out


async def where_today(db: AsyncSession, model: Dict[str, Any], v: Dict[str, Any], today: date, cut: datetime,
                      actual: float, expected: float) -> List[Dict[str, Any]]:
    """Where a gap sits: each slice today against its usual share of the expected total."""
    out = []
    start = datetime.combine(today, time.min)
    gap = actual - expected
    for dim in (v.get("slices") or [])[:2]:
        t = await run(db, model, [v["metric"]], [dim], filters=_between(start, cut), order=f"{v['metric']} desc", limit=3000)
        b = await run(db, model, [v["metric"]], [dim], filters=_between(start - timedelta(days=28), start - timedelta(seconds=1)),
                      order=f"{v['metric']} desc", limit=3000)
        if t.get("error") or b.get("error"):
            continue
        now_map = {str(r[0]): num(r[1]) or 0.0 for r in t.get("rows") or []}
        base_map = {str(r[0]): num(r[1]) or 0.0 for r in b.get("rows") or []}
        base_total = sum(base_map.values())
        if not base_total:
            continue
        rows = []
        for s in set(now_map) | set(base_map):
            exp_s = base_map.get(s, 0.0) / base_total * expected
            delta = now_map.get(s, 0.0) - exp_s
            rows.append({"slice": s, "today": now_map.get(s, 0.0), "usual": round(exp_s, 2), "delta": round(delta, 2),
                         "change_pct": P.pct(now_map.get(s, 0.0), exp_s),
                         "share_of_gap_pct": round(delta / gap * 100, 1) if gap else None})
        # The slices that carry the gap (same sign as the gap) first; the ones pulling the other way after.
        rows.sort(key=lambda r: -(r["delta"] * (1 if gap >= 0 else -1)))
        top, against = rows[:4], [r for r in rows[::-1][:3] if r["delta"] * (1 if gap >= 0 else -1) < 0]
        for r in top + against:
            r["today_display"], r["usual_display"] = show(r["today"], v.get("unit"), v["metric"]), show(r["usual"], v.get("unit"), v["metric"])
            r["delta_display"] = ("+" if r["delta"] >= 0 else "−") + show(abs(r["delta"]), v.get("unit"), v["metric"])
        out.append({"dimension": dim, "slices_compared": len(rows), "top": top, "against": against})
    return out


# ── words ───────────────────────────────────────────────────────────


def _displays(v: Dict[str, Any], p: Dict[str, Any]) -> Dict[str, str]:
    u, m = v.get("unit") or "", v["metric"]
    out = {f"{k}_display": show(p.get(k), u, m) for k in ("actual", "expected", "low", "high", "projection", "expected_full")
           if p.get(k) is not None}
    return out


def moment_plain(v: Dict[str, Any], f: Dict[str, Any], weekday: str) -> Tuple[str, str]:
    p, label = f["pace"], v["label"]
    dev = p.get("dev_pct")
    when = f["local_time"]
    word = "above" if f["direction"] == "up" else "below"
    if f["signal"] == "hour_break":
        h = f["hour"]
        title = f"{label} {abs(h['dev_pct']):.1f}% {word} normal in the {h['hour']:02d}:00 hour"
        body = (f"Between {h['hour']:02d}:00 and {h['hour'] + 1:02d}:00 {label.lower()} came to {h['actual_display']}, against "
                f"a usual {h['expected_display']} for that hour on {p['basis']}.")
    else:
        title = f"{label} running {abs(dev or 0):.1f}% {word} a normal {weekday}" if dev is not None else \
            f"{label} {word} a normal {weekday}"
        body = (f"By {when}, {label.lower()} is {p.get('actual_display')}; on {p['basis']} it was {p.get('expected_display')} "
                f"by this time (between {p.get('low_display')} and {p.get('high_display')}).")
        if p.get("projection_display") and p.get("expected_full_display"):
            body += f" On this pace the day closes near {p['projection_display']}, against a usual {p['expected_full_display']}."
    for d in f.get("where") or []:
        top = [t for t in d["top"][:2] if t.get("share_of_gap_pct") and t["share_of_gap_pct"] > 0]
        if top:
            bits = ", ".join(f"{t['slice']} ({t['delta_display']})" for t in top)
            body += f" Most of it is in {bits} by {d['dimension'].replace('_', ' ')}."
    if f["valence"] == "bad":
        body += " That's the wrong direction for the business."
    elif f["valence"] == "good":
        body += " That's working in the business's favour."
    return title, body


def sane(text: Optional[str], min_words: int = 5) -> bool:
    """Words a person would write: enough of them, mostly letters. A model can return fragments
    (":{") that carry no numbers and so pass the numbers check; they never reach the screen."""
    if not text:
        return False
    t = text.strip()
    words = re.findall(r"[A-Za-z][A-Za-z'’-]+", t)
    letters = sum(ch.isalpha() for ch in t)
    return len(words) >= min_words and letters >= 0.5 * len(t.replace(" ", "")) and not re.match(r"^[\W_]", t)


async def _llm_json(system: str, payload: Any, schema):
    from kairos_kb.llm.provider import chat_model

    llm = chat_model()
    if llm is None:
        return None
    try:
        return await llm.with_structured_output(schema).ainvoke(
            [("system", system), ("human", json.dumps(payload, default=str)[:40000])])
    except Exception:  # noqa: BLE001 — the plain words stand in
        logger.exception("Companion narration failed")
        return None


VOICE = ("You are Jenny, this business's companion — a calm, sharp chief of staff who watches the live numbers all day "
         "(think JARVIS, but understated). Speak as 'I', to the owner as 'you'. Plain words, no hype, no jargon "
         "(never 'z-score', 'baseline', 'spread', 'MAD'). Use ONLY numbers that appear in the facts, written as the "
         "*_display fields show them, and percentages with one decimal and no sign after a direction word "
         "('down 12.4%', never 'down -12.4%'). Say where a gap is concentrated, never claim "
         "a cause. Say whether a move is good or bad for the business when the facts say so.")


async def narrate_moments(items: List[Dict[str, Any]]) -> Dict[int, Tuple[str, str]]:
    from pydantic import BaseModel

    class M(BaseModel):
        index: int
        title: str
        body: str

    class Out(BaseModel):
        moments: List[M]

    if not items:
        return {}
    out = await _llm_json(
        VOICE + " For each moment write a title (what is happening, e.g. 'Orders running 12.4% below a normal "
        "Friday') and 2-3 sentences: where it stands against a normal day at this time, the projected close when "
        "given, where it is concentrated, and whether it matters. One entry per index.",
        [{"index": i, **f} for i, f in enumerate(items)], Out)
    res = {}
    for m in (out.moments if out else []):
        if 0 <= m.index < len(items) and sane(m.title, 3) and sane(m.body, 8) and                 numbers_check(m.title + " " + m.body, items[m.index]):
            res[m.index] = (m.title[:500], m.body)
    return res


async def write_headline(facts: Dict[str, Any]) -> Optional[str]:
    from pydantic import BaseModel

    class Out(BaseModel):
        headline: str

    out = await _llm_json(
        VOICE + " Write the status line the owner sees first: at most two sentences, under 40 words, on how the "
        "business is doing right now. Only vitals whose status is 'above' or 'below' are off normal; 'normal' ones "
        "are on track whatever their small difference, and never call them good or bad; 'early' ones are too early in "
        "the day to read — say it's early, never strong or weak. Lead with what matters most "
        "(a bad gap first, then a good one); if everything is normal, say so with the core volume so far and where "
        "the day is heading. Mention data that has stopped flowing.",
        facts, Out)
    if out and sane(out.headline) and numbers_check(out.headline, facts):
        # A status line, not a report: the first two sentences, however much the model wrote.
        sentences = re.split(r"(?<=[.!?])\s+", out.headline.strip())
        return " ".join(sentences[:2])
    return None


def plain_headline(snapshot: Dict[str, Any], weekday: str) -> str:
    vit = [v for v in snapshot.get("vitals") or [] if v.get("status") not in ("stale", "error", None)]
    if snapshot.get("stalled"):
        return f"No new data for {snapshot['lag_minutes']:.0f} minutes — the stream may have stopped."
    off = sorted([v for v in vit if v["status"] in ("above", "below")],
                 key=lambda v: (v.get("valence") != "bad", -abs(v.get("dev_pct") or 0)))
    if off:
        v = off[0]
        return (f"{v['label']} is {abs(v.get('dev_pct') or 0):.1f}% {v['status']} a normal {weekday} by "
                f"{snapshot['local_time']}." + (" The rest looks normal." if len(off) == 1 else ""))
    lead = next((v for v in vit if v.get("additive")), vit[0] if vit else None)
    if not lead:
        return "Nothing I can read live yet."
    if lead.get("status") == "early":
        return (f"Early hours: {lead['label'].lower()} {lead['actual_display']} by {snapshot['local_time']} — too soon to "
                "read the day yet.")
    pace = f", on pace for {lead['projection_display']}" if lead.get("projection_display") else ""
    return f"A normal {weekday} so far: {lead['label'].lower()} {lead['actual_display']} by {snapshot['local_time']}{pace}."


# ── one pulse ───────────────────────────────────────────────────────


async def _watch_id(db: AsyncSession, product_id: str, metric: str):
    w = (await db.execute(select(Watch.id).where(Watch.product_id == product_id, Watch.metric == metric))).first()
    return w[0] if w else None


def _note(ws: Workspace, utc: datetime, today: Optional[date], **kw) -> AgentNote:
    return AgentNote(workspace_id=ws.id, mode="live", as_of=utc, period=today, status="open", **kw)


async def pulse(db: AsyncSession, ws: Workspace, st: CompanionState, *, force: bool = False) -> Dict[str, Any]:
    utc = datetime.now(timezone.utc)
    utc_naive = utc.replace(tzinfo=None)
    mem: Dict[str, Any] = json.loads(json.dumps(st.memory or {}))
    if not st.vitals:
        st.vitals = await choose(db, ws.id)
        await db.flush()
    vitals: List[Dict[str, Any]] = list(st.vitals or [])
    stats = {"vitals": len(vitals), "moments": 0, "resolved": 0, "queries": 0}
    if not vitals:
        st.snapshot = {"as_of": utc.isoformat(), "live": False, "reason": "no_clock", "vitals": []}
        st.headline = ("I can't watch anything here live yet: none of the data products record when each event "
                       "happened, only the day. I'll keep the monthly notebook instead.")
        st.headline_at, st.live, st.last_pulse_at = utc, False, utc
        return stats

    products = {str(p.id): p for p in (await db.execute(select(DataProduct).where(
        DataProduct.id.in_({v["product_id"] for v in vitals})))).scalars()}
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for v in vitals:
        if v["product_id"] in products:
            groups.setdefault(v["product_id"], []).append(v)

    clocks: Dict[str, Tuple[Dict[str, Any], Optional[datetime]]] = {}
    for pid, vs in groups.items():
        model = live_model(products[pid], vs[0]["event"])
        clocks[pid] = (model, await data_clock(db, model, vs[0]["metric"]))
    newest = max((c[1] for c in clocks.values() if c[1]), default=None)
    if st.tz_offset_minutes is None and newest:
        off = infer_offset(newest, utc_naive)
        if off is not None:
            st.tz_offset_minutes, st.tz_source = off, "inferred"
    offset = st.tz_offset_minutes
    local_now = utc_naive + timedelta(minutes=offset) if offset is not None else None
    live = bool(local_now and newest and local_now - newest <= LIVE_WINDOW)
    today = local_now.date() if live else None
    weekday = today.strftime("%A") if today else ""

    if today and mem.get("day") != today.isoformat():
        mem = {"day": today.isoformat(), "streak": {}, "calm": {}, "open": {}, "hours": [], "stall": {},
               "last_close": mem.get("last_close")}
    for k in ("streak", "calm", "open", "hours", "stall"):
        mem.setdefault(k, [] if k == "hours" else {})

    out_vitals: List[Dict[str, Any]] = []
    new_moments: List[Tuple[AgentNote, Dict[str, Any], Dict[str, Any]]] = []
    hourly_cache: Dict[str, Dict[str, Dict[datetime, float]]] = {}
    stalled_products: List[Tuple[str, float]] = []

    for pid, vs in groups.items():
        p = products[pid]
        model, dnow = clocks[pid]
        base_fields = lambda v: {k: v.get(k) for k in ("key", "product", "metric", "label", "unit", "additive",  # noqa: E731
                                                     "good_direction", "why")}
        if not live or not dnow or local_now - dnow > LIVE_WINDOW:
            for v in vs:
                out_vitals.append({**base_fields(v), "status": "stale", "data_until": dnow.isoformat(sep=" ") if dnow else None})
            continue
        lag = (local_now - dnow).total_seconds() / 60
        cut = dnow if lag <= STALL_MINUTES and dnow.date() == today else local_now
        start = datetime.combine(today - timedelta(days=7 * P.WEEKS), time.min)
        metrics = [v["metric"] for v in vs]
        hours, err = await hourly(db, model, metrics, start, cut)
        stats["queries"] += 1
        hourly_cache[pid] = hours
        if err:
            for v in vs:
                out_vitals.append({**base_fields(v), "status": "error", "error": err[:300]})
            continue
        rates = [v for v in vs if not v["additive"]]
        rate_today: Dict[str, Optional[float]] = {}
        rate_base: Dict[str, Dict[date, float]] = {v["metric"]: {} for v in rates}
        if rates:
            rm = [v["metric"] for v in rates]
            rate_today = await values_until(db, model, rm, datetime.combine(today, time.min), cut)
            stats["queries"] += 1
            have_days = {t.date() for t in hours.get(rm[0], {})}
            days, _basis = P.baseline_days(today, [d for d in have_days if d < today])
            bucket = cut.replace(minute=cut.minute - cut.minute % 15, second=0)
            for d in days:
                key = (pid, d.isoformat(), bucket.strftime("%H:%M"), tuple(rm))
                if key not in _RATE_CACHE:
                    _RATE_CACHE[key] = await values_until(db, model, rm, datetime.combine(d, time.min),
                                                          datetime.combine(d, bucket.time()))
                    stats["queries"] += 1
                for m, val in _RATE_CACHE[key].items():
                    if val is not None:
                        rate_base[m][d] = val
        for v in vs:
            m = v["metric"]
            if v["additive"]:
                pc = P.pace_additive(hours.get(m, {}), today, cut, count_like=(v.get("unit") or "count") in ("count", ""))
            else:
                pc = P.pace_rate(rate_today.get(m), rate_base.get(m, {}), hours.get(m, {}), today, cut)
            if pc is None:
                out_vitals.append({**base_fields(v), "status": "learning", "note": "Not enough history at this hour yet."})
                continue
            verdict = P.judge(pc, v["good_direction"])
            pc.update(_displays(v, pc))
            if pc.get("hour"):
                h = pc["hour"]
                h["actual_display"], h["expected_display"] = show(h["actual"], v.get("unit"), m), show(h["expected"], v.get("unit"), m)
            out_vitals.append({**base_fields(v), **verdict, **{k: pc[k] for k in pc if k != "kind"},
                               "z": round(pc["z"], 2), "lag_minutes": round(lag, 1)})
        # A rate read off a handful of events says little: while this product's day is still in its first few
        # percent (as its counts show), its rates are "early" too, not above or below.
        mine = out_vitals[-len(vs):]
        day_done = [o["share_done"] for o in mine if o.get("additive") and o.get("share_done") is not None]
        if day_done and min(day_done) < 0.08:
            for o in mine:
                if not o.get("additive") and o.get("status") in ("above", "below"):
                    o.update(status="early", direction=None, strength=None, valence="neutral")
        # The stream stopping: no new events for a while at an hour that is normally busy.
        lead = next((v for v in vs if v["additive"] and (v.get("unit") or "count") in ("count", "")), None)
        if lead and lag > STALL_MINUTES:
            days_map = P.by_day(hours.get(lead["metric"], {}))
            usual = P.median([days_map[d][local_now.hour] for d in days_map if d < today]) if days_map else 0
            if usual >= 20:
                stalled_products.append((pid, lag))

    # ── remember: moments that hold, resolve, and never repeat ──
    by_key = {v["key"]: v for v in vitals}
    weekday_word = weekday
    for ov in out_vitals:
        key = ov["key"]
        if ov.get("status") in (None, "stale", "error", "learning"):
            continue
        v = by_key[key]
        opened = mem["open"].get(key)
        if ov["status"] in ("normal", "early"):
            mem["streak"].pop(key, None)
            mem["calm"][key] = mem["calm"].get(key, 0) + 1
            if opened and mem["calm"][key] >= 2:
                prior = await db.get(AgentNote, opened["id"])
                if prior and prior.status == "open":
                    prior.status = "resolved"
                    db.add(_note(ws, utc, today, product_id=v["product_id"], watch_id=prior.watch_id, kind="moment",
                                 signal="recovered", importance=3, confidence=0.8, supersedes_id=prior.id,
                                 title=f"{v['label']} is back to normal",
                                 body=(f"Earlier I flagged {v['label'].lower()} as running {'above' if opened['dir'] == 'up' else 'below'} "
                                       f"a normal {weekday_word}. By {_clock(local_now)} it's back within the usual range "
                                       f"({ov.get('actual_display')} against {ov.get('expected_display')})."),
                                 facts={"vital": key, "label": v["label"], "resolves": str(prior.id),
                                        "pace": {k: ov.get(k) for k in ("actual", "expected", "actual_display", "expected_display")}}))
                    stats["resolved"] += 1
                mem["open"].pop(key, None)
            continue
        mem["calm"][key] = 0
        s = mem["streak"].get(key)
        n = s["n"] + 1 if s and s["dir"] == ov["direction"] else 1
        mem["streak"][key] = {"dir": ov["direction"], "n": n}
        pace_facts = {k: ov.get(k) for k in ("actual", "expected", "low", "high", "dev_pct", "projection", "expected_full",
                                             "basis", "actual_display", "expected_display", "low_display", "high_display",
                                             "projection_display", "expected_full_display", "share_done")}
        if opened and opened["dir"] == ov["direction"]:
            prior = await db.get(AgentNote, opened["id"])
            if prior and prior.status == "open":
                f = dict(prior.facts or {})
                f["latest"] = {**pace_facts, "local_time": _clock(local_now)}
                if abs(ov.get("dev_pct") or 0) > abs((f.get("peak") or f.get("pace") or {}).get("dev_pct") or 0):
                    f["peak"] = {**pace_facts, "local_time": _clock(local_now)}
                prior.facts = f
            continue
        if n < 2 and ov["strength"] != "strong":
            continue
        if opened:  # it turned the other way: the old moment is over
            prior = await db.get(AgentNote, opened["id"])
            if prior and prior.status == "open":
                prior.status = "resolved"
        pid = v["product_id"]
        where = []
        if v["additive"] and v.get("slices"):
            where = await where_today(db, clocks[pid][0], v, today, ts(ov["cut"]) or local_now, ov["actual"], ov["expected"])
            stats["queries"] += 2 * len(v["slices"][:2])
        facts = {"vital": key, "label": v["label"], "product": v["product"], "metric": v["metric"], "signal": f"pace_{ov['status']}",
                 "status": ov["status"], "direction": ov["direction"], "valence": ov["valence"], "strength": ov["strength"],
                 "weekday": weekday_word, "local_time": _clock(local_now), "day": today.isoformat(),
                 "pace": pace_facts, "where": where, "good_direction": v["good_direction"],
                 "curve": ov.get("curve")}
        title, body = moment_plain(v, facts, weekday_word)
        bad = ov["valence"] == "bad"
        note = _note(ws, utc, today, product_id=pid, watch_id=await _watch_id(db, pid, v["metric"]), kind="moment",
                     signal=facts["signal"], title=title, body=body, facts=facts,
                     importance=min(10, 5 + (2 if bad else 0) + (2 if ov["strength"] == "strong" else 0)),
                     confidence=0.85 if ov["strength"] == "strong" else 0.7)
        db.add(note)
        await db.flush()
        mem["open"][key] = {"id": str(note.id), "dir": ov["direction"]}
        new_moments.append((note, facts, v))
        stats["moments"] += 1

    # A sharp break in the last full hour (not already part of an open moment).
    for ov in out_vitals:
        h, key = ov.get("hour"), ov["key"]
        if not h or key in mem["open"] or f"{key}@{h['hour']}" in mem["hours"]:
            continue
        v = by_key[key]
        big_enough = h["expected"] >= 20 or not (v.get("unit") or "count") in ("count", "")
        if abs(h["z"]) >= 3.5 and abs(h.get("dev_pct") or 0) >= 25 and big_enough and h["expected"] > 0:
            mem["hours"].append(f"{key}@{h['hour']}")
            direction = "up" if h["z"] > 0 else "down"
            val = "neutral" if v["good_direction"] == "neutral" else ("good" if (direction == "up") == (v["good_direction"] == "up") else "bad")
            facts = {"vital": key, "label": v["label"], "product": v["product"], "metric": v["metric"], "signal": "hour_break",
                     "direction": direction, "valence": val, "weekday": weekday_word, "local_time": _clock(local_now),
                     "day": today.isoformat(), "hour": {k: h.get(k) for k in ("hour", "actual", "expected", "dev_pct",
                                                                               "actual_display", "expected_display")},
                     "pace": {"basis": ov.get("basis")}, "where": []}
            title, body = moment_plain(v, facts, weekday_word)
            note = _note(ws, utc, today, product_id=v["product_id"], watch_id=await _watch_id(db, v["product_id"], v["metric"]),
                         kind="moment", signal="hour_break", title=title, body=body, facts=facts,
                         importance=6 if val == "bad" else 4, confidence=0.6)
            db.add(note)
            new_moments.append((note, facts, v))
            stats["moments"] += 1

    # The stream stopping, and starting again.
    stalled_ids = {pid for pid, _ in stalled_products}
    for pid, lag in stalled_products:
        if pid not in mem["stall"]:
            p = products[pid]
            note = _note(ws, utc, today, product_id=pid, kind="data_issue", signal="stalled", importance=8, confidence=0.9,
                         title=f"{p.name}: no new data for {lag:.0f} minutes",
                         body=(f"The newest event behind {p.name} is {lag:.0f} minutes old, at an hour that is normally busy. "
                               "Either the business has gone quiet or the stream feeding it has stopped — the pipeline is "
                               "worth a look. I'm reading today's numbers up to now, so they will look low until it catches up."),
                         facts={"product": p.name, "lag_minutes": round(lag, 1)})
            db.add(note)
            await db.flush()
            mem["stall"][pid] = str(note.id)
    for pid in list(mem["stall"]):
        if pid not in stalled_ids:
            prior = await db.get(AgentNote, mem["stall"].pop(pid))
            if prior and prior.status == "open":
                prior.status = "resolved"
                # Told the stream stopped, the owner is waiting to hear it's back ("I say when a data stream stops or
                # comes back"): worth raising on a call and in a voice note. Never told, it's only worth a mention.
                db.add(_note(ws, utc, today, product_id=pid, kind="data_issue", signal="flowing",
                             importance=RECOVERED_TOLD if prior.seen else 3, confidence=0.9,
                             supersedes_id=prior.id, title=f"{products[pid].name}: data is flowing again",
                             body="New events are arriving again; today's numbers are catching up.",
                             facts={"resolves": str(prior.id)}))

    # Words for the new moments.
    if new_moments:
        written = await narrate_moments([f for _, f, _ in new_moments])
        for i, (note, _f, _v) in enumerate(new_moments):
            if i in written:
                note.title, note.body = written[i]
                note.facts = {**(note.facts or {}), "written_by": "llm (numbers checked)"}

    # Once a day, after midnight: how yesterday closed.
    if live and mem.get("last_close") != today.isoformat():
        await daily_briefing(db, ws, groups, clocks, hourly_cache, today, utc, stats)
        mem["last_close"] = today.isoformat()

    # ── the snapshot and the headline ──
    lag_all = round((local_now - newest).total_seconds() / 60, 1) if live else None
    snapshot = {
        "as_of": utc.isoformat(), "live": live, "local_time": _clock(local_now) if local_now else None,
        "local_now": local_now.isoformat(sep=" ") if local_now else None, "weekday": weekday,
        "today": today.isoformat() if today else None, "offset_minutes": offset, "tz_source": st.tz_source,
        "data_now": newest.isoformat(sep=" ") if newest else None, "lag_minutes": lag_all,
        "stalled": bool(stalled_products), "vitals": out_vitals,
        "reason": None if live else ("no_offset" if offset is None and newest else "stale"),
    }
    if not live:
        last = newest.strftime("%d %b %Y") if newest else "unknown"
        st.headline = (f"Nothing here is live: the newest event in the data is from {last}. I'll keep reading it as history "
                       "and keep looking in, so I'll notice when it comes back.")
        st.headline_at = utc
    else:
        facts = {"local_time": snapshot["local_time"], "weekday": weekday, "lag_minutes": lag_all,
                 "stalled": snapshot["stalled"],
                 "vitals": [{k: v.get(k) for k in ("label", "status", "valence", "strength", "dev_pct", "actual_display",
                                                   "expected_display", "projection_display", "expected_full_display", "basis")}
                            for v in out_vitals if v.get("status") not in ("stale", "error")],
                 "open_moments": [n.title for n in (await db.execute(select(AgentNote).where(
                     AgentNote.workspace_id == ws.id, AgentNote.kind.in_(("moment", "data_issue")),
                     AgentNote.status == "open", AgentNote.period == today))).scalars().all()][:6]}
        judged = [v for v in out_vitals if v.get("status") in ("above", "below", "normal", "early")]
        too_early = bool(judged) and all(v["status"] in ("early", "normal") for v in judged) and             any(v["status"] == "early" for v in judged if v.get("additive"))
        st.headline = plain_headline(snapshot, weekday) if too_early else             (await write_headline(facts) or plain_headline(snapshot, weekday))
        st.headline_at = utc
    snapshot["headline"] = st.headline
    st.snapshot = json.loads(json.dumps(snapshot, default=str))
    st.memory = json.loads(json.dumps(mem, default=str))
    st.live, st.last_pulse_at, st.error = live, utc, None
    db.add(CompanionPulse(workspace_id=ws.id, as_of=utc, headline=st.headline, summary={
        "live": live, "lag_minutes": lag_all, "local_time": snapshot["local_time"],
        "vitals": [{k: v.get(k) for k in ("key", "label", "status", "valence", "dev_pct", "actual", "expected", "actual_display")}
                   for v in out_vitals]}))
    await db.execute(delete(CompanionPulse).where(CompanionPulse.workspace_id == ws.id, CompanionPulse.as_of < utc - KEEP_PULSES))
    return stats


async def daily_briefing(db: AsyncSession, ws: Workspace, groups, clocks, hourly_cache, today: date, utc: datetime,
                         stats: Dict[str, Any]) -> None:
    """How yesterday closed against a normal day of its kind, what stood out, and what I'm watching today."""
    from pydantic import BaseModel

    yesterday = today - timedelta(days=1)
    closes = []
    for pid, vs in groups.items():
        model = clocks[pid][0]
        rates = [v["metric"] for v in vs if not v["additive"]]
        rate_daily = await daily(db, model, rates, datetime.combine(today - timedelta(days=7 * P.WEEKS + 1), time.min),
                                 datetime.combine(today, time.min) - timedelta(seconds=1)) if rates else {}
        for v in vs:
            c = P.close_additive(hourly_cache.get(pid, {}).get(v["metric"], {}), yesterday) if v["additive"] else \
                P.close_rate(rate_daily.get(v["metric"], {}), yesterday)
            if c:
                verdict = P.judge({**c, "kind": "rate"}, v["good_direction"])
                closes.append({"label": v["label"], "product": v["product"], **c, **verdict,
                               "actual_display": show(c["actual"], v.get("unit"), v["metric"]),
                               "expected_display": show(c["expected"], v.get("unit"), v["metric"])})
    if not closes:
        return
    moments = (await db.execute(select(AgentNote).where(
        AgentNote.workspace_id == ws.id, AgentNote.kind == "moment", AgentNote.period == yesterday))).scalars().all()
    facts = {"day": yesterday.isoformat(), "day_display": yesterday.strftime("%A %d %b"), "closes": closes,
             "moments_yesterday": [m.title for m in moments][:8]}

    class Out(BaseModel):
        title: str
        body: str

    out = await _llm_json(
        VOICE + " Write the morning briefing about how yesterday closed: a short title (e.g. 'Thursday closed 8.9% "
        "above normal'), then 3-5 sentences — the headline number against a normal day of its kind, what stood out "
        "(good and bad), anything that happened during the day, and what you'll keep an eye on today. A close whose "
        "status is 'normal' was within its usual range: say so, don't call it good or bad.", facts, Out)
    if out and sane(out.title, 3) and sane(out.body, 12) and numbers_check(out.title + " " + out.body, facts):
        title, body = out.title, out.body
    else:
        lead = closes[0]
        title = f"{facts['day_display']}: {lead['label'].lower()} closed at {lead['actual_display']}"
        parts = [f"{c['label']} {c['actual_display']} against a usual {c['expected_display']}"
                 + (f" ({c['dev_pct']:+.1f}%)" if c.get("dev_pct") is not None else "") for c in closes]
        body = f"How {facts['day_display']} closed, against {lead['basis']}: " + "; ".join(parts) + "."
    db.add(AgentNote(workspace_id=ws.id, mode="live", kind="daily_briefing", signal="day_close", title=title[:500], body=body,
                     facts={**facts, **({"written_by": "llm (numbers checked)"} if out else {})}, period=yesterday,
                     as_of=utc, importance=6, confidence=0.85, status="open"))
    stats["briefing"] = True


async def pace_for(db: AsyncSession, p: DataProduct, metric: str, st: CompanionState,
                   dimension: Optional[str] = None, at_hours: Optional[List[int]] = None) -> Dict[str, Any]:
    """On demand (for a question): one metric today-so-far against normal days at this minute, where a gap sits by
    a dimension, and — asked for particular hours, or broken down by the event clock — each hour of today against
    the same hour on normal days."""
    from kairos_kb.companion.vitals import event_column

    ev = await event_column(db, p)
    if not ev:
        return {"error": f"{p.name} does not record when each event happened, so it can't be read live."}
    model = live_model(p, {"table": ev[0], "column": ev[1]})
    m = next((x for x in model.get("metrics") or [] if x["name"].lower() == metric.lower()), None)
    if m is None:
        return {"error": f"No metric '{metric}' on {p.name}.", "metrics": [x["name"] for x in model.get("metrics") or []]}
    if st.tz_offset_minutes is None:
        return {"error": "I don't know this business's clock yet (no live data seen)."}
    local_now = datetime.utcnow() + timedelta(minutes=st.tz_offset_minutes)
    dnow = await data_clock(db, model, m["name"])
    if not dnow or local_now - dnow > LIVE_WINDOW:
        return {"error": f"{p.name} is not live: the newest event is {dnow.isoformat(sep=' ') if dnow else 'unknown'}."}
    today = local_now.date()
    cut = dnow if (local_now - dnow).total_seconds() / 60 <= STALL_MINUTES and dnow.date() == today else local_now
    hours, err = await hourly(db, model, [m["name"]], datetime.combine(today - timedelta(days=7 * P.WEEKS), time.min), cut)
    if err:
        return {"error": err}
    v = {"metric": m["name"], "label": m.get("label") or m["name"], "unit": m.get("unit") or "", "additive": bool(m.get("additive")),
         "slices": [dimension] if dimension else []}
    if v["additive"]:
        pc = P.pace_additive(hours.get(m["name"], {}), today, cut, count_like=v["unit"] in ("count", ""))
    else:
        actual = (await values_until(db, model, [m["name"]], datetime.combine(today, time.min), cut))[m["name"]]
        days, _ = P.baseline_days(today, [t.date() for t in hours.get(m["name"], {}) if t.date() < today])
        base = {}
        for d in days:
            val = (await values_until(db, model, [m["name"]], datetime.combine(d, time.min), datetime.combine(d, cut.time())))[m["name"]]
            if val is not None:
                base[d] = val
        pc = P.pace_rate(actual, base, hours.get(m["name"], {}), today, cut)
    if pc is None:
        return {"error": "Not enough history at this hour to say what normal is."}
    curve = pc.pop("curve", None)
    pc.update(_displays(v, pc))
    out = {"product": p.name, "metric": m["name"], "label": v["label"], "as_of": _clock(cut), "weekday": today.strftime("%A"),
           **{k: (round(val, 4) if isinstance(val, float) else val) for k, val in pc.items() if k not in ("days",)}}
    if curve:
        out["_curve"] = curve  # for a chart on Jenny's stage (private: not shown to the model)
    # Broken down by a time dimension, "where" would compare dated hours with themselves (always "usual 0"):
    # what's meant is each hour of today against the same hour on normal days.
    by_time = bool(dimension) and dimension.split(":")[0].lower() in {
        d["name"].lower() for d in model.get("dimensions") or [] if d.get("type") == "time"}
    if at_hours or by_time:
        if not v["additive"]:
            out["by_hour_note"] = "An hour-by-hour comparison of a rate isn't computed here; query it by event_time:hour."
        else:
            hv = P.hours_vs_normal(hours.get(m["name"], {}), today, cut, at_hours or None)
            if hv:
                for r in hv["hours"]:
                    r.update({f"{k}_display": show(r[k], v["unit"], v["metric"]) for k in ("actual", "expected", "low", "high")})
                    r["gap_display"] = ("+" if r["gap"] >= 0 else "−") + show(abs(r["gap"]), v["unit"], v["metric"])
                out["by_hour"] = hv
    elif dimension and v["additive"]:
        out["where"] = await where_today(db, model, v, today, cut, pc["actual"], pc["expected"])
    elif dimension:
        out["where"] = [await rate_where(db, model, v, dimension, today, cut)]
    return out


async def rate_where(db: AsyncSession, model: Dict[str, Any], v: Dict[str, Any], dimension: str, today: date,
                     cut: datetime) -> Dict[str, Any]:
    """For a rate (a cancellation rate, say): each slice today so far against its own usual over the last four weeks,
    ranked by what the difference amounts to at today's volume — a town with one cancelled order out of one isn't
    the story; a city with forty more cancellations than usual is. (The gap split by slice only works for numbers
    that add up; a rate is compared slice by slice.)"""
    dim = dimension.split(":")[0]
    metric = next((m for m in model.get("metrics") or [] if m["name"] == v["metric"]), {})
    # The volume behind the rate: a plain count on the same table (orders, for a cancellation rate).
    volume = next((m for m in model.get("metrics") or [] if m.get("additive") and m.get("unit") == "count"
                   and m.get("base_table") == metric.get("base_table")
                   and str(m.get("expression") or "").upper().startswith("COUNT(")), None)
    names = [v["metric"]] + ([volume["name"]] if volume else [])
    fmt = "%Y-%m-%d %H:%M:%S"
    start = datetime.combine(today, time.min)
    now_w = [{"dimension": EVENT_DIM, "op": "between", "value": [start.strftime(fmt), cut.strftime(fmt)]}]
    past_w = [{"dimension": EVENT_DIM, "op": "between",
               "value": [(start - timedelta(days=28)).strftime(fmt), (start - timedelta(seconds=1)).strftime(fmt)]}]
    today_r = await run(db, model, names, [dim], now_w, "", 1000)
    if today_r.get("error"):
        return {"dimension": dim, "error": today_r["error"]}
    past_r = await run(db, model, [v["metric"]], [dim], past_w, "", 2000)
    usual = {str(r[0]): num(r[1]) for r in past_r.get("rows") or []}
    ratio = (v.get("unit") or "") in ("ratio", "")
    rows = []
    for r in today_r.get("rows") or []:
        name, now_v = str(r[0]), num(r[1])
        vol = num(r[2]) if volume and len(r) > 2 else None
        was = usual.get(name)
        if now_v is None or was is None:
            continue
        extra = (now_v - was) * vol if (ratio and vol) else None  # e.g. cancellations more than its usual rate gives
        row = {"slice": name, "today_display": show(now_v, v["unit"], v["metric"]), "usual_display": show(was, v["unit"], v["metric"]),
               "change_pct": P.pct(now_v, was), "_rank": abs(extra) if extra is not None else abs(now_v - was) * (vol or 1),
               "_today": now_v, "_usual": was, "_volume": vol}
        if vol is not None:
            row["volume_display"] = f"{int(vol):,} {(volume.get('label') or volume['name']).lower()}"
        if extra is not None:
            row["extra_display"] = f"{'+' if extra >= 0 else '-'}{abs(extra):.0f} vs its usual rate"
        rows.append(row)
    rows.sort(key=lambda x: -x["_rank"])
    for row in rows:
        row.pop("_rank", None)
    return {"dimension": dim, "slices_compared": len(rows), "top": rows[:8],
            "basis": ("today so far against each slice's own rate over the last 4 weeks, ranked by what the difference "
                      "amounts to at today's volume")}


def interval_for(st: CompanionState) -> int:
    return st.interval_seconds if st.live or st.last_pulse_at is None else max(st.interval_seconds, NOT_LIVE_INTERVAL)
