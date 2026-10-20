"""Enrichment endpoints — start runs, watch them live, read the profiles."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.db.engine import get_db
from kairos_kb.enrichment.context import PROFILABLE_KINDS
from kairos_kb.enrichment.profile_writer import load_profile_yaml
from kairos_kb.enrichment.runner import (
    create_run,
    expand_target,
    is_active,
    request_cancel,
    start_background,
)
from kairos_kb.exceptions import KairosException, NotFoundError
from kairos_kb.models.discovered import DiscoveredEntity, DiscoveredRelation
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.entity_profile import EntityProfile
from kairos_kb.models.job import Job
from kairos_kb.models.run import Run
from kairos_kb.models.schema import Schema
from kairos_kb.models.table import Table
from kairos_kb.models.task import Task
from kairos_kb.models.enrichment_run import EnrichmentEvent, EnrichmentItem, EnrichmentRun
from kairos_kb.models.workspace import Workspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/enrichment", tags=["enrichment"])


def connection_names(entity_ids: Optional[List[str]]) -> set[str]:
    """The connections a set of entity ids belong to (the name between the first two colons)."""
    return {e.split(":", 2)[1] for e in entity_ids or [] if e.count(":") >= 2}


async def resolve_workspace(db: AsyncSession, workspace_id: Optional[uuid.UUID],
                            entity_ids: Optional[List[str]]) -> Workspace:
    """The one connection a run (or an estimate) works on.

    A run's connection decides which platform its facts and history come from and
    how entities it discovers are named, so it must be the connection its entities
    belong to: taken from the entity ids, never guessed. Entities from two
    connections in one run are refused rather than half-processed on the wrong one.
    """
    names = connection_names(entity_ids)
    if len(names) > 1:
        raise KairosException(
            f"One run works on one connection; these entities come from {len(names)}: "
            f"{', '.join(sorted(names))}. Start a run per connection.", status_code=400)
    if workspace_id:
        workspace = await db.get(Workspace, workspace_id)
        if not workspace:
            raise NotFoundError("Workspace", str(workspace_id))
        if names and workspace.name not in names:
            raise KairosException(f"These entities belong to '{next(iter(names))}', not to '{workspace.name}'.",
                                  status_code=400)
        return workspace
    if names:
        name = next(iter(names))
        workspace = (await db.execute(select(Workspace).where(Workspace.name == name))).scalars().first()
        if not workspace:
            raise NotFoundError("Workspace", name)
        return workspace
    workspaces = (await db.execute(select(Workspace))).scalars().all()
    if len(workspaces) == 1:
        return workspaces[0]
    if not workspaces:
        raise NotFoundError("Workspace", "")
    raise KairosException("Say which connection to enrich: pass workspace_id or entity_ids.", status_code=400)


class StartRunRequest(BaseModel):
    workspace_id: Optional[uuid.UUID] = None
    kinds: Optional[List[str]] = Field(
        default=None, description=f"Subset of {PROFILABLE_KINDS}. Defaults to all."
    )
    entity_ids: Optional[List[str]] = Field(
        default=None, description="Profile exactly these entities, ignoring kinds."
    )
    limit_per_kind: Optional[int] = Field(
        default=None, description="Cap entities per kind — useful for a pilot run."
    )
    include_descendants: bool = Field(
        default=True,
        description="Only used when follow_graph is false. Static expansion of the seeds.",
    )
    follow_graph: bool = Field(
        default=True,
        description=(
            "Frontier mode. Profile the seeds, then follow their relationships "
            "outward on evidence: a job reaches its tasks, and a task the tables "
            "its code reads and writes. Stored links are followed only when "
            "verified or corroborated by this run's code scan or Delta history."
        ),
    )
    max_depth: Optional[int] = Field(
        default=None, description="How many relationship hops the frontier may travel. Default 3."
    )
    max_entities: Optional[int] = Field(
        default=None,
        description=(
            "Hard ceiling on entities profiled in one run. Without it a single "
            "seed can reach the whole warehouse through its links. Default 30."
        ),
    )
    entity_cap: bool = Field(
        default=True,
        description=(
            "Off: no ceiling on entities. The frontier is then bounded only by "
            "max_depth, and one seed may profile everything it reaches."
        ),
    )
    include_upstream_producers: bool = Field(
        default=False,
        description=(
            "Also queue the jobs that write the tables a pipeline reads — one "
            "hop upstream. Off by default: a pipeline's neighbourhood is its own "
            "tasks and the tables they touch."
        ),
    )
    force: bool = Field(default=False, description="Re-profile even if the snapshot is unchanged.")


def _run_payload(run: EnrichmentRun) -> Dict[str, Any]:
    total = run.total_items or 0
    done = run.completed_items + run.failed_items + run.skipped_items
    return {
        "id": str(run.id),
        "workspace_id": str(run.workspace_id),
        "status": run.status,
        "active_in_process": is_active(run.id),
        "scope": run.scope,
        "totals": {
            "total": total,
            "completed": run.completed_items,
            "failed": run.failed_items,
            "skipped": run.skipped_items,
            "remaining": max(0, total - done),
            "percent": round(100.0 * done / total, 1) if total else 0.0,
        },
        "discovered": {
            "relations": run.relations_discovered,
            "entities": run.entities_discovered,
        },
        "current_entity_id": run.current_entity_id,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "heartbeat_at": run.heartbeat_at.isoformat() if run.heartbeat_at else None,
        "usage": {
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "total_tokens": run.input_tokens + run.output_tokens,
            "llm_calls": run.llm_calls,
            "tool_calls": run.tool_calls,
        },
        "activity": run.current_activity,
        "activity_at": run.current_activity_at.isoformat() if run.current_activity_at else None,
    }


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _item_payload(item: EnrichmentItem) -> Dict[str, Any]:
    duration = (
        (item.finished_at - item.started_at).total_seconds()
        if item.started_at and item.finished_at else None
    )
    return {
        "entity_id": item.entity_id,
        "name": item.entity_id.split(":")[-1],
        "kind": item.kind,
        "status": item.status,
        "depth": item.depth,
        # Why the frontier queued it: "WRITES_TABLE · code line 142", from its parent.
        "via_relation": item.via_relation,
        "parent_entity_id": item.parent_entity_id,
        "parent_name": item.parent_entity_id.split(":")[-1] if item.parent_entity_id else None,
        "started_at": _iso(item.started_at),
        "finished_at": _iso(item.finished_at),
        "duration_s": round(duration, 1) if duration is not None else None,
        "input_tokens": item.input_tokens,
        "output_tokens": item.output_tokens,
        "total_tokens": item.input_tokens + item.output_tokens,
        "llm_calls": item.llm_calls,
        "tool_calls": item.tool_calls,
    }


@router.post("/runs", status_code=201)
async def start_run(body: StartRunRequest, db: AsyncSession = Depends(get_db)):
    """Queue an enrichment run and start it in the background."""
    workspace = await resolve_workspace(db, body.workspace_id, body.entity_ids)

    scope: Dict[str, Any] = {
        "kinds": body.kinds,
        "entity_ids": body.entity_ids,
        "limit_per_kind": body.limit_per_kind,
        "include_descendants": body.include_descendants,
        "follow_graph": body.follow_graph,
        "max_depth": body.max_depth,
        "max_entities": body.max_entities,
        "entity_cap": body.entity_cap,
        "include_upstream_producers": body.include_upstream_producers,
        "force": body.force,
    }
    run = await create_run(db, workspace=workspace, scope=scope)
    await db.commit()

    start_background(run.id)
    return _run_payload(run)


@router.get("/runs")
async def list_runs(limit: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    """Most recent runs first."""
    runs = (
        await db.execute(select(EnrichmentRun).order_by(EnrichmentRun.created_at.desc()).limit(limit))
    ).scalars().all()
    return {"runs": [_run_payload(r) for r in runs]}


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Live status of one run."""
    run = await db.get(EnrichmentRun, run_id)
    if not run:
        raise NotFoundError("EnrichmentRun", str(run_id))

    by_status = (
        await db.execute(
            select(EnrichmentItem.status, func.count())
            .where(EnrichmentItem.run_id == run_id)
            .group_by(EnrichmentItem.status)
        )
    ).all()

    payload = _run_payload(run)
    payload["items_by_status"] = {status: count for status, count in by_status}

    # What is being enriched right now, and what just finished — the live view.
    current = None
    if run.current_entity_id:
        current = (
            await db.execute(
                select(EnrichmentItem)
                .where(EnrichmentItem.run_id == run_id, EnrichmentItem.entity_id == run.current_entity_id)
                .order_by(EnrichmentItem.started_at.desc().nulls_last())
                .limit(1)
            )
        ).scalars().first()
    recent = (
        await db.execute(
            select(EnrichmentItem)
            .where(EnrichmentItem.run_id == run_id, EnrichmentItem.finished_at.is_not(None))
            .order_by(EnrichmentItem.finished_at.desc())
            .limit(8)
        )
    ).scalars().all()
    payload["current"] = _item_payload(current) if current and current.status == "running" else None
    payload["recent_items"] = [_item_payload(i) for i in recent]

    # A job's entity id ends in its numeric id; show people its name instead.
    shown = [p for p in [payload["current"], *payload["recent_items"]] if p]
    job_ids = {p["entity_id"] for p in shown if p["kind"] == "job"}
    job_ids |= {p["parent_entity_id"] for p in shown if (p["parent_entity_id"] or "").startswith("job:")}
    if job_ids:
        names = dict((await db.execute(select(Job.entity_id, Job.name).where(Job.entity_id.in_(job_ids)))).all())
        for p in shown:
            p["name"] = names.get(p["entity_id"], p["name"])
            if p["parent_entity_id"]:
                p["parent_name"] = names.get(p["parent_entity_id"], p["parent_name"])
    # Timers in the browser count from the server's clock, not the viewer's.
    payload["server_now"] = datetime.now(timezone.utc).isoformat()
    return payload


@router.get("/runs/{run_id}/events")
async def get_run_events(
    run_id: uuid.UUID,
    after: int = Query(0, ge=0, description="Return events with sequence greater than this"),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """The live activity feed. Poll with `after` set to the last sequence you saw."""
    events = (
        await db.execute(
            select(EnrichmentEvent)
            .where(EnrichmentEvent.run_id == run_id, EnrichmentEvent.sequence > after)
            .order_by(EnrichmentEvent.sequence)
            .limit(limit)
        )
    ).scalars().all()

    return {
        "run_id": str(run_id),
        "events": [
            {
                "sequence": e.sequence,
                "event_type": e.event_type,
                "level": e.level,
                "entity_id": e.entity_id,
                "message": e.message,
                "payload": e.payload,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
        "last_sequence": events[-1].sequence if events else after,
    }


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Restart a run that was paused by a container reload or cancel."""
    run = await db.get(EnrichmentRun, run_id)
    if not run:
        raise NotFoundError("EnrichmentRun", str(run_id))
    start_background(run_id)
    return {"id": str(run_id), "status": "resuming"}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Stop a run after the entity it is currently working on."""
    run = await db.get(EnrichmentRun, run_id)
    if not run:
        raise NotFoundError("EnrichmentRun", str(run_id))
    request_cancel(run_id)
    return {"id": str(run_id), "status": "canceling"}


# ── Scoped targeting ─────────────────────────────────────────────────

# Fallbacks until this deployment has enough measured runs to average.
DEFAULT_SECONDS_PER_KIND = {
    "workspace": 30.0,
    "catalog": 25.0,
    "schema": 20.0,
    "table": 30.0,
    "job": 35.0,
    "task": 45.0,
}


async def _measured_seconds_per_kind(db: AsyncSession) -> Dict[str, float]:
    """Average wall-clock seconds per entity kind, from completed items."""
    rows = (
        await db.execute(
            select(
                EnrichmentItem.kind,
                func.avg(
                    func.extract("epoch", EnrichmentItem.finished_at - EnrichmentItem.started_at)
                ),
                func.count(),
            )
            .where(
                EnrichmentItem.status == "completed",
                EnrichmentItem.started_at.isnot(None),
                EnrichmentItem.finished_at.isnot(None),
            )
            .group_by(EnrichmentItem.kind)
        )
    ).all()
    # Ignore kinds with too few samples to mean anything.
    return {kind: float(avg) for kind, avg, count in rows if avg and count >= 2}


@router.get("/targets")
async def list_targets(
    kind: str = Query("job", description="Kind to list: job, catalog, schema, or table"),
    q: Optional[str] = Query(None, description="Filter by name substring"),
    workspace_id: Optional[uuid.UUID] = None,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Selectable enrichment targets, annotated with how much work each implies.

    Use this to pick one pipeline instead of profiling the whole warehouse.
    """
    profiled = {
        row[0]
        for row in (await db.execute(select(EntityProfile.entity_id))).all()
    }

    targets: List[Dict[str, Any]] = []

    if kind == "job":
        query = select(Job).order_by(Job.name).limit(limit)
        if workspace_id:
            query = query.where(Job.workspace_id == workspace_id)
        if q:
            query = query.where(Job.name.ilike(f"%{q}%"))
        jobs = (await db.execute(query)).scalars().all()

        task_counts = dict(
            (
                await db.execute(
                    select(Task.job_id, func.count()).group_by(Task.job_id)
                )
            ).all()
        )
        failed_counts = dict(
            (
                await db.execute(
                    select(Run.job_id, func.count())
                    .where(Run.result_state == "FAILED")
                    .group_by(Run.job_id)
                )
            ).all()
        )

        for job in jobs:
            task_total = task_counts.get(job.id, 0)
            targets.append(
                {
                    "entity_id": job.entity_id,
                    "kind": "job",
                    "name": job.name,
                    "detail": f"job {job.source_native_id}",
                    "owner": job.owner,
                    "child_count": task_total,
                    # The job itself plus one entity per task.
                    "entity_count": 1 + task_total,
                    "profiled": job.entity_id in profiled,
                    "failed_runs": failed_counts.get(job.id, 0),
                }
            )

    elif kind == "catalog":
        query = select(Catalog).order_by(Catalog.name).limit(limit)
        if workspace_id:
            query = query.where(Catalog.workspace_id == workspace_id)
        if q:
            query = query.where(Catalog.name.ilike(f"%{q}%"))
        for catalog in (await db.execute(query)).scalars().all():
            schemas = (
                await db.execute(select(Schema.id).where(Schema.catalog_id == catalog.id))
            ).scalars().all()
            table_total = 0
            if schemas:
                table_total = (
                    await db.execute(
                        select(func.count()).select_from(Table).where(Table.schema_id.in_(schemas))
                    )
                ).scalar() or 0
            targets.append(
                {
                    "entity_id": catalog.entity_id,
                    "kind": "catalog",
                    "name": catalog.name,
                    "detail": f"{len(schemas)} schemas, {table_total} tables",
                    "owner": catalog.owner,
                    "child_count": len(schemas) + table_total,
                    "entity_count": 1 + len(schemas) + table_total,
                    "profiled": catalog.entity_id in profiled,
                    "failed_runs": 0,
                }
            )

    elif kind == "schema":
        query = select(Schema).order_by(Schema.full_name).limit(limit)
        if workspace_id:
            query = query.where(Schema.workspace_id == workspace_id)
        if q:
            query = query.where(Schema.full_name.ilike(f"%{q}%"))
        for schema in (await db.execute(query)).scalars().all():
            table_total = (
                await db.execute(
                    select(func.count()).select_from(Table).where(Table.schema_id == schema.id)
                )
            ).scalar() or 0
            targets.append(
                {
                    "entity_id": schema.entity_id,
                    "kind": "schema",
                    "name": schema.full_name,
                    "detail": f"{table_total} tables",
                    "owner": schema.owner,
                    "child_count": table_total,
                    "entity_count": 1 + table_total,
                    "profiled": schema.entity_id in profiled,
                    "failed_runs": 0,
                }
            )

    else:  # table
        query = select(Table).order_by(Table.full_name).limit(limit)
        if workspace_id:
            query = query.where(Table.workspace_id == workspace_id)
        if q:
            query = query.where(Table.full_name.ilike(f"%{q}%"))
        for table in (await db.execute(query)).scalars().all():
            targets.append(
                {
                    "entity_id": table.entity_id,
                    "kind": "table",
                    "name": table.full_name,
                    "detail": table.table_type,
                    "owner": table.owner,
                    "child_count": 0,
                    "entity_count": 1,
                    "profiled": table.entity_id in profiled,
                    "failed_runs": 0,
                }
            )

    return {"kind": kind, "count": len(targets), "targets": targets}


class EstimateRequest(BaseModel):
    entity_ids: List[str]
    include_descendants: bool = True
    force: bool = False


@router.post("/estimate")
async def estimate_run(body: EstimateRequest, db: AsyncSession = Depends(get_db)):
    """Cost and duration estimate for a scoped run, before committing to it.

    Durations are averaged from this deployment's own completed items where
    there is enough history, and fall back to observed defaults otherwise.
    """
    workspace = await resolve_workspace(db, None, body.entity_ids)

    seen: set[str] = set()
    by_kind: Dict[str, int] = {}
    for entity_id in body.entity_ids:
        for entry in await expand_target(db, workspace, entity_id, body.include_descendants):
            if entry["entity_id"] in seen:
                continue
            seen.add(entry["entity_id"])
            by_kind[entry["kind"]] = by_kind.get(entry["kind"], 0) + 1

    already = set()
    if seen and not body.force:
        already = {
            row[0]
            for row in (
                await db.execute(
                    select(EntityProfile.entity_id).where(EntityProfile.entity_id.in_(seen))
                )
            ).all()
        }

    measured = await _measured_seconds_per_kind(db)
    to_process = seen - already

    seconds = 0.0
    for entity_id in to_process:
        kind = entity_id.split(":", 1)[0]
        seconds += measured.get(kind, DEFAULT_SECONDS_PER_KIND.get(kind, 30.0))

    return {
        "entities_in_scope": len(seen),
        "already_profiled": len(already),
        "to_process": len(to_process),
        "by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "estimated_seconds": round(seconds),
        "estimated_minutes": round(seconds / 60, 1),
        # One agent pass is several LLM turns; this is the useful order of magnitude.
        "estimated_llm_calls": len(to_process) * 4,
        "basis": "measured" if measured else "default",
        "measured_kinds": {k: round(v, 1) for k, v in measured.items()},
    }


# ── Profiles and the discovered map ──────────────────────────────────


@router.get("/profiles")
async def list_profiles(
    kind: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Index of generated profiles."""
    query = select(EntityProfile).order_by(EntityProfile.generated_at.desc()).limit(limit)
    if kind:
        query = query.where(EntityProfile.kind == kind)
    profiles = (await db.execute(query)).scalars().all()

    return {
        "profiles": [
            {
                "entity_id": p.entity_id,
                "kind": p.kind,
                "summary": p.summary,
                "purpose": p.purpose,
                "data_product": p.data_product,
                "semantic_tags": p.semantic_tags,
                "yaml_path": p.yaml_path,
                "generated_at": p.generated_at.isoformat(),
            }
            for p in profiles
        ]
    }


@router.get("/profiles/yaml")
async def get_profile_yaml(
    entity_id: str = Query(..., description="Entity whose YAML profile to read"),
    db: AsyncSession = Depends(get_db),
):
    """The raw YAML artifact for one entity."""
    content = await load_profile_yaml(db, entity_id)
    if content is None:
        raise NotFoundError("EntityProfile", entity_id)
    return {"entity_id": entity_id, "yaml": content}


@router.get("/discovered")
async def list_discovered(
    limit: int = Query(200, ge=1, le=1000),
    workspace_id: Optional[List[uuid.UUID]] = Query(None, description="Only these workspaces (repeatable)"),
    db: AsyncSession = Depends(get_db),
):
    """Everything the agent has added to the map that the sync never knew about."""
    def scoped(query, model):
        return query.where(model.workspace_id.in_(workspace_id)) if workspace_id else query

    relations = (
        await db.execute(
            scoped(select(DiscoveredRelation), DiscoveredRelation).order_by(DiscoveredRelation.observed_at.desc()).limit(limit)
        )
    ).scalars().all()
    entities = (
        await db.execute(
            scoped(select(DiscoveredEntity), DiscoveredEntity).order_by(DiscoveredEntity.first_seen_at.desc()).limit(limit)
        )
    ).scalars().all()

    by_type = (
        await db.execute(
            scoped(select(DiscoveredRelation.relation_type, func.count()), DiscoveredRelation)
            .group_by(DiscoveredRelation.relation_type)
            .order_by(func.count().desc())
        )
    ).all()
    by_kind = (
        await db.execute(
            scoped(select(DiscoveredEntity.kind, func.count()), DiscoveredEntity)
            .group_by(DiscoveredEntity.kind)
            .order_by(func.count().desc())
        )
    ).all()

    return {
        "relation_types": [{"relation_type": t, "count": c} for t, c in by_type],
        "entity_kinds": [{"kind": k, "count": c} for k, c in by_kind],
        "relations": [
            {
                "source": r.source_entity_id,
                "target": r.target_entity_id,
                "relation_type": r.relation_type,
                "confidence": r.confidence,
                "rationale": r.rationale,
                "source_ref": r.source_ref,
                "observed_at": r.observed_at.isoformat(),
            }
            for r in relations
        ],
        "entities": [
            {
                "entity_id": e.entity_id,
                "kind": e.kind,
                "name": e.name,
                "full_name": e.full_name,
                "rationale": e.rationale,
                "first_seen_at": e.first_seen_at.isoformat(),
            }
            for e in entities
        ],
    }
