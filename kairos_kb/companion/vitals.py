"""What the companion keeps its eye on during the day, and the clock those events run on.

Vitals: the few numbers a business owner glances at all day — volume, money, and the one or
two rates that signal trouble. The LLM picks them from the living agent's watch list (which
already knows what matters and which way is good); code keeps only metrics that can be read
hour by hour.

The event clock: a data product's time dimension is usually a date, which cannot say how the
day is going. Its base table often also records *when* each event happened (ORDER_TIMESTAMP
next to ORDER_DATE). The companion finds that timestamp in the catalog and reads the product
through it — hour by hour, up to this minute — on a copy of the product's model, so the
product itself is unchanged.
"""

from __future__ import annotations

import copy
import logging
import re
from collections import Counter
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.context.access import AgentIdentity
from kairos_kb.models.column import Column
from kairos_kb.models.data_product import DataProduct
from kairos_kb.models.living import Watch
from kairos_kb.models.table import Table

logger = logging.getLogger(__name__)

IDENTITY = AgentIdentity(agent_id=None, name="companion", scopes=frozenset({"read", "query"}), channel="companion")
EVENT_DIM = "event_time"
MAX_VITALS = 6

_TS = re.compile(r"TIMESTAMP|DATETIME", re.I)
_LATE = re.compile(r"UPDATED|MODIFIED|LOADED|INGEST|_ETL|_DBT|SYNCED|INSERTED", re.I)


# ── the event clock ──────────────────────────────────────────────────


def base_table(p: DataProduct) -> Optional[str]:
    metrics = ((p.spec or {}).get("model") or {}).get("metrics") or []
    counts = Counter(m.get("base_table") for m in metrics if m.get("base_table"))
    return counts.most_common(1)[0][0] if counts else None


async def event_column(db: AsyncSession, p: DataProduct) -> Optional[Tuple[str, str]]:
    """(base table, timestamp column) the product's events happen at, or None when it has none."""
    base = base_table(p)
    if not base:
        return None
    rows = (await db.execute(
        select(Column.name, Column.data_type).join(Table, Table.id == Column.table_id)
        .where(Table.workspace_id == p.workspace_id, func.upper(Table.full_name) == base.upper())
        .order_by(Column.ordinal_position))).all()
    stamps = [name for name, kind in rows if _TS.search(kind or "")]
    if not stamps:
        return None
    # The timestamp that goes with the product's date (ORDER_DATE -> ORDER_TIMESTAMP) first; load
    # times (updated_at, loaded_at) last: they say when a row arrived, not when the business event was.
    hints = set()
    for d in ((p.spec or {}).get("model") or {}).get("dimensions") or []:
        if d.get("type") == "time":
            for col in [d.get("column")] + [j.get("from_column") for j in d.get("joins") or []]:
                if col:
                    hints.add(re.split(r"[_ ]", col.upper())[0])

    def score(c: str) -> int:
        s = 3 if re.split(r"[_ ]", c.upper())[0] in hints else 0
        s += 1 if re.search(r"CREATED|EVENT|PLACED|OCCURRED|ORDER|TIMESTAMP", c, re.I) else 0
        s -= 4 if _LATE.search(c) else 0
        return s

    return base, max(stamps, key=score)


def live_model(p: DataProduct, event: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """The product's model with the event clock added as a time dimension (a copy; the product is unchanged)."""
    model = copy.deepcopy((p.spec or {}).get("model") or {})
    if event and not any(d["name"].lower() == EVENT_DIM for d in model.get("dimensions") or []):
        model.setdefault("dimensions", []).append({
            "name": EVENT_DIM, "type": "time", "table": event["table"], "column": event["column"],
            "label": "Event time", "joins": [], "also_in": [],
            "description": f"When the event happened ({event['column']}), read to the minute for live pacing."})
    return model


async def run(db: AsyncSession, model: Dict[str, Any], metrics: List[str], by: Optional[List[str]] = None,
              filters: Optional[List[Dict[str, Any]]] = None, order: str = "", limit: int = 5000) -> Dict[str, Any]:
    """A product query on a (live) model, through the same read-only SQL guard every agent uses."""
    from kairos_kb.context.query import run_sql
    from kairos_kb.products.semantic import QueryError, compile_query

    try:
        compiled = compile_query(model, metrics, by, filters, order)
    except QueryError as exc:
        return {"error": str(exc)}
    out = await run_sql(db, IDENTITY, compiled["sql"], limit)
    return {**out, "sql": compiled["sql"], "table": compiled["table"]}


def ts(v: Any) -> Optional[datetime]:
    """A timestamp from a query cell (string or datetime), naive, in the data's own clock."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    s = str(v).strip().replace("T", " ")
    s = re.sub(r"(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$", "", s)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


# ── choosing the vitals ──────────────────────────────────────────────


class VitalPick(BaseModel):
    product: str = Field(description="Product name exactly as listed.")
    metric: str = Field(description="Metric name exactly as listed.")
    why: str = Field(description="One short sentence: what this number tells the owner during the day.")


class VitalPlan(BaseModel):
    vitals: List[VitalPick]


VITALS_SYSTEM = f"""You are setting up the live dashboard of a business companion who watches the business
during the day, like a chief of staff glancing at the numbers. From the candidate metrics, choose at most
{MAX_VITALS} vitals the owner would want to see move hour by hour: the core volume, the money, and the one or
two rates or times that signal trouble early (cancellations, delays, failures). Prefer metrics that change
within a day. Do not pick two that say the same thing (orders and delivered orders; revenue and sales amount),
sample counts, or slow-moving judgments (ratings that arrive days later). Use names exactly as given."""


def _fallback_rank(c: Dict[str, Any]) -> int:
    name = c["metric"].lower()
    for i, pat in enumerate((r"^orders?$|transactions|bookings", r"gmv|revenue|net_sales", r"cancel|reject|fail",
                             r"aov|basket|avg_order", r"deliver.*time|delay|latency", r"discount")):
        if re.search(pat, name):
            return i
    return 99


async def choose(db: AsyncSession, workspace_id) -> List[Dict[str, Any]]:
    """The vitals for a connection: candidates from the watch list on products with an event clock."""
    from kairos_kb.llm.provider import chat_model
    from kairos_kb.products.semantic import QueryError, compile_query

    products = {p.id: p for p in (await db.execute(
        select(DataProduct).where(DataProduct.workspace_id == workspace_id))).scalars()}
    events: Dict[Any, Optional[Dict[str, str]]] = {}
    for pid, p in products.items():
        ev = await event_column(db, p)
        events[pid] = {"table": ev[0], "column": ev[1]} if ev else None
    watches = (await db.execute(select(Watch).where(Watch.workspace_id == workspace_id, Watch.status == "active")
                                .order_by(Watch.product_id, Watch.metric))).scalars().all()
    candidates = []
    for w in watches:
        p, ev = products.get(w.product_id), events.get(w.product_id)
        if not p or not ev:
            continue
        model = live_model(p, ev)
        try:
            compile_query(model, [w.metric], [f"{EVENT_DIM}:hour"])
        except QueryError:
            continue
        m = next((m for m in model.get("metrics") or [] if m["name"] == w.metric), {})
        dims = {d["name"]: d for d in model.get("dimensions") or []}
        candidates.append({
            "key": f"{p.slug}.{w.metric}", "product_id": str(p.id), "product": p.name, "metric": w.metric,
            "label": w.label or m.get("label") or w.metric, "good_direction": w.good_direction,
            "additive": bool(m.get("additive")), "unit": m.get("unit") or "",
            "slices": [s for s in (w.slices or []) if dims.get(s, {}).get("type") == "categorical"][:2],
            "event": ev, "why": w.why or m.get("description") or "", "description": m.get("description") or ""})
    if not candidates:
        return []
    picked: List[Dict[str, Any]] = []
    llm = chat_model()
    if llm is not None and len(candidates) > MAX_VITALS:
        brief = "\n".join(f"- product: {c['product']} | metric: {c['metric']} | {c['label']} | "
                          f"{'additive' if c['additive'] else 'rate/average'} | better: {c['good_direction']} | "
                          f"{c['description'][:140]}" for c in candidates)
        try:
            plan = await llm.with_structured_output(VitalPlan).ainvoke(
                [("system", VITALS_SYSTEM), ("human", "CANDIDATES:\n" + brief)])
            by_key = {(c["product"].lower(), c["metric"].lower()): c for c in candidates}
            for v in plan.vitals:
                c = by_key.get((v.product.lower(), v.metric.lower()))
                if c and c not in picked:
                    picked.append({**c, "why": v.why or c["why"]})
        except Exception:  # noqa: BLE001 — the plain ranking stands in
            logger.exception("Vital selection failed; ranking by name")
    if not picked:
        picked = sorted(candidates, key=_fallback_rank)
    return [{k: v for k, v in c.items() if k != "description"} for c in picked[:MAX_VITALS]]
