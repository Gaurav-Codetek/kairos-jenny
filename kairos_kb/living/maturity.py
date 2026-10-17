"""How long a metric's recent periods keep moving: measured, once the agent has looked enough times.

Every look stores each period's value as it stood then. For a period seen at several
looks, the value at each age (months between the period and the look) is compared
with its latest value. The settle age is the youngest age from which revisions stay
under one percent. Until enough looks exist, the watch's prior (the LLM's industry
judgment, e.g. "claims settle over two months") stands, and says so.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.models.living import MetricObservation, Watch

SETTLED_REVISION_PCT = 1.0
MIN_EVIDENCE = 3  # periods seen at two or more ages
SAME_LOAD_HOURS = 20  # looks closer than this saw the same load: they are one look


def _age(period: date, as_of: date) -> int:
    return (as_of.year - period.year) * 12 + as_of.month - period.month


async def maturity(db: AsyncSession, w: Watch) -> Dict[str, Any]:
    rows = (await db.execute(select(MetricObservation).where(
        MetricObservation.watch_id == w.id, MetricObservation.slice == "", MetricObservation.run_id.is_(None))
        .order_by(MetricObservation.period, MetricObservation.as_of))).scalars().all()
    # Collapse looks taken within the same load window: keep the latest of each window.
    stamps = sorted({r.as_of for r in rows})
    keep, last = set(), None
    for t in reversed(stamps):
        if last is None or (last - t).total_seconds() > SAME_LOAD_HOURS * 3600:
            keep.add(t)
            last = t
    rows = [r for r in rows if r.as_of in keep]
    by_period: Dict[date, List[MetricObservation]] = defaultdict(list)
    for r in rows:
        by_period[r.period].append(r)
    looks = len(keep)
    revisions: Dict[int, List[float]] = defaultdict(list)
    evidence = 0
    for period, obs in by_period.items():
        final = obs[-1].value
        if len(obs) < 2 or not final:
            continue
        evidence += 1
        for o in obs[:-1]:
            if o.value is not None:
                revisions[_age(period, o.as_of.date())].append(abs(final - o.value) / abs(final) * 100)
    curve = [{"age": a, "mean_revision_pct": round(sum(v) / len(v), 2), "samples": len(v)}
             for a, v in sorted(revisions.items())]
    if evidence < MIN_EVIDENCE:
        return {"measured": False, "settle_periods": w.settle_periods, "reason": w.settle_reason,
                "looks": looks, "evidence": evidence, "curve": curve}
    settle = 0
    for point in curve:
        if point["mean_revision_pct"] >= SETTLED_REVISION_PCT:
            settle = point["age"] + 1
    return {"measured": True, "settle_periods": settle, "prior": w.settle_periods, "looks": looks,
            "evidence": evidence, "curve": curve,
            "reason": f"Measured over {evidence} periods seen at more than one look: values stop moving "
                      f"(under {SETTLED_REVISION_PCT:g}%) after {settle} month(s)."}
