"""What the living agent watches, and how it reads each series.

The watch list is derived from the data products: each product already defines its
metrics once, with a time dimension and the slices to explain by. The LLM reads a
product and proposes, per metric, whether to watch it, which way is good, which
slices explain a change, and — the human part — how long recent values keep moving
before they settle ("claims adjudicate over about two months"), with its reason.
Code keeps only metrics and slices the product really has. A person can mute a
watch, flip its direction or change its threshold.

Reading a series: the time dimension is probed — a daily column is read at month
grain; a column that already holds months is read as it is — and values are parsed
into (period, value) points. The newest period is "partial" when the data does not
yet reach the end of it.
"""

from __future__ import annotations

import calendar
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.context.access import AgentIdentity
from kairos_kb.models.data_product import DataProduct
from kairos_kb.models.living import Watch

logger = logging.getLogger(__name__)

SYSTEM_IDENTITY = AgentIdentity(agent_id=None, name="living-agent", scopes=frozenset({"read", "query"}),
                                channel="living")


# ── proposing the watch list ─────────────────────────────────────────


class WatchPick(BaseModel):
    metric: str = Field(description="Metric name exactly as listed.")
    watch: bool = Field(description="True only for outcomes and drivers a business person tracks. False for "
                                    "model internals (residuals, predictions, probabilities, features, coefficients, "
                                    "baselines, log transforms), sample counts, technical or duplicate measures.")
    good_direction: str = Field(description="up when higher is better for the business, down when lower is "
                                            "better (cancellations, rejections, delays, returns), neutral otherwise.")
    slices: List[str] = Field(default_factory=list, description="Up to 2 dimensions, exactly as listed, that a "
                                                               "business person would explain a change by (city, "
                                                               "region, product, territory, channel). Never ids "
                                                               "of individual people, invoices or orders.")
    why: str = Field(description="One sentence: why this metric matters to the business.")


class ProductWatch(BaseModel):
    settle_periods: int = Field(description="How many recent months typically keep changing after first load "
                                            "before the numbers are final, judged from what the data is: e.g. "
                                            "claims adjudicate and arrive late (2), weekly Rx gets restated (1), "
                                            "operational order logs are final at once (0).")
    settle_reason: str = Field(description="One sentence explaining that judgment.")
    metrics: List[WatchPick]


WATCH_SYSTEM = """You are setting up a careful business analyst who will watch one data product
month by month and tell people when something genuinely changes. For each metric decide whether it
is worth watching, which way is good for the business, and which one or two dimensions would explain
a change. Then judge, from what the underlying data is (its tables and what they record), how many
recent months typically keep changing before they are final — as an experienced analyst in this
industry would know (pharma claims arrive late; syndicated Rx is restated; transactional logs are
final at once). Watch at most 8 metrics per product — the ones a business owner would ask about first;
leave model internals and statistical by-products unwatched. Use metric and dimension names exactly as given."""


def _product_brief(p: DataProduct) -> str:
    spec = p.spec or {}
    model = spec.get("model") or {}
    lines = [f"PRODUCT: {p.name} ({p.domain or '-'})", f"description: {p.description or '-'}",
             "INPUT TABLES: " + "; ".join(f"{i['table']} ({i.get('role')}): {i.get('why') or ''}"[:200]
                                          for i in spec.get("inputs") or []),
             "METRICS:"]
    for m in model.get("metrics") or []:
        lines.append(f"- {m['name']}: {m.get('label') or ''} — {m.get('description') or ''} "
                     f"({'additive' if m.get('additive') else 'not additive'})")
    lines.append("DIMENSIONS:")
    for d in model.get("dimensions") or []:
        lines.append(f"- {d['name']} ({d.get('type')}): {d.get('description') or ''}")
    return "\n".join(lines)


def _fallback_direction(name: str) -> str:
    if re.search(r"cancel|reject|denial|lapse|return|delay|time_min|churn|discount|gap|switch|cost|error", name, re.I):
        return "down"
    if re.search(r"order|sale|revenue|gmv|trx|nrx|claim|fill|start|call|rating|units|amount|share", name, re.I):
        return "up"
    return "neutral"


async def propose(p: DataProduct) -> ProductWatch:
    from kairos_kb.llm.provider import chat_model

    llm = chat_model()
    model = (p.spec or {}).get("model") or {}
    if llm is not None:
        try:
            return await llm.with_structured_output(ProductWatch).ainvoke(
                [("system", WATCH_SYSTEM), ("human", _product_brief(p))])
        except Exception:  # noqa: BLE001 — a plain watch list is better than none
            logger.exception("Watch proposal failed for %s; using defaults", p.name)
    return ProductWatch(settle_periods=1, settle_reason="No judgment available; waiting one month to be safe.",
                        metrics=[WatchPick(metric=m["name"], watch=True, good_direction=_fallback_direction(m["name"]),
                                           slices=[], why=m.get("description") or "")
                                 for m in model.get("metrics") or []])


def time_dimensions(p: DataProduct) -> List[str]:
    return [d["name"] for d in ((p.spec or {}).get("model") or {}).get("dimensions") or [] if d.get("type") == "time"]


async def derive(db: AsyncSession, p: DataProduct) -> List[Watch]:
    """Create (or refresh) the watches of one product. Person-made settings are kept."""
    model = (p.spec or {}).get("model") or {}
    metrics = {m["name"]: m for m in model.get("metrics") or []}
    dims = {d["name"]: d for d in model.get("dimensions") or []}
    times = time_dimensions(p)
    if not times:
        return []
    time_dim = await pick_time_dimension(db, p, times, next(iter(metrics), None))
    if not time_dim:
        return []
    plan = await propose(p)
    existing = {w.metric: w for w in (await db.execute(select(Watch).where(Watch.product_id == p.id))).scalars()}
    out = []
    from kairos_kb.products.semantic import QueryError, compile_query

    def readable_over_time(metric: str) -> bool:
        """Only metrics the product can serve month by month are worth watching."""
        try:
            compile_query(model, [metric], [time_dim])
            return True
        except QueryError:
            logger.info("Not watching %s.%s: it cannot be read over %s", p.name, metric, time_dim)
            return False

    picked = [x for x in plan.metrics if x.watch and x.metric in metrics and readable_over_time(x.metric)][:8]
    keep = {x.metric for x in picked}
    for metric, w in existing.items():
        if metric not in keep and w.origin != "person":
            await db.delete(w)  # no longer worth watching
    for pick in picked:
        m = metrics.get(pick.metric)
        slices = [s for s in pick.slices if s in dims and dims[s].get("type") != "time"][:2]
        w = existing.get(pick.metric)
        if w is None:
            w = Watch(workspace_id=p.workspace_id, product_id=p.id, metric=pick.metric)
            db.add(w)
        if w.origin != "person":
            w.good_direction = pick.good_direction if pick.good_direction in ("up", "down", "neutral") else "neutral"
            w.slices = slices
        w.label = m.get("label") or pick.metric
        w.time_dim, w.grain = time_dim, "month"
        w.settle_periods = max(0, min(int(plan.settle_periods), 6))
        w.settle_reason, w.why = plan.settle_reason, pick.why
        out.append(w)
    await db.flush()
    return out


# ── reading a series ─────────────────────────────────────────────────


def parse_date(v: Any) -> Optional[date]:
    if v is None:
        return None
    s = str(v)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        m = re.match(r"(\d{4})[-/ ]?(\d{2})", str(v))
        return date(int(m.group(1)), int(m.group(2)), 1) if m else None


def parse_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


async def _run(db: AsyncSession, p: DataProduct, metrics: List[str], by: List[str],
               filters: Optional[List[Dict[str, Any]]] = None, order: str = "", limit: int = 1000) -> Dict[str, Any]:
    from kairos_kb.products.service import query

    return await query(db, p, SYSTEM_IDENTITY, metrics=metrics, by=by, filters=filters, order=order, limit=limit)


async def pick_time_dimension(db: AsyncSession, p: DataProduct, times: List[str], metric: Optional[str]) -> Optional[str]:
    """The time dimension with the longest monthly history (some are labels, not dates)."""
    if not metric:
        return None
    best, best_n = None, 0
    for t in times:
        for by in (f"{t}:month", t):
            r = await _run(db, p, [metric], [by], limit=400)
            if r.get("error"):
                continue
            n = len({parse_date(row[0]) for row in r.get("rows") or [] if parse_date(row[0])})
            if n > best_n:
                best, best_n = by, n
            break
    return best


async def latest_day(db: AsyncSession, p: DataProduct, w: Watch) -> Optional[date]:
    """The newest date the data reaches on this watch's time column (for a partial-period check)."""
    base = w.time_dim.split(":")[0]
    r = await _run(db, p, [w.metric], [base], order=f"{base} desc", limit=1)
    rows = r.get("rows") or []
    return parse_date(rows[0][0]) if rows else None


async def read_series(db: AsyncSession, p: DataProduct, w: Watch, *, slice_dim: Optional[str] = None,
                      periods: Optional[Tuple[date, date]] = None) -> Tuple[Dict[str, List[Tuple[date, float]]], Dict[str, Any]]:
    """{slice value or "": [(period, value)]} oldest first, and the query's provenance."""
    by = [w.time_dim] + ([slice_dim] if slice_dim else [])
    filters = None
    if periods:
        base = w.time_dim.split(":")[0]
        filters = [{"dimension": base, "op": "between",
                    "value": [periods[0].isoformat(), month_end(periods[1]).isoformat()]}]
    r = await _run(db, p, [w.metric], by, filters=filters, limit=5000 if slice_dim else 1000)
    if r.get("error"):
        raise ValueError(r["error"])
    out: Dict[str, List[Tuple[date, float]]] = {}
    for row in r.get("rows") or []:
        d, v = parse_date(row[0]), parse_float(row[-1])
        if d is None or v is None:
            continue
        key = "" if not slice_dim else str(row[1])
        out.setdefault(key, []).append((date(d.year, d.month, 1), v))
    for k in out:
        merged: Dict[date, float] = {}
        for d, v in out[k]:
            merged[d] = merged.get(d, 0.0) + v
        out[k] = sorted(merged.items())
    return out, {"sql": r.get("sql"), "source": r.get("source"), "table": r.get("table")}


def is_partial(period: date, data_until: Optional[date]) -> bool:
    """The data does not yet reach the end of this period."""
    return bool(data_until) and data_until < month_end(period) - timedelta(days=1)


def now() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)
