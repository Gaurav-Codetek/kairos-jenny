"""Background orchestration of enrichment runs.

Every unit of work is persisted before it starts, so a run survives the API
container reloading mid-pass and can be resumed from where it stopped.
Progress and discoveries are written to ``enrichment_events``, which is what
the UI polls to render a live feed.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.db.engine import async_session_factory
from kairos_kb.enrichment.agent import MAX_ITERATIONS, profile_entity
from kairos_kb.enrichment.pipeline import (
    canonical_relation,
    classify_table,
    describe_missing_columns,
    effective_template,
    propagate_column_docs,
    reconcile_with_verification,
    refresh_column_coverage,
    facts_summary,
    gather_facts,
    profile_digest,
    record_code_sources,
    record_history_writers,
    retire_contradicted_writes,
    role_brief,
    verification_summary,
    verify_profile,
)
from kairos_kb.enrichment.context import (
    KIND_PRIORITY,
    PROFILABLE_KINDS,
    gather_context,
)
from kairos_kb.context.documents import index_entities
from kairos_kb.context.feedback import feedback_brief, mark_applied, open_feedback_for
from kairos_kb.enrichment.profile_writer import refresh_profile_yaml, write_profile
from kairos_kb.enrichment.tools import ToolContext
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.discovered import DiscoveredRelation
from kairos_kb.models.entity_profile import EntityProfile
from kairos_kb.models.enrichment_run import EnrichmentEvent, EnrichmentItem, EnrichmentRun
from kairos_kb.models.job import Job
from kairos_kb.models.schema import Schema
from kairos_kb.models.table import Table
from kairos_kb.models.task import Task
from kairos_kb.models.workspace import Workspace
from kairos_kb.warehouse.entity_graph import EntityGraph

logger = logging.getLogger(__name__)

# Runs currently executing in this process, so status can report liveness
# and a cancel request can be honoured promptly.
_ACTIVE: Dict[uuid.UUID, asyncio.Task] = {}
_CANCEL: set[uuid.UUID] = set()

# Frontier budget. A seed reaches its links, those reach theirs, and without
# a ceiling one pipeline can pull in the whole warehouse — so the walk is
# bounded by both how far it may travel and how much it may consume.
DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_ENTITIES = 30
# "No cap": larger than any warehouse, so only max_depth bounds the walk.
UNCAPPED = 1_000_000
# Turn budget for a light pass: an empty or scratch/test table.
LIGHT_ITERATIONS = 6


# ── Live telemetry ───────────────────────────────────────────────────


async def _record_telemetry(
    run_id: uuid.UUID,
    item_id: Optional[uuid.UUID],
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    llm_calls: int = 0,
    tool_calls: int = 0,
    activity: Optional[str] = None,
) -> None:
    """Add usage to the run and the item, and set the current activity line.

    Increments are applied in SQL (col = col + n), so the counters stay right
    even if two writers ever overlap. Own session, like _emit: telemetry is
    never lost to, or the cause of, a rollback elsewhere.
    """
    now = datetime.now(timezone.utc)
    run_values: Dict[str, Any] = {}
    counts = {"input_tokens": input_tokens, "output_tokens": output_tokens,
              "llm_calls": llm_calls, "tool_calls": tool_calls}
    for col, n in counts.items():
        if n:
            run_values[col] = getattr(EnrichmentRun, col) + n
    if activity is not None:
        run_values["current_activity"] = activity[:512]
        run_values["current_activity_at"] = now
    if not run_values:
        return
    run_values["heartbeat_at"] = now
    async with async_session_factory() as db:
        await db.execute(update(EnrichmentRun).where(EnrichmentRun.id == run_id).values(**run_values))
        item_values = {col: getattr(EnrichmentItem, col) + n for col, n in counts.items() if n}
        if item_id and item_values:
            await db.execute(update(EnrichmentItem).where(EnrichmentItem.id == item_id).values(**item_values))
        await db.commit()


# ── Event log ────────────────────────────────────────────────────────


async def _emit(
    run_id: uuid.UUID,
    entity_id: Optional[str],
    event_type: str,
    message: str,
    *,
    level: str = "info",
    payload: Dict[str, Any] | None = None,
) -> None:
    """Append one event. Uses its own session so it is never lost to a rollback."""
    async with async_session_factory() as db:
        next_sequence = (
            await db.execute(
                select(func.coalesce(func.max(EnrichmentEvent.sequence), 0)).where(
                    EnrichmentEvent.run_id == run_id
                )
            )
        ).scalar() or 0
        db.add(
            EnrichmentEvent(
                run_id=run_id,
                entity_id=entity_id,
                event_type=event_type,
                level=level,
                message=message[:4000],
                payload=payload,
                sequence=next_sequence + 1,
            )
        )
        await db.commit()


# ── Queue construction ───────────────────────────────────────────────


def _entry(entity_id: str, kind: str) -> Dict[str, Any]:
    return {"entity_id": entity_id, "kind": kind, "priority": KIND_PRIORITY.get(kind, 100)}


async def expand_target(
    db: AsyncSession,
    workspace: Workspace,
    entity_id: str,
    include_descendants: bool = True,
) -> List[Dict[str, Any]]:
    """Expand one selected entity into everything a scoped run should cover.

    Selecting a pipeline should profile the job *and its tasks* — the tasks are
    where the code lives, and therefore where relationships are found. Columns
    are deliberately absent: their semantics are captured inside the parent
    table's profile.
    """
    kind = entity_id.split(":", 1)[0]
    entries = [_entry(entity_id, kind)]
    if not include_descendants:
        return entries

    if kind == "job":
        job = (await db.execute(select(Job).where(Job.entity_id == entity_id))).scalars().first()
        if job:
            for task in (
                await db.execute(select(Task).where(Task.job_id == job.id).order_by(Task.task_key))
            ).scalars().all():
                entries.append(_entry(task.entity_id, "task"))

    elif kind == "schema":
        schema = (
            await db.execute(select(Schema).where(Schema.entity_id == entity_id))
        ).scalars().first()
        if schema:
            for table in (
                await db.execute(select(Table).where(Table.schema_id == schema.id).order_by(Table.name))
            ).scalars().all():
                entries.append(_entry(table.entity_id, "table"))

    elif kind == "catalog":
        catalog = (
            await db.execute(select(Catalog).where(Catalog.entity_id == entity_id))
        ).scalars().first()
        if catalog:
            schemas = (
                await db.execute(select(Schema).where(Schema.catalog_id == catalog.id))
            ).scalars().all()
            for schema in schemas:
                entries.append(_entry(schema.entity_id, "schema"))
            if schemas:
                for table in (
                    await db.execute(
                        select(Table).where(Table.schema_id.in_([s.id for s in schemas]))
                    )
                ).scalars().all():
                    entries.append(_entry(table.entity_id, "table"))

    elif kind == "workspace":
        for model, node_kind in ((Catalog, "catalog"), (Schema, "schema"), (Table, "table"), (Job, "job"), (Task, "task")):
            for row in (
                await db.execute(select(model).where(model.workspace_id == workspace.id))
            ).scalars().all():
                entries.append(_entry(row.entity_id, node_kind))

    if kind in ("workspace", "catalog", "schema"):
        entries += [_entry(eid, k) for eid, k in await platform_objects_in(db, workspace, entity_id)]

    return entries


async def platform_objects_in(db: AsyncSession, workspace: Workspace, container_id: str) -> List[Tuple[str, str]]:
    """(entity_id, kind) of the platform objects a container holds; a workspace holds all of them,
    a database also holds its account-level infrastructure only when it is the workspace's."""
    from kairos_kb.models.discovered import DiscoveredEntity

    rows = (await db.execute(select(DiscoveredEntity).where(
        DiscoveredEntity.workspace_id == workspace.id, DiscoveredEntity.origin == "platform"))).scalars().all()
    kind = container_id.split(":", 1)[0]
    if kind == "workspace":
        return [(r.entity_id, r.kind) for r in rows]
    name = container_id.split(":", 2)[-1].upper()
    out = []
    for r in rows:
        parent = str((r.attrs or {}).get("parent") or "").upper()
        if (kind == "schema" and parent == name) or (kind == "catalog" and (parent == name or parent.startswith(name + "."))):
            out.append((r.entity_id, r.kind))
    return out


async def _collect_entities(
    db: AsyncSession, workspace: Workspace, scope: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Resolve a run scope into the concrete list of entities to profile."""
    kinds = scope.get("kinds") or PROFILABLE_KINDS
    explicit = scope.get("entity_ids") or []
    limit_per_kind = scope.get("limit_per_kind")

    if explicit:
        include_descendants = scope.get("include_descendants", True)
        resolved: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for entity_id in explicit:
            for entry in await expand_target(db, workspace, entity_id, include_descendants):
                if entry["entity_id"] not in seen:
                    seen.add(entry["entity_id"])
                    resolved.append(entry)
        # Containers before contents, so a task can link to an already-profiled table.
        return sorted(resolved, key=lambda e: (e["priority"], e["entity_id"]))

    entities: List[Dict[str, Any]] = []

    def add(entity_id: str, kind: str) -> None:
        entities.append({"entity_id": entity_id, "kind": kind, "priority": KIND_PRIORITY.get(kind, 100)})

    if "workspace" in kinds:
        add(f"workspace:{workspace.name}", "workspace")

    if "catalog" in kinds:
        query = select(Catalog).where(Catalog.workspace_id == workspace.id).order_by(Catalog.name)
        if limit_per_kind:
            query = query.limit(limit_per_kind)
        for row in (await db.execute(query)).scalars().all():
            add(row.entity_id, "catalog")

    if "schema" in kinds:
        query = select(Schema).where(Schema.workspace_id == workspace.id).order_by(Schema.name)
        if limit_per_kind:
            query = query.limit(limit_per_kind)
        for row in (await db.execute(query)).scalars().all():
            add(row.entity_id, "schema")

    if "table" in kinds:
        query = select(Table).where(Table.workspace_id == workspace.id).order_by(Table.name)
        if limit_per_kind:
            query = query.limit(limit_per_kind)
        for row in (await db.execute(query)).scalars().all():
            add(row.entity_id, "table")

    if "job" in kinds:
        query = select(Job).where(Job.workspace_id == workspace.id).order_by(Job.name)
        if limit_per_kind:
            query = query.limit(limit_per_kind)
        for row in (await db.execute(query)).scalars().all():
            add(row.entity_id, "job")

    if "task" in kinds:
        query = select(Task).where(Task.workspace_id == workspace.id).order_by(Task.task_key)
        if limit_per_kind:
            query = query.limit(limit_per_kind)
        for row in (await db.execute(query)).scalars().all():
            add(row.entity_id, "task")

    from kairos_kb.enrichment.context import OBJECT_KINDS

    wanted_objects = [k for k in kinds if k in OBJECT_KINDS]
    if wanted_objects:
        per_kind: Dict[str, int] = {}
        for eid, k in sorted(await platform_objects_in(db, workspace, f"workspace:{workspace.name}")):
            if k in wanted_objects and (not limit_per_kind or per_kind.get(k, 0) < limit_per_kind):
                per_kind[k] = per_kind.get(k, 0) + 1
                add(eid, k)

    return entities


async def create_run(
    db: AsyncSession, *, workspace: Workspace, scope: Dict[str, Any]
) -> EnrichmentRun:
    """Create a run and queue its initial work items.

    In frontier mode the queue starts as just the seeds; the rest is
    discovered by expanding each entity through the entity graph after it is
    profiled, so the walk follows real relationships instead of a
    precomputed list of kinds.
    """
    run = EnrichmentRun(
        workspace_id=workspace.id,
        scope=scope,
        status="queued",
        started_at=None,
    )
    db.add(run)
    await db.flush()

    if scope.get("follow_graph", True) and scope.get("entity_ids"):
        # Seeds only. Depth 0. The frontier grows from here.
        seeds = scope["entity_ids"]
        for entity_id in seeds:
            db.add(
                EnrichmentItem(
                    run_id=run.id,
                    entity_id=entity_id,
                    kind=entity_id.split(":", 1)[0],
                    priority=KIND_PRIORITY.get(entity_id.split(":", 1)[0], 100),
                    depth=0,
                    status="pending",
                )
            )
        run.total_items = len(seeds)
    else:
        entities = await _collect_entities(db, workspace, scope)
        for entry in entities:
            db.add(
                EnrichmentItem(
                    run_id=run.id,
                    entity_id=entry["entity_id"],
                    kind=entry["kind"],
                    priority=entry["priority"],
                    depth=0,
                    status="pending",
                )
            )
        run.total_items = len(entities)

    await db.flush()
    return run


# What the frontier follows is decided per kind in _expand_frontier: a
# container's children, a job seed's tasks, the tables a task's code names,
# a table seed's writers — and stored links only when they are data flow and
# verified or corroborated. Runs and task runs are events, never followed.

# Kinds that hold arbitrarily many children. Descending into one that the
# user did not ask for spends the whole budget on its contents — a schema
# can hold 33 tables, a catalog 131.
CONTAINER_KINDS = {"workspace", "catalog", "schema"}

# Relations that represent deliberate containment descent. A container is
# only expanded when it was seeded, or when it was reached by descending
# containment from a seed. Arriving at a schema sideways — via an
# agent-emitted MEMBER_OF_SCHEMA from one of its tables, say — is context,
# not an instruction to enumerate everything inside it.
CONTAINMENT_RELATIONS = {"CONTAINS"}


# Vocabulary verbs that carry data between a pipeline and a table. The rest
# (DEPENDS_ON, TRIGGERS, RUNS_NOTEBOOK, STORED_AT, USES_EXTERNAL) are real but
# lead to things that are not the pipeline's data neighbourhood.
FLOW_RELATIONS = {"READS_TABLE", "WRITES_TABLE", "FEEDS"}


def evidence_candidates(
    kind: str, depth: int, facts: Dict[str, Any], include_upstream_producers: bool = False
) -> Tuple[List[Tuple[str, str]], List[str]]:
    """What this run's own evidence says to queue: [(entity_id, reason)], notes.

    A task: the tables its code reads or writes (a table only named — in a
    comment, a config list — is not enough). A table seed: the jobs Delta
    history shows writing it.
    """
    out: List[Tuple[str, str]] = []
    notes: List[str] = []
    if kind == "task":
        for t in facts.get("tables_in_code") or []:
            modes = set(t.get("modes") or [])
            line = (t.get("lines") or [None])[0]
            where = f"code line {line}" if line else "code"
            if "write" in modes:
                out.append((t["entity_id"], f"WRITES_TABLE · {where}"))
            elif "read" in modes:
                out.append((t["entity_id"], f"READS_TABLE · {where}"))
            else:
                notes.append(f"{t.get('table') or t['entity_id']} is only named in code ({where}), never read or written")
    if kind == "table" and (depth == 0 or include_upstream_producers):
        writers = sorted({w["entity_id"] for w in facts.get("writers") or []
                          if w.get("linkable") and w.get("entity_id")})
        out += [(job, "WRITES_TABLE · Delta history") for job in writers]
        # A view's or built table's own SQL names its sources exactly.
        for t in facts.get("tables_in_code") or []:
            if "read" in (t.get("modes") or []):
                line = (t.get("lines") or [None])[0]
                out.append((t["entity_id"], f"FEEDS · {facts.get('code_source') or 'SQL'}"
                            + (f" line {line}" if line else "")))
    return out, notes


def judge_stored_link(
    kind: str,
    entity_id: str,
    source: str,
    target: str,
    relation_type: str,
    status: str,
    corroborated: set,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Whether the frontier follows a stored link: (other, reason or None, note or None).

    Followed only when it is data flow between a pipeline and a table, and it
    is verified or corroborated by this run's evidence. An earlier agent's
    proposal on its own — "raw_ingestion writes calls" — is not enough; that
    one gets a note so the boundary is visible.
    """
    other = target if source == entity_id else source
    if status == "contradicted":
        return other, None, None
    canonical, _, _ = canonical_relation(relation_type)
    if canonical not in FLOW_RELATIONS:
        return other, None, None  # containment, a guess, or not data flow
    other_kind = other.split(":", 1)[0]
    if kind == "table" and other_kind not in ("job", "task"):
        return other, None, None  # a table seed reaches its pipelines, not sibling tables
    if kind in ("job", "task") and other_kind != "table":
        return other, None, None
    if status == "verified":
        return other, f"{canonical} · verified", None
    if other in corroborated:
        return other, f"{canonical} · corroborated", None
    return other, None, (f"{relation_type} → {other.split(':')[-1]} (proposed by an earlier run; "
                         "not in this run's code scan or Delta history)")


async def _expand_frontier(
    db: AsyncSession,
    run: EnrichmentRun,
    entity_id: str,
    depth: int,
    *,
    max_depth: int,
    max_entities: int,
    via_relation: str | None = None,
    parent_entity_id: str | None = None,
    facts: Optional[Dict[str, Any]] = None,
    include_upstream_producers: bool = False,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Queue what this entity is meaningfully connected to, on evidence.

    Returns (added, not_followed): the entries queued, each with the reason it
    was queued, and short notes on links that were deliberately not followed.

    Rules — a pipeline seed covers the pipeline, its tasks and the tables they
    read and write; it never wanders into catalogs, schemas, siblings or other
    pipelines:

      catalog/schema  children, only on a containment descent from a seed
      job             its tasks and its verified table I/O — only as the seed;
                      a job reached from elsewhere is another pipeline, so it
                      is profiled but not expanded
      task            the tables its code names (this run's scan), plus stored
                      links that are verified or corroborated by that scan
      table           as a seed: the jobs/tasks that write or read it;
                      otherwise stops (upstream producer jobs are opt-in)

    Stored links are only followed when they are data flow (the vocabulary)
    and verified, or corroborated by this run's facts. A link an earlier
    agent merely proposed — "raw_ingestion writes calls" — is not enough.
    """
    facts = facts or {}
    not_followed: List[str] = []
    if depth >= max_depth:
        return [], not_followed

    kind = entity_id.split(":", 1)[0]
    parent_kind = (parent_entity_id or "").split(":", 1)[0]

    if kind in CONTAINER_KINDS and depth > 0:
        descending = via_relation in CONTAINMENT_RELATIONS and parent_kind in CONTAINER_KINDS
        if not descending:
            return [], not_followed
    if kind == "job" and depth > 0:
        not_followed.append(f"{entity_id.split(':')[-1]} is another pipeline — profiled, not expanded")
        return [], not_followed
    if kind == "table" and depth > 0 and not include_upstream_producers:
        return [], not_followed

    queued_total = (
        await db.execute(
            select(func.count()).select_from(EnrichmentItem).where(EnrichmentItem.run_id == run.id)
        )
    ).scalar() or 0
    if queued_total >= max_entities:
        return [], not_followed

    # (target entity_id, reason) in priority order.
    candidates: List[Tuple[str, str]] = []

    # ── Containment descent (a catalog/schema seed, or descending from one) ──
    if kind in CONTAINER_KINDS:
        edges, _ = await EntityGraph(db).expand(entity_id, relations={"CONTAINS"}, limit=500)
        candidates += [(e["target"], "CONTAINS") for e in edges if e["source"] == entity_id]
        # The platform objects it holds: stages, procedures, policies … (all of them, for a workspace).
        ws = (await db.execute(select(Workspace).where(Workspace.id == run.workspace_id))).scalars().first()
        if ws is not None:
            candidates += [(eid, "CONTAINS") for eid, _ in await platform_objects_in(db, ws, entity_id)]

    # ── A job seed: its tasks ──
    if kind == "job":
        edges, _ = await EntityGraph(db).expand(entity_id, relations={"HAS_TASK"}, limit=200)
        candidates += [(e["target"], "HAS_TASK") for e in edges if e["source"] == entity_id]

    # ── This run's evidence: a task's code, a table seed's Delta history ──
    evidence, notes = evidence_candidates(kind, depth, facts, include_upstream_producers)
    candidates += evidence
    not_followed += notes
    corroborated = {other for other, _ in evidence}

    # ── Stored links: data flow only, and only on evidence ──
    if kind in ("job", "task") or (kind == "table" and depth == 0):
        rels = (await db.execute(select(DiscoveredRelation).where(
            (DiscoveredRelation.source_entity_id == entity_id) | (DiscoveredRelation.target_entity_id == entity_id)
        ))).scalars().all()
        unfollowed: List[Tuple[str, str]] = []
        for r in rels:
            other, label, note = judge_stored_link(
                kind, entity_id, r.source_entity_id, r.target_entity_id, r.relation_type, r.status, corroborated
            )
            if label:
                candidates.append((other, label))
            elif note:
                unfollowed.append((other, note))
        # A stale link to something reached on evidence anyway is not worth a note.
        reached = {other for other, _ in candidates}
        not_followed += [note for other, note in unfollowed if other not in reached]

    seen = {
        row[0]
        for row in (
            await db.execute(select(EnrichmentItem.entity_id).where(EnrichmentItem.run_id == run.id))
        ).all()
    }
    added: List[Dict[str, Any]] = []
    budget = max_entities - queued_total
    for other, reason in candidates:
        if budget <= 0:
            not_followed.append(f"budget of {max_entities} entities reached")
            break
        if other in seen or other == entity_id:
            continue
        other_kind = other.split(":", 1)[0]
        if other_kind not in PROFILABLE_KINDS:
            continue
        # Containers are only ever reached by descending into them.
        if other_kind in CONTAINER_KINDS and not reason.startswith("CONTAINS"):
            continue
        seen.add(other)
        db.add(
            EnrichmentItem(
                run_id=run.id,
                entity_id=other,
                kind=other_kind,
                priority=KIND_PRIORITY.get(other_kind, 100),
                depth=depth + 1,
                parent_entity_id=entity_id,
                via_relation=reason[:128],
                status="pending",
            )
        )
        added.append({"entity_id": other, "kind": other_kind, "relation": reason})
        budget -= 1

    if added:
        current = await db.get(EnrichmentRun, run.id)
        if current:
            current.total_items = queued_total + len(added)
    await db.flush()
    # One note per distinct link is enough.
    return added, list(dict.fromkeys(not_followed))


# ── Execution ────────────────────────────────────────────────────────


async def _process_item(
    run: EnrichmentRun,
    workspace_name: str,
    item: EnrichmentItem,
    *,
    force: bool,
) -> Tuple[str, Dict[str, Any]]:
    """Profile one entity.

    Returns (outcome, facts): outcome is 'completed', 'skipped' or 'failed';
    facts are Stage 0's findings, which the frontier expands on. They are
    gathered even for an unchanged entity, so a skip still yields evidence.
    """
    entity_id = item.entity_id

    async with async_session_factory() as db:
        context_doc = await gather_context(db, entity_id)

        # Hand the agent what its parent concluded. Profiling a task with the
        # job's purpose already established produces a profile that fits the
        # pipeline, instead of one written in isolation.
        if context_doc is not None and item.parent_entity_id:
            parent = (
                await db.execute(
                    select(EntityProfile).where(
                        EntityProfile.entity_id == item.parent_entity_id
                    )
                )
            ).scalars().first()
            if parent:
                context_doc["parent_context"] = {
                    "entity_id": parent.entity_id,
                    "kind": parent.kind,
                    "reached_via": item.via_relation,
                    "summary": parent.summary,
                    "purpose": parent.purpose,
                    "data_product": parent.data_product,
                }

    if context_doc is None:
        # The frontier reaches entities the connector never synced — a table
        # in an unscoped catalog, for instance. There is nothing to profile,
        # but that is not a failure of this run.
        await _emit(
            run.id,
            entity_id,
            "entity_skipped",
            f"Not in the warehouse, nothing to profile: {entity_id.split(':')[-1]}",
        )
        return "skipped", {}

    async def emit(event_type: str, message: str, *, level: str = "info", payload=None) -> None:
        await _emit(run.id, entity_id, event_type, message, level=level, payload=payload)

    async def telemetry(**kwargs: Any) -> None:
        await _record_telemetry(run.id, item.id, **kwargs)

    ctx = ToolContext(
        workspace_id=run.workspace_id,
        workspace_name=workspace_name,
        run_id=run.id,
        entity_id=entity_id,
        kind=item.kind,
        emit=emit,
        telemetry=telemetry,
    )

    # ── Stage 0: facts, by code ──
    facts: Dict[str, Any] = {}
    try:
        await telemetry(activity="Stage 0 · collecting facts: Delta history, statistics, known links")
        facts = await gather_facts(context_doc, workspace_name, run.workspace_id)
        recorded = 0
        if item.kind == "table":
            recorded = await record_history_writers(facts, entity_id, run.workspace_id, run.id)
            recorded += await record_code_sources(facts, entity_id, run.workspace_id, run.id)
            retired = await retire_contradicted_writes(facts, entity_id)
            if retired:
                await emit("facts", f"Retired {len(retired)} stored writer link(s) contradicted by Delta history: "
                           + ", ".join(r.split(':')[-1] for r in retired[:8]),
                           level="warning", payload={"retired": retired})
        code_note = ""
        if facts.get("code_available"):
            code_note = (f" · code read ({facts['code_chars']:,} chars): {len(facts.get('tables_in_code') or [])} "
                         f"table(s), {len(facts.get('volume_paths_in_code') or [])} volume path(s) named")
        await emit("facts", f"Facts: {facts_summary(facts)}{code_note}"
                   + (f" · {recorded} writer link(s) recorded from Delta history" if recorded else ""))
    except Exception:  # noqa: BLE001 — a missing fact never stops profiling
        logger.exception("Facts stage failed for %s", entity_id)

    # The entity's stable source plus the pipeline version: a profile made by
    # an older version of these stages is re-profiled, not skipped.
    digest = profile_digest(context_doc)

    # What agents reported about the current profile. An open report means the
    # profile is known to be wrong somewhere, so it is never skipped.
    async with async_session_factory() as db:
        reports = await open_feedback_for(db, entity_id)

    # Skip entities whose underlying snapshot has not moved since last time.
    if not force and not reports:
        async with async_session_factory() as db:
            existing = (
                await db.execute(
                    select(EntityProfile).where(EntityProfile.entity_id == entity_id)
                )
            ).scalars().first()
            if existing and existing.source_hash == digest:
                await _emit(run.id, entity_id, "entity_skipped", f"Unchanged since last profile: {entity_id}")
                return "skipped", facts

    await emit("entity_started", f"Profiling {item.kind}: {entity_id.split(':')[-1]}")

    # ── Stage 1: classification, by Jev (tables) ──
    classification: Optional[Dict[str, Any]] = None
    if item.kind == "table":
        try:
            await telemetry(activity="Stage 1 · classifying with Jev")
            classification = await classify_table(context_doc, facts)
            if classification.get("status") == "ok":
                effective, _ = effective_template(classification)
                await emit("classified",
                           f"Classified: {effective} · {classification['layer']} "
                           f"(top role {classification['role_raw']} at {classification['role_confidence']:.2f})")
            else:
                await emit("classified", f"Not classified ({classification.get('reason')}); generic template",
                           level="warning")
        except Exception:  # noqa: BLE001
            logger.exception("Classification stage failed for %s", entity_id)

    brief, light = role_brief(item.kind, classification, facts)
    if reports:
        brief = f"{brief}\n\n{feedback_brief(reports)}" if brief else feedback_brief(reports)
        await emit("facts", f"{len(reports)} report(s) from agents on the current profile — the agent will check each")
    if light:
        await emit("classified", "Light pass: empty or scratch/test table — brief profile from the facts")

    # ── Stage 2: the agent ──
    try:
        fields = await profile_entity(
            ctx, context_doc, brief=brief, max_iterations=LIGHT_ITERATIONS if light else MAX_ITERATIONS
        )
    except Exception as exc:  # noqa: BLE001 - recorded against the item
        logger.exception("Enrichment failed for %s", entity_id)
        await emit("entity_failed", f"Failed: {exc}", level="error")
        async with async_session_factory() as db:
            db_item = await db.get(EnrichmentItem, item.id)
            if db_item:
                db_item.error_message = str(exc)[:2000]
            await db.commit()
        return "failed", facts

    # ── Stage 3: verification, by code ──
    try:
        await telemetry(activity="Stage 3 · verifying the profile against the facts")
        fields, verification = await verify_profile(fields, context_doc, facts, classification)
    except Exception:  # noqa: BLE001
        logger.exception("Verification stage failed for %s", entity_id)
        verification = {"passed": None, "checks": [], "error": "verification could not run"}

    # ── Stage 4 + 2b: complete the columns — lineage first, then a batched pass ──
    if item.kind == "table" and not light:
        try:
            await telemetry(activity="Stage 4 · propagating column meanings along lineage")
            propagated = await propagate_column_docs(fields, context_doc)
            described = await describe_missing_columns(fields, context_doc, telemetry)
            if propagated or described:
                refresh_column_coverage(fields, verification, propagated, described)
                await emit("verified", f"Columns completed: {propagated} propagated from upstream, "
                                       f"{described} described by the column pass")
        except Exception:  # noqa: BLE001
            logger.exception("Column completion failed for %s", entity_id)

    # ── Reconcile the prose with what the checks established ──
    try:
        await telemetry(activity="Reconciling open questions with the checks")
        if await reconcile_with_verification(fields, verification, telemetry):
            await emit("verified", "Open questions and grain statement reconciled with the checks")
    except Exception:  # noqa: BLE001
        logger.exception("Reconcile failed for %s", entity_id)
    if verification.get("checks"):
        await emit("verified", "Verified: " + verification_summary(verification),
                   level="info" if verification.get("passed") else "warning")

    # Code-authored blocks: prose can never contradict these.
    fields["facts"] = {k: v for k, v in facts.items() if k not in ("known_relationships", "_code")} or None
    fields["classification"] = classification
    fields["verification"] = verification
    if classification and classification.get("status") == "ok":
        tags = list(fields.get("semantic_tags") or [])
        for tag in (f"role:{classification['role'].lower()}", f"layer:{classification['layer'].lower()}"):
            if tag not in tags:
                tags.append(tag)
        fields["semantic_tags"] = tags
    ctx_rejected = ctx.links_rejected

    async with async_session_factory() as db:
        await write_profile(
            db,
            workspace_id=run.workspace_id,
            entity_id=entity_id,
            kind=item.kind,
            name=context_doc.get("name") or entity_id,
            fields=fields,
            source_hash_value=digest,
            model=None,
            run_id=run.id,
        )

        # A new edge must also appear in the counterpart's YAML.
        counterparts = (
            await db.execute(
                select(DiscoveredRelation).where(
                    (DiscoveredRelation.source_entity_id == entity_id)
                    | (DiscoveredRelation.target_entity_id == entity_id)
                )
            )
        ).scalars().all()
        others = {
            r.target_entity_id if r.source_entity_id == entity_id else r.source_entity_id
            for r in counterparts
        }
        for other in others:
            if other != entity_id:
                await refresh_profile_yaml(db, other)

        await db.commit()

    await emit(
        "profile_written",
        f"Profiled {entity_id.split(':')[-1]} — {ctx.links_made} link(s), {ctx.entities_minted} new entity(ies)"
        + (f", {ctx_rejected} declined by the vocabulary" if ctx_rejected else ""),
        payload={"links": ctx.links_made, "minted": ctx.entities_minted, "declined": ctx_rejected},
    )

    # The reports were in the brief; the new profile is the answer to them.
    if reports:
        async with async_session_factory() as db:
            await mark_applied(db, [r.id for r in reports], f"Considered when re-profiling in run {run.id}")

    # Agents search the new profile from now on.
    try:
        await index_entities([entity_id])
    except Exception:  # noqa: BLE001 — the profile is written; the index can be rebuilt
        logger.exception("Could not index %s for agents", entity_id)
    return "completed", facts


async def execute_run(run_id: uuid.UUID) -> None:
    """Drive a run to completion. Safe to call again to resume a stopped run."""
    async with async_session_factory() as db:
        run = await db.get(EnrichmentRun, run_id)
        if run is None:
            return
        workspace = await db.get(Workspace, run.workspace_id)
        workspace_name = workspace.name if workspace else ""
        scope = run.scope or {}
        force = bool(scope.get("force"))
        follow_graph = bool(scope.get("follow_graph", True)) and bool(scope.get("entity_ids"))
        max_depth = int(scope.get("max_depth") or DEFAULT_MAX_DEPTH)
        # Hard ceiling on how far the frontier may grow. Without this a single
        # seed can reach the entire warehouse through its links; switching the
        # cap off leaves the walk bounded by max_depth alone.
        capped = bool(scope.get("entity_cap", True))
        max_entities = int(scope.get("max_entities") or DEFAULT_MAX_ENTITIES) if capped else UNCAPPED
        # Off by default: a table's neighbourhood is who reads and writes it,
        # not the jobs that produce its inputs.
        include_upstream = bool(scope.get("include_upstream_producers"))
        run.status = "running"
        if run.started_at is None:
            run.started_at = datetime.now(timezone.utc)

        # Reclaim items orphaned by a previous process dying mid-entity —
        # a code reload kills the asyncio task but leaves the row "running",
        # and only "pending" rows are picked up below.
        orphaned = (
            await db.execute(
                select(EnrichmentItem).where(
                    EnrichmentItem.run_id == run_id, EnrichmentItem.status == "running"
                )
            )
        ).scalars().all()
        for stale in orphaned:
            # Give up on an entity that has already failed repeatedly rather
            # than looping on it forever.
            stale.status = "failed" if stale.attempts >= 3 else "pending"
            if stale.status == "failed":
                stale.error_message = "Abandoned after repeated interruptions."
        await db.commit()

    if orphaned:
        await _emit(run_id, None, "run_started", f"Reclaimed {len(orphaned)} interrupted item(s)")

    await _emit(run_id, None, "run_started", "Enrichment run started")
    if not capped:
        await _emit(run_id, None, "frontier_expanded",
                    f"No entity cap: everything the seeds reach within {max_depth} hops will be profiled.")
    elif not scope.get("max_entities"):
        await _emit(run_id, None, "frontier_stopped",
                    f"Budget: up to {DEFAULT_MAX_ENTITIES} entities (the default). Set max_entities to cover more.")
    else:
        await _emit(run_id, None, "frontier_stopped", f"Budget: up to {max_entities} entities.")

    try:
        while True:
            if run_id in _CANCEL:
                async with async_session_factory() as db:
                    current = await db.get(EnrichmentRun, run_id)
                    if current:
                        current.status = "canceled"
                        current.finished_at = datetime.now(timezone.utc)
                        await db.commit()
                await _emit(run_id, None, "run_finished", "Run canceled")
                _CANCEL.discard(run_id)
                return

            async with async_session_factory() as db:
                # Depth first in the ordering, so the walk proceeds outward
                # level by level from the seed rather than jumping branches.
                item = (
                    await db.execute(
                        select(EnrichmentItem)
                        .where(EnrichmentItem.run_id == run_id, EnrichmentItem.status == "pending")
                        .order_by(
                            EnrichmentItem.depth,
                            EnrichmentItem.priority,
                            EnrichmentItem.entity_id,
                        )
                        .limit(1)
                    )
                ).scalars().first()

                if item is None:
                    break

                item.status = "running"
                item.attempts += 1
                item.started_at = datetime.now(timezone.utc)
                run_row = await db.get(EnrichmentRun, run_id)
                if run_row:
                    run_row.current_entity_id = item.entity_id
                    run_row.heartbeat_at = datetime.now(timezone.utc)
                    run_row.current_activity = "Gathering what the warehouse already knows"
                    run_row.current_activity_at = datetime.now(timezone.utc)
                await db.commit()
                # Detach the values we need; the session closes here.
                item_id, entity_id, kind = item.id, item.entity_id, item.kind
                item_depth, item_parent = item.depth, item.parent_entity_id
                item_via = item.via_relation

            async with async_session_factory() as db:
                run_snapshot = await db.get(EnrichmentRun, run_id)

            detached = EnrichmentItem(run_id=run_id, entity_id=entity_id, kind=kind)
            detached.id = item_id
            detached.depth = item_depth
            detached.parent_entity_id = item_parent
            detached.via_relation = item_via

            outcome, facts = await _process_item(run_snapshot, workspace_name, detached, force=force)

            # Grow the frontier from what was just profiled — on evidence:
            # this run's code scan and Delta history, and stored links only
            # when verified or corroborated by those.
            if follow_graph and outcome in ("completed", "skipped"):
                async with async_session_factory() as db:
                    current = await db.get(EnrichmentRun, run_id)
                    if current:
                        added, not_followed = await _expand_frontier(
                            db,
                            current,
                            entity_id,
                            item_depth,
                            max_depth=max_depth,
                            max_entities=max_entities,
                            via_relation=item_via,
                            parent_entity_id=item_parent,
                            facts=facts,
                            include_upstream_producers=include_upstream,
                        )
                        await db.commit()
                        name = entity_id.split(":")[-1]
                        if added:
                            reasons = "; ".join(
                                f"{a['entity_id'].split(':')[-1]} ({a['relation']})" for a in added[:6]
                            ) + (" …" if len(added) > 6 else "")
                            await _emit(
                                run_id,
                                entity_id,
                                "frontier_expanded",
                                f"Queued {len(added)} from {name}: {reasons}",
                                payload={"added": added[:20], "depth": item_depth + 1},
                            )
                        if not_followed:
                            await _emit(
                                run_id,
                                entity_id,
                                "frontier_stopped",
                                f"Not followed from {name}: {not_followed[0]}"
                                + (f" (+{len(not_followed) - 1} more)" if len(not_followed) > 1 else ""),
                                payload={"not_followed": not_followed[:30]},
                            )
                        elif (
                            not added
                            and kind in CONTAINER_KINDS
                            and item_depth > 0
                            and item_via not in CONTAINMENT_RELATIONS
                        ):
                            # Make the boundary visible rather than silent.
                            await _emit(
                                run_id,
                                entity_id,
                                "frontier_stopped",
                                f"Stopped at {kind} {name} — reached via "
                                f"{item_via}, not descended into. Seed it directly to enrich its contents.",
                                payload={"kind": kind, "via_relation": item_via},
                            )

            async with async_session_factory() as db:
                db_item = await db.get(EnrichmentItem, item_id)
                if db_item:
                    db_item.status = outcome
                    db_item.finished_at = datetime.now(timezone.utc)
                current = await db.get(EnrichmentRun, run_id)
                if current:
                    if outcome == "completed":
                        current.completed_items += 1
                    elif outcome == "failed":
                        current.failed_items += 1
                    else:
                        current.skipped_items += 1
                    current.heartbeat_at = datetime.now(timezone.utc)

                    relation_count = (
                        await db.execute(
                            select(func.count())
                            .select_from(DiscoveredRelation)
                            .where(DiscoveredRelation.run_id == run_id)
                        )
                    ).scalar() or 0
                    current.relations_discovered = relation_count
                await db.commit()

        async with async_session_factory() as db:
            current = await db.get(EnrichmentRun, run_id)
            if current:
                current.status = "completed"
                current.finished_at = datetime.now(timezone.utc)
                current.current_entity_id = None
                current.current_activity = None
                await db.commit()
        await _emit(run_id, None, "run_finished", "Enrichment run complete")

    except asyncio.CancelledError:
        async with async_session_factory() as db:
            current = await db.get(EnrichmentRun, run_id)
            if current and current.status == "running":
                current.status = "paused"
                await db.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Enrichment run %s failed", run_id)
        async with async_session_factory() as db:
            current = await db.get(EnrichmentRun, run_id)
            if current:
                current.status = "failed"
                current.error_message = str(exc)[:2000]
                current.finished_at = datetime.now(timezone.utc)
                await db.commit()
        await _emit(run_id, None, "run_finished", f"Run failed: {exc}", level="error")
    finally:
        _ACTIVE.pop(run_id, None)


def start_background(run_id: uuid.UUID) -> None:
    """Launch (or relaunch) a run in this process."""
    if run_id in _ACTIVE and not _ACTIVE[run_id].done():
        return
    _CANCEL.discard(run_id)
    _ACTIVE[run_id] = asyncio.create_task(execute_run(run_id))


def request_cancel(run_id: uuid.UUID) -> None:
    """Ask a running pass to stop after the current entity."""
    _CANCEL.add(run_id)


def is_active(run_id: uuid.UUID) -> bool:
    task = _ACTIVE.get(run_id)
    return bool(task and not task.done())
