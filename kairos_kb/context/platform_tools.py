"""Tools only one platform has, for that platform's connection endpoints.

  Databricks  table_history(entity_id)   Delta history: every write, by whom and which job
  Snowflake   object_ddl(object_name)    GET_DDL: the definition of a view, procedure, task, pipe…

Both read the platform and never change it; both stay inside what the agent may see.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.connectors.factory import connector_for_entity, platform_of, sql_dialect
from kairos_kb.context.access import AgentIdentity
from kairos_kb.context.files import redact_values
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.table import Table

HISTORY_LIMIT = 50
DDL_KINDS = {"table", "view", "procedure", "function", "task", "pipe", "stream", "dynamic_table", "file_format",
             "sequence", "stage"}
_OBJECT = re.compile(r'^[A-Za-z0-9_$"]+\.[A-Za-z0-9_$"]+\.[A-Za-z0-9_$" ]+(\([^)]*\))?$')


async def table_history(db: AsyncSession, identity: AgentIdentity, entity_id: str,
                        limit: int = 20) -> Dict[str, Any]:
    """Databricks: the table's Delta history, newest first, with user e-mail addresses redacted."""
    table = (await db.execute(select(Table).where(Table.entity_id == entity_id))).scalars().first()
    if table is None:
        return {"error": f"{entity_id} is not a known table. Use find() to find it."}
    if await platform_of(db, entity_id) != "databricks":
        return {"error": "table_history reads Delta history, which only Databricks tables have."}
    connector = await connector_for_entity(db, entity_id)
    name = ".".join(f"`{p}`" for p in table.full_name.split("."))
    limit = max(1, min(int(limit or 20), HISTORY_LIMIT))
    try:
        result = await connector.execute_query(f"DESCRIBE HISTORY {name} LIMIT {limit}")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not read the history: {str(exc)[:300]}"}
    status = result.get("status") or {}
    if status.get("state") not in (None, "SUCCEEDED"):
        return {"error": "No Delta history: " + str(((status.get("error") or {}).get("message")) or "")[:300]
                + " (views and non-Delta tables have none)."}
    rows = connector._rows_from_statement_result(result)  # noqa: SLF001
    versions = []
    for r in rows:
        job = _json(r.get("job")) or {}
        versions.append({k: v for k, v in {
            "version": r.get("version"),
            "timestamp": r.get("timestamp"),
            "operation": r.get("operation"),
            "by": redact_values(str(r.get("userName") or "")) or None,
            "job": {"id": job.get("jobId"), "name": job.get("jobName"), "run_id": job.get("jobRunId")} if job else None,
            "notebook": (_json(r.get("notebook")) or {}).get("notebookPath"),
            "metrics": _json(r.get("operationMetrics")),
        }.items() if v not in (None, "", {})})
    return {"entity_id": entity_id, "table": table.full_name, "versions": versions, "count": len(versions),
            "note": "Writes by a job link to that job's pipeline; get_context on it for its runs."}


async def object_ddl(db: AsyncSession, identity: AgentIdentity, object_name: str, kind: str = "") -> Dict[str, Any]:
    """Snowflake: an object's definition with GET_DDL — views, procedures, tasks, pipes, streams, tables."""
    name = (object_name or "").strip()
    if not _OBJECT.match(name):
        return {"error": "Give the fully qualified name: DATABASE.SCHEMA.OBJECT (procedures may add their "
                         "argument types, e.g. DB.SCH.LOAD_SALES(DATE))."}
    database = name.split(".", 1)[0].strip('"')
    catalogs = (await db.execute(select(Catalog).where(func.lower(Catalog.name) == database.lower()))).scalars().all()
    visible = [c for c in catalogs if identity.sees_entity(c.entity_id)]
    if not visible:
        return {"error": f"Database '{database}' is not in this connection's map."}
    entity_id = visible[0].entity_id
    if await platform_of(db, entity_id) != "snowflake":
        return {"error": "object_ddl reads Snowflake definitions; this object is not on Snowflake."}
    kind = (kind or "").strip().lower()
    if not kind:
        table = (await db.execute(select(Table).where(func.lower(Table.full_name) == name.lower()))).scalars().first()
        if table is None:
            return {"error": "Say what kind of object it is (procedure, task, pipe, function, stream, view, table…)."}
        kind = {"VIEW": "view", "MATERIALIZED_VIEW": "view", "STREAM": "stream",
                "DYNAMIC_TABLE": "dynamic_table"}.get((table.table_type or "").upper(), "table")
    if kind not in DDL_KINDS:
        return {"error": f"Unknown kind '{kind}'. One of: {', '.join(sorted(DDL_KINDS))}."}
    connector = await connector_for_entity(db, entity_id)
    if sql_dialect(connector) != "snowflake":
        return {"error": "object_ddl reads Snowflake definitions."}
    try:
        ddl = await connector.read_workspace_file(f"snowflake://{kind}/{name}")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not read the definition: {str(exc)[:300]}"}
    return {"object": name, "kind": kind, "ddl": ddl[:40000], "truncated": len(ddl) > 40000}


def _json(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value) if value else None
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, ValueError):
        return None
