"""Checks an agent can ask Kairos to run against the live platform.

Kairos verifies the grain key it states for each table. Agents often need to
test a different key — "is (ORG_VID, INVOICE_ID, INVOICE_ITEM) unique?" —
before they aggregate or join on it. This runs that check read-only, on the
platform, with guardrails: known columns only, at most a handful of them, and
results cached so repeated questions do not repeat the scan.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.connectors.databricks import DatabricksConnector
from kairos_kb.connectors.factory import connector_for_entity, quote_column, quote_table, sql_dialect
from kairos_kb.context.documents import load_profile
from kairos_kb.context.privacy import mask_rows, tagged_personal
from kairos_kb.enrichment.context import gather_context
from kairos_kb.enrichment.pipeline import _q

MAX_KEY_COLUMNS = 8
CACHE_SECONDS = 3600
_CACHE: Dict[Tuple[str, Tuple[str, ...]], Tuple[float, Dict[str, Any]]] = {}


def _rows(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    status = (result.get("status") or {})
    if status.get("state") not in (None, "SUCCEEDED"):
        raise RuntimeError(((status.get("error") or {}).get("message")) or status.get("state"))
    return DatabricksConnector._rows_from_statement_result(result)


def parse_columns(columns: str) -> List[str]:
    return [c.strip().strip("`") for c in (columns or "").replace("+", ",").split(",") if c.strip()]


async def check_key_uniqueness(db: AsyncSession, entity_id: str, columns: str) -> Dict[str, Any]:
    wanted = parse_columns(columns)
    if not wanted:
        return {"error": "Give the key columns, comma-separated, e.g. 'ORG_VID, INVOICE_ID'."}
    if len(wanted) > MAX_KEY_COLUMNS:
        return {"error": f"At most {MAX_KEY_COLUMNS} key columns."}
    context_doc = await gather_context(db, entity_id)
    if context_doc is None or context_doc.get("kind") != "table":
        return {"error": f"{entity_id} is not a known table. Use find_data() to find it."}
    real = {c["name"].lower(): c["name"] for c in context_doc.get("columns") or []}
    unknown = [c for c in wanted if c.lower() not in real]
    if unknown:
        return {"error": f"Not columns of this table: {', '.join(unknown)}",
                "columns": sorted(real.values())[:200]}
    names = tuple(real[c.lower()] for c in wanted)

    cache_key = (entity_id, tuple(sorted(n.lower() for n in names)))
    hit = _CACHE.get(cache_key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return {**hit[1], "cached": True}

    connector = await connector_for_entity(db, entity_id)
    snowflake = sql_dialect(connector) == "snowflake"
    table = quote_table(connector, context_doc["full_name"]) if snowflake else _q(context_doc["full_name"])
    cols = ", ".join(quote_column(connector, n) for n in names)
    null_any = " OR ".join(f"{quote_column(connector, n)} IS NULL" for n in names)
    # Distinct keys with NULLs counted as values: struct() on Databricks, a DISTINCT subquery on Snowflake.
    distinct = (f"(SELECT COUNT(*) FROM (SELECT DISTINCT {cols} FROM {table}))" if snowflake
                else f"COUNT(DISTINCT struct({cols}))")
    try:
        rows = _rows(await connector.execute_query(
            f"SELECT COUNT(*) AS n, {distinct} AS k, "
            f"SUM(CASE WHEN {null_any} THEN 1 ELSE 0 END) AS nulls FROM {table}"
        ))
        low = {k.lower(): v for k, v in rows[0].items()}
        n, k, nulls = int(low["n"]), int(low["k"]), int(low["nulls"] or 0)
        samples: List[Dict[str, Any]] = []
        if n != k:
            samples = _rows(await connector.execute_query(
                f"SELECT {cols}, COUNT(*) AS copies FROM {table} GROUP BY {cols} HAVING COUNT(*) > 1 "
                f"ORDER BY copies DESC LIMIT 3"
            ))
            samples = [{("copies" if k.lower() == "copies" else k): v for k, v in r.items()} for r in samples]
            profile = await load_profile(db, entity_id)
            samples = mask_rows(samples, tagged_personal(((profile or {}).get("shape") or {}).get("columns")))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"The check could not run on the platform: {str(exc)[:200]}"}

    key_text = " + ".join(names)
    result = {
        "entity_id": entity_id,
        "key": list(names),
        "rows": n,
        "distinct_keys": k,
        "duplicate_rows": n - k,
        "rows_with_null_in_key": nulls,
        "unique": n == k,
        "verdict": (f"{key_text} is unique across {n:,} rows" if n == k else
                    f"{key_text} is NOT unique: {n - k:,} duplicate rows out of {n:,}"),
        "duplicate_examples": samples,
        "note": ("NULLs in a key column count as one value in COUNT DISTINCT(struct) — "
                 "rows with NULL keys may still collide." if nulls else None),
    }
    _CACHE[cache_key] = (time.time(), result)
    return result
