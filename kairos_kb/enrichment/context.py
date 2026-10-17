"""Gather everything the warehouse knows about one entity.

This is the raw material handed to the enrichment agent before it starts
calling tools. The richer this is, the fewer tool round-trips the agent
needs to reach an understanding.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.models.catalog import Catalog
from kairos_kb.models.change_event import ChangeEvent
from kairos_kb.models.column import Column
from kairos_kb.models.job import Job
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.models.run import Run
from kairos_kb.models.schema import Schema
from kairos_kb.models.table import Table
from kairos_kb.models.task import Task
from kairos_kb.models.task_run import TaskRun
from kairos_kb.models.workspace import Workspace

logger = logging.getLogger(__name__)

# Coarse grains only. Column semantics are captured inside the parent
# table's profile; runs and task runs are events, not things to describe.
# Platform objects synced beyond tables and pipelines (see ingestion/object_sync.py).
INFRA_KINDS = ["location", "integration", "external_volume", "warehouse", "compute_pool", "resource_monitor",
               "role", "database_role", "user", "network_policy", "share", "application"]
SCHEMA_OBJECT_KINDS = ["stage", "file_format", "sequence", "tag", "policy", "secret", "network_rule"]
CODE_OBJECT_KINDS = ["procedure", "function", "pipe", "alert", "semantic_view", "cortex_search", "notebook",
                     "streamlit", "model", "git_repository", "dbt_project"]
OBJECT_KINDS = INFRA_KINDS + SCHEMA_OBJECT_KINDS + CODE_OBJECT_KINDS

PROFILABLE_KINDS = ["workspace", "catalog", "schema", "table", "job", "task"] + OBJECT_KINDS

# Containers are profiled before their contents, and tasks last so they can
# link to tables that already have profiles.
KIND_PRIORITY = {
    "workspace": 10,
    "catalog": 20,
    "schema": 30,
    # Tasks before tables: a task's code is the evidence the frontier
    # reaches its tables on, so it should be read first.
    "task": 35,
    "table": 40,
    "job": 50,
    # Infrastructure first (a stage is described in terms of its integration and bucket), then the
    # objects schemas hold, then code-bearing objects alongside the tasks that call them.
    **{k: 25 for k in INFRA_KINDS},
    **{k: 32 for k in SCHEMA_OBJECT_KINDS},
    **{k: 36 for k in CODE_OBJECT_KINDS},
}


def _json_default(value: Any) -> str:
    return str(value)


def source_hash(context: Dict[str, Any]) -> str:
    """Stable hash of the source material, so unchanged entities can be skipped."""
    payload = json.dumps(context, sort_keys=True, default=_json_default)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def gather_context(db: AsyncSession, entity_id: str) -> Optional[Dict[str, Any]]:
    """Collect the full warehouse view of one entity, or None if unknown."""
    kind = entity_id.split(":", 1)[0]

    if kind == "workspace":
        return await _workspace_context(db, entity_id)
    if kind == "catalog":
        return await _catalog_context(db, entity_id)
    if kind == "schema":
        return await _schema_context(db, entity_id)
    if kind == "table":
        return await _table_context(db, entity_id)
    if kind == "job":
        return await _job_context(db, entity_id)
    if kind == "task":
        return await _task_context(db, entity_id)
    return await _object_context(db, entity_id)


async def _object_context(db: AsyncSession, entity_id: str) -> Optional[Dict[str, Any]]:
    """Any other entity: a platform object (warehouse, stage, procedure …) or one the agent found."""
    from kairos_kb.models.discovered import DiscoveredEntity, DiscoveredRelation

    ent = (await db.execute(select(DiscoveredEntity).where(DiscoveredEntity.entity_id == entity_id))).scalars().first()
    if ent is None:
        return None
    attrs = dict(ent.attrs or {})
    definition = attrs.pop("definition", None)
    rels = (await db.execute(select(DiscoveredRelation).where(
        DiscoveredRelation.status != "contradicted",
        (DiscoveredRelation.source_entity_id == entity_id) | (DiscoveredRelation.target_entity_id == entity_id),
    ).limit(300))).scalars().all()
    links = []
    for r in rels:
        out = r.source_entity_id == entity_id
        links.append({"direction": "out" if out else "in", "relation": r.relation_type,
                      "entity_id": r.target_entity_id if out else r.source_entity_id,
                      "status": r.status, "rationale": (r.rationale or "")[:300]})
    return {
        "entity_id": entity_id,
        "kind": ent.kind,
        "name": ent.name,
        "full_name": ent.full_name or ent.name,
        "origin": ent.origin,
        "attributes": attrs,
        "definition": definition,
        "links": sorted(links, key=lambda l: (l["relation"], l["entity_id"])),
        **(await _provenance(db, entity_id)),
    }


async def _provenance(db: AsyncSession, entity_id: str) -> Dict[str, Any]:
    """Change history for an entity — the temporal signal."""
    changes = (
        await db.execute(
            select(ChangeEvent)
            .where(ChangeEvent.entity_id == entity_id)
            .order_by(ChangeEvent.detected_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return {
        "change_events": [
            {
                "change_type": c.change_type,
                "field": c.field_name,
                "old": c.old_value,
                "new": c.new_value,
                "detected_at": c.detected_at.isoformat(),
            }
            for c in changes
        ]
    }


async def _workspace_context(db: AsyncSession, entity_id: str) -> Optional[Dict[str, Any]]:
    name = entity_id.split(":", 1)[1]
    workspace = (
        await db.execute(select(Workspace).where(Workspace.name == name))
    ).scalars().first()
    if not workspace:
        return None

    catalogs = (
        await db.execute(select(Catalog).where(Catalog.workspace_id == workspace.id))
    ).scalars().all()
    jobs = (await db.execute(select(Job).where(Job.workspace_id == workspace.id))).scalars().all()

    return {
        "entity_id": entity_id,
        "kind": "workspace",
        "name": workspace.name,
        "attributes": {
            "host": workspace.host,
            "cloud": workspace.cloud,
            "region": workspace.region,
            "status": workspace.status,
            "description": workspace.description,
        },
        "catalogs": [{"name": c.name, "entity_id": c.entity_id, "comment": c.comment} for c in catalogs],
        "jobs": [{"name": j.name, "entity_id": j.entity_id} for j in jobs[:100]],
        "counts": {"catalogs": len(catalogs), "jobs": len(jobs)},
    }


async def _catalog_context(db: AsyncSession, entity_id: str) -> Optional[Dict[str, Any]]:
    catalog = (
        await db.execute(select(Catalog).where(Catalog.entity_id == entity_id))
    ).scalars().first()
    if not catalog:
        return None

    schemas = (
        await db.execute(select(Schema).where(Schema.catalog_id == catalog.id).order_by(Schema.name))
    ).scalars().all()

    schema_ids = [s.id for s in schemas]
    tables: List[Table] = []
    if schema_ids:
        tables = (
            await db.execute(select(Table).where(Table.schema_id.in_(schema_ids)))
        ).scalars().all()

    return {
        "entity_id": entity_id,
        "kind": "catalog",
        "name": catalog.name,
        "attributes": {
            "catalog_type": catalog.catalog_type,
            "owner": catalog.owner,
            "comment": catalog.comment,
            "isolation_mode": catalog.isolation_mode,
            "properties": catalog.properties,
        },
        "schemas": [
            {"name": s.name, "entity_id": s.entity_id, "comment": s.comment} for s in schemas
        ],
        "sample_tables": [
            {"full_name": t.full_name, "table_type": t.table_type, "comment": t.comment}
            for t in tables[:60]
        ],
        "counts": {"schemas": len(schemas), "tables": len(tables)},
        **await _provenance(db, entity_id),
    }


async def _schema_context(db: AsyncSession, entity_id: str) -> Optional[Dict[str, Any]]:
    schema = (
        await db.execute(select(Schema).where(Schema.entity_id == entity_id))
    ).scalars().first()
    if not schema:
        return None

    tables = (
        await db.execute(select(Table).where(Table.schema_id == schema.id).order_by(Table.name))
    ).scalars().all()

    return {
        "entity_id": entity_id,
        "kind": "schema",
        "name": schema.name,
        "full_name": schema.full_name,
        "attributes": {"owner": schema.owner, "comment": schema.comment, "properties": schema.properties},
        "tables": [
            {
                "name": t.name,
                "entity_id": t.entity_id,
                "table_type": t.table_type,
                "format": t.data_source_format,
                "comment": t.comment,
            }
            for t in tables
        ],
        "counts": {"tables": len(tables)},
        **await _provenance(db, entity_id),
    }


async def _table_context(db: AsyncSession, entity_id: str) -> Optional[Dict[str, Any]]:
    table = (await db.execute(select(Table).where(Table.entity_id == entity_id))).scalars().first()
    if not table:
        return None

    columns = (
        await db.execute(
            select(Column).where(Column.table_id == table.id).order_by(Column.ordinal_position)
        )
    ).scalars().all()

    lineage = (
        await db.execute(
            select(LineageEdge)
            .where(
                or_(
                    LineageEdge.source_entity_id == entity_id,
                    LineageEdge.target_entity_id == entity_id,
                )
            )
            .limit(100)
        )
    ).scalars().all()

    return {
        "entity_id": entity_id,
        "kind": "table",
        "name": table.name,
        "full_name": table.full_name,
        "attributes": {
            "table_type": table.table_type,
            "data_source_format": table.data_source_format,
            "owner": table.owner,
            "comment": table.comment,
            "storage_location": table.storage_location,
            "row_count": table.row_count,
            "size_bytes": table.size_bytes,
            "properties": table.properties,
        },
        "columns": [
            {
                "name": c.name,
                "data_type": c.data_type,
                "full_data_type": c.full_data_type,
                "nullable": c.is_nullable,
                "partition": c.is_partition_column,
                "comment": c.comment,
                "position": c.ordinal_position,
            }
            for c in columns
        ],
        "known_lineage": [
            {
                "direction": "downstream" if e.source_entity_id == entity_id else "upstream",
                "other": e.target_entity_id if e.source_entity_id == entity_id else e.source_entity_id,
                "level": e.source_type,
            }
            for e in lineage
        ],
        **await _provenance(db, entity_id),
    }


async def _job_context(db: AsyncSession, entity_id: str) -> Optional[Dict[str, Any]]:
    job = (await db.execute(select(Job).where(Job.entity_id == entity_id))).scalars().first()
    if not job:
        return None

    tasks = (
        await db.execute(select(Task).where(Task.job_id == job.id).order_by(Task.task_key))
    ).scalars().all()
    runs = (
        await db.execute(
            select(Run).where(Run.job_id == job.id).order_by(Run.start_time.desc()).limit(20)
        )
    ).scalars().all()

    return {
        "entity_id": entity_id,
        "kind": "job",
        "name": job.name,
        "attributes": {
            "source_native_id": job.source_native_id,
            "owner": job.owner,
            "schedule": job.schedule,
            "tags": job.tags,
            "max_concurrent_runs": job.max_concurrent_runs,
            "timeout_seconds": job.timeout_seconds,
        },
        # The full job definition as Databricks returned it — the agent is
        # expected to read this closely.
        "settings_snapshot": job.settings_snapshot,
        "tasks": [
            {
                "task_key": t.task_key,
                "entity_id": t.entity_id,
                "task_type": t.task_type,
                "notebook_path": t.notebook_path,
                "depends_on": t.depends_on,
                "parameters": t.parameters,
            }
            for t in tasks
        ],
        "recent_runs": [
            {
                "result_state": r.result_state,
                "state": r.state,
                "start_time": r.start_time.isoformat() if r.start_time else None,
                "duration_ms": r.execution_duration_ms,
                "error_message": r.error_message,
            }
            for r in runs
        ],
        **await _provenance(db, entity_id),
    }


async def _task_context(db: AsyncSession, entity_id: str) -> Optional[Dict[str, Any]]:
    task = (await db.execute(select(Task).where(Task.entity_id == entity_id))).scalars().first()
    if not task:
        return None

    job = (await db.execute(select(Job).where(Job.id == task.job_id))).scalars().first()

    recent_task_runs = (
        await db.execute(
            select(TaskRun)
            .where(TaskRun.task_key == task.task_key)
            .order_by(TaskRun.start_time.desc())
            .limit(10)
        )
    ).scalars().all()

    return {
        "entity_id": entity_id,
        "kind": "task",
        "name": task.task_key,
        "attributes": {
            "task_type": task.task_type,
            "notebook_path": task.notebook_path,
            "sql_query": task.sql_query,
            "parameters": task.parameters,
            "depends_on": task.depends_on,
        },
        "parent_job": {
            "entity_id": job.entity_id if job else None,
            "name": job.name if job else None,
            "settings_snapshot": job.settings_snapshot if job else None,
        },
        "recent_task_runs": [
            {
                "result_state": tr.result_state,
                "state": tr.state,
                "error_message": tr.error_message,
                "start_time": tr.start_time.isoformat() if tr.start_time else None,
            }
            for tr in recent_task_runs
        ],
        **await _provenance(db, entity_id),
    }
