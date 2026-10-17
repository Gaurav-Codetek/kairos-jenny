"""Synthetic Warehouse entity graph endpoints.

The agent-facing view of the warehouse: what kinds of entity exist, how
they connect, and how to walk between them at any grain.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.db.engine import get_db
from kairos_kb.exceptions import NotFoundError
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.change_event import ChangeEvent
from kairos_kb.models.column import Column
from kairos_kb.models.evidence import Evidence
from kairos_kb.models.job import Job
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.models.run import Run
from kairos_kb.models.schema import Schema
from kairos_kb.models.sync_state import SyncState
from kairos_kb.models.table import Table
from kairos_kb.models.task import Task
from kairos_kb.models.task_run import TaskRun
from kairos_kb.models.workspace import Workspace
from kairos_kb.warehouse.entity_graph import EntityGraph, workspace_node_id
from kairos_kb.warehouse.entity_map import (
    DEFAULT_RELATION_GROUPS,
    ENTITY_KINDS,
    RELATION_GROUPS,
    entity_map_document,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/warehouse", tags=["warehouse"])

COUNT_MODELS = {
    "workspace": Workspace,
    "catalog": Catalog,
    "schema": Schema,
    "table": Table,
    "column": Column,
    "job": Job,
    "task": Task,
    "run": Run,
    "taskrun": TaskRun,
    "evidence": Evidence,
    "change": ChangeEvent,
    "syncstate": SyncState,
}


def _parse_groups(groups: Optional[str]) -> List[str]:
    """Parse a comma-separated relation-group filter."""
    if not groups:
        return list(DEFAULT_RELATION_GROUPS)
    requested = [g.strip() for g in groups.split(",") if g.strip()]
    return [g for g in requested if g in RELATION_GROUPS] or list(DEFAULT_RELATION_GROUPS)


@router.get("/map")
async def get_entity_map(db: AsyncSession = Depends(get_db)):
    """The entity map: every kind, every relationship, with live row counts.

    An agent should read this first — it describes the terrain before any
    traversal, so the agent can plan which grain to target.
    """
    document = entity_map_document()

    counts: Dict[str, int] = {}
    for kind, model in COUNT_MODELS.items():
        counts[kind] = (await db.execute(select(func.count()).select_from(model))).scalar() or 0

    for kind_entry in document["kinds"]:
        kind_entry["count"] = counts.get(kind_entry["kind"], 0)

    lineage_total = (await db.execute(select(func.count()).select_from(LineageEdge))).scalar() or 0
    table_lineage = (
        await db.execute(
            select(func.count()).select_from(LineageEdge).where(LineageEdge.source_type == "TABLE")
        )
    ).scalar() or 0

    document["totals"] = {
        "entities": sum(counts.values()),
        "lineage_edges": lineage_total,
        "table_lineage_edges": table_lineage,
        "column_lineage_edges": lineage_total - table_lineage,
    }
    return document


@router.get("/roots")
async def get_roots(db: AsyncSession = Depends(get_db)):
    """Entry points for exploration — one per workspace, with its top-level counts."""
    workspaces = (await db.execute(select(Workspace).order_by(Workspace.name))).scalars().all()

    roots = []
    for workspace in workspaces:
        catalog_count = (
            await db.execute(
                select(func.count()).select_from(Catalog).where(Catalog.workspace_id == workspace.id)
            )
        ).scalar() or 0
        job_count = (
            await db.execute(
                select(func.count()).select_from(Job).where(Job.workspace_id == workspace.id)
            )
        ).scalar() or 0
        failed_runs = (
            await db.execute(
                select(func.count())
                .select_from(Run)
                .where(Run.workspace_id == workspace.id, Run.result_state == "FAILED")
            )
        ).scalar() or 0

        roots.append(
            {
                "id": workspace_node_id(workspace),
                "kind": "workspace",
                "label": workspace.name,
                "host": workspace.host,
                "status": workspace.status,
                "last_synced_at": workspace.last_synced_at.isoformat()
                if workspace.last_synced_at
                else None,
                "catalogs": catalog_count,
                "jobs": job_count,
                "failed_runs": failed_runs,
            }
        )

    return {"roots": roots}


@router.get("/graph")
async def get_entity_graph(
    entity_id: str = Query(..., description="Node id to centre the graph on"),
    depth: int = Query(2, ge=0, le=6),
    relation_groups: Optional[str] = Query(
        None,
        description=(
            "Comma-separated subset of: structural, pipeline, operational, "
            "lineage, discovered, provenance. Defaults to everything except "
            "provenance, which fans out to thousands of nodes."
        ),
    ),
    limit_per_relation: int = Query(25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Walk the entity graph outward from any node, across every grain."""
    graph = EntityGraph(db)
    return await graph.traverse(
        entity_id,
        depth=depth,
        relation_groups=_parse_groups(relation_groups),
        limit_per_relation=limit_per_relation,
    )


@router.get("/entity")
async def get_entity(
    entity_id: str = Query(..., description="Node id"),
    db: AsyncSession = Depends(get_db),
):
    """Every stored attribute of one entity, plus exact neighbour counts per relation."""
    graph = EntityGraph(db)
    detail = await graph.entity_detail(entity_id)
    if not detail["known"]:
        # Still useful: lineage references entities outside the synced scope,
        # and the agent should be able to tell "absent" from "does not exist".
        detail["note"] = (
            "No stored row for this id. It is referenced by other records "
            "(typically lineage) but was never synced into the warehouse."
        )
    return detail


@router.get("/search")
async def search_entities(
    q: str = Query(..., min_length=1, description="Substring to match on name"),
    kinds: Optional[str] = Query(None, description="Comma-separated kinds to restrict to"),
    limit: int = Query(30, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Find entities by name across every grain. The agent's entry point."""
    graph = EntityGraph(db)
    kind_list = [k.strip() for k in kinds.split(",")] if kinds else None
    results = await graph.search(q, kinds=kind_list, limit=limit)
    return {"query": q, "count": len(results), "results": results}
