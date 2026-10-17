"""A data product's contracts: what it promises, checked against the map and the platform.

Derived by code from the semantic model and the inputs, never written by the LLM:

  schema       every column the model depends on still exists on its input table
  grain        an input's enrichment grain check still holds
  pipeline     the pipelines writing an input last succeeded
  freshness    when each input last changed (a promise only once a person sets an SLO)
  metric       each metric compiles on the platform (live check)
  reconcile    a metric's mart shortcut agrees with its base computation (live check)

Map checks are cheap and run whenever the product is read; live checks run on
the platform when asked. Product health: broken (a schema or metric contract is
broken), degraded (anything else breached), healthy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.models.column import Column
from kairos_kb.models.table import Table
from kairos_kb.products.semantic import columns_used

BREAKING = {"schema", "metric"}


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


async def map_checks(db: AsyncSession, inputs: List[Dict[str, Any]], model: Dict[str, Any],
                     pipelines: List[Dict[str, Any]], freshness_slo_hours: Optional[float]) -> List[Dict[str, Any]]:
    """Contracts checked against what Kairos holds — no platform call."""
    out: List[Dict[str, Any]] = []
    used = columns_used(model)
    now = datetime.now(timezone.utc)
    for port in inputs:
        table = (await db.execute(select(Table).where(Table.entity_id == port["entity_id"]))).scalars().first()
        if table is None:
            out.append({"contract": "schema", "port": port["full_name"], "status": "broken",
                        "detail": "the table is no longer in the map"})
            continue
        need = used.get(port["full_name"].upper(), set())
        if need:
            have = {c.name.upper() for c in (await db.execute(
                select(Column).where(Column.table_id == table.id))).scalars()}
            missing = sorted(need - have)
            out.append({"contract": "schema", "port": port["full_name"], "status": "broken" if missing else "ok",
                        "detail": (f"missing {', '.join(missing)}" if missing
                                   else f"{len(need)} column(s) the product depends on are present"),
                        "columns": sorted(need)})
        grain = next((c for c in port.get("checks") or [] if c.get("check") == "grain"), None)
        if grain and grain.get("result") in ("holds", "fails"):
            out.append({"contract": "grain", "port": port["full_name"],
                        "status": "ok" if grain["result"] == "holds" else "breached",
                        "detail": grain.get("detail")})
        stamp = _parse_ts((port.get("freshness") or {}).get("last_altered"))
        if stamp:
            age_h = (now - stamp).total_seconds() / 3600
            status = "info" if not freshness_slo_hours else ("ok" if age_h <= freshness_slo_hours else "breached")
            out.append({"contract": "freshness", "port": port["full_name"], "status": status,
                        "detail": f"last changed {age_h:,.0f} h ago"
                                  + (f" (SLO {freshness_slo_hours:g} h)" if freshness_slo_hours else " · no SLO set"),
                        "age_hours": round(age_h, 1)})
    for p in pipelines:
        runs = p.get("runs") or {}
        if not runs:
            continue
        failing = runs.get("last_state") not in (None, "SUCCESS")
        out.append({"contract": "pipeline", "port": p["name"], "status": "breached" if failing else "ok",
                    "detail": (f"last run {runs.get('last_state')}" if failing
                               else f"{runs.get('succeeded')}/{runs.get('recent')} recent runs succeeded")})
    return out


async def live_checks(model: Dict[str, Any], connector) -> List[Dict[str, Any]]:
    """Contracts checked on the platform: every metric compiles; shortcuts agree with the base."""
    out: List[Dict[str, Any]] = []

    async def run(sql: str):
        result = await connector.execute_query(sql, row_limit=5)
        status = (result or {}).get("status") or {}
        if status.get("state") not in (None, "SUCCEEDED"):
            raise RuntimeError(str(((status.get("error") or {}).get("message")) or status.get("state")))
        from kairos_kb.connectors.databricks import DatabricksConnector

        return DatabricksConnector._rows_from_statement_result(result)

    for m in model.get("metrics") or []:
        try:
            base = await run(f"SELECT {m['expression']} AS v FROM {m['base_table']} f")
            base_v = next(iter(base[0].values())) if base else None
            out.append({"contract": "metric", "port": m["name"], "status": "ok",
                        "detail": f"computes on {m['base_table'].split('.')[-1]}: {base_v}"})
        except Exception as exc:  # noqa: BLE001
            out.append({"contract": "metric", "port": m["name"], "status": "broken", "detail": str(exc)[:240]})
            continue
        for s in m.get("shortcuts") or []:
            if s.get("rollup") != "sum" or not m.get("additive"):
                continue
            try:
                rows = await run(f"SELECT SUM(t.{s['column']}) AS v FROM {s['table']} t")
                short_v = next(iter(rows[0].values())) if rows else None
                b, sv = float(base_v or 0), float(short_v or 0)
                diff = abs(b - sv) / max(abs(b), 1e-9) if b else abs(sv)
                out.append({"contract": "reconcile", "port": f"{m['name']} · {s['table'].split('.')[-1]}",
                            "status": "ok" if diff <= 0.005 else "breached",
                            "detail": (f"mart total {sv:,.2f} matches the base computation" if diff <= 0.005
                                       else f"mart total {sv:,.2f} vs base {b:,.2f} ({diff:.1%} apart)")})
            except Exception as exc:  # noqa: BLE001
                out.append({"contract": "reconcile", "port": f"{m['name']} · {s['table'].split('.')[-1]}",
                            "status": "error", "detail": str(exc)[:240]})
    return out


def health(contracts: List[Dict[str, Any]]) -> Dict[str, Any]:
    broken = [c for c in contracts if c["status"] == "broken" and c["contract"] in BREAKING]
    breached = [c for c in contracts if c["status"] in ("breached", "broken", "error") and c not in broken]
    return {
        "status": "broken" if broken else "degraded" if breached else "healthy",
        "broken": len(broken),
        "breached": len(breached),
        "ok": sum(1 for c in contracts if c["status"] == "ok"),
        "total": len(contracts),
    }
