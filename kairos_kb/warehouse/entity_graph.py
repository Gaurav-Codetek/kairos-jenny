"""Generic traversal over the Synthetic Warehouse entity graph.

One engine walks every grain — workspace, catalog, schema, table, column,
job, task, run, task run, evidence, change event, sync state — over the
typed relationships declared in :mod:`kairos_kb.warehouse.entity_map`.

Traversal is deliberately undirected: an agent starting from a failed task
run must be able to climb to its job and descend to the columns of the
table it wrote, so every incident edge is returned regardless of the
direction it was declared in.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.models.catalog import Catalog
from kairos_kb.models.change_event import ChangeEvent
from kairos_kb.models.column import Column
from kairos_kb.models.discovered import DiscoveredEntity, DiscoveredRelation
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
from kairos_kb.warehouse.entity_map import (
    DEFAULT_RELATION_GROUPS,
    RELATIONS,
    relation_names_for_groups,
)

logger = logging.getLogger(__name__)

# Kinds whose node id is the ingestion-written entity_id.
NATURAL_KINDS = {"catalog", "schema", "table", "column", "job", "task", "run", "taskrun"}
# Kinds whose node id wraps a primary key.
SYNTHETIC_KINDS = {"evidence", "change", "syncstate"}

MODEL_BY_KIND = {
    "catalog": Catalog,
    "schema": Schema,
    "table": Table,
    "column": Column,
    "job": Job,
    "task": Task,
    "run": Run,
    "taskrun": TaskRun,
}

RELATION_GROUP_BY_NAME = {r["name"]: r["group"] for r in RELATIONS}


def split_node_id(node_id: str) -> Tuple[str, str]:
    """Return (kind, remainder) for a node id."""
    kind, _, rest = node_id.partition(":")
    return kind, rest


def workspace_node_id(workspace: Workspace) -> str:
    return f"workspace:{workspace.name}"


def _entity_workspace(entity_id: str) -> str:
    """The workspace segment embedded in an entity_id."""
    parts = entity_id.split(":")
    return parts[1] if len(parts) >= 3 else ""


def _fqn(entity_id: str) -> str:
    parts = entity_id.split(":", 2)
    return parts[2] if len(parts) == 3 else entity_id


class Edge(dict):
    """A typed, directed edge. Directionality follows the entity map."""

    def __init__(self, source: str, target: str, relation: str, group: str | None = None) -> None:
        super().__init__(
            id=f"{source}|{relation}|{target}",
            source=source,
            target=target,
            relation=relation,
            # Agent-discovered relations use an open vocabulary, so their group
            # is passed explicitly rather than looked up in the seed map.
            group=group or RELATION_GROUP_BY_NAME.get(relation, "structural"),
        )


class EntityGraph:
    """Query helper bound to one session. Not safe to share across requests."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._workspace_by_id: Dict[uuid.UUID, Workspace] = {}
        self._workspace_by_name: Dict[str, Workspace] = {}
        self._workspaces_loaded = False

    # ── Workspaces ───────────────────────────────────────────────────

    async def _load_workspaces(self) -> None:
        if self._workspaces_loaded:
            return
        rows = (await self._db.execute(select(Workspace))).scalars().all()
        for workspace in rows:
            self._workspace_by_id[workspace.id] = workspace
            self._workspace_by_name[workspace.name] = workspace
        self._workspaces_loaded = True

    async def _workspace_node_for(self, workspace_id: uuid.UUID | None) -> Optional[str]:
        if workspace_id is None:
            return None
        await self._load_workspaces()
        workspace = self._workspace_by_id.get(workspace_id)
        return workspace_node_id(workspace) if workspace else None

    # ── Resolution ───────────────────────────────────────────────────

    async def resolve(self, node_id: str) -> Optional[Any]:
        """Load the ORM row behind a node id, or None if it is not stored."""
        kind, rest = split_node_id(node_id)

        if kind == "workspace":
            await self._load_workspaces()
            found = self._workspace_by_name.get(rest)
            if found:
                return found
            # Tolerate being addressed by primary key.
            try:
                return self._workspace_by_id.get(uuid.UUID(rest))
            except (ValueError, AttributeError):
                return None

        if kind in NATURAL_KINDS:
            model = MODEL_BY_KIND[kind]
            found = (
                await self._db.execute(select(model).where(model.entity_id == node_id))
            ).scalars().first()
            if found:
                return found
            # Fall through: the agent may have minted a stub for a table that
            # exists in Databricks but was never synced.

        elif kind in SYNTHETIC_KINDS:
            model = {"evidence": Evidence, "change": ChangeEvent, "syncstate": SyncState}[kind]
            try:
                pk = uuid.UUID(rest)
            except ValueError:
                return None
            return (await self._db.execute(select(model).where(model.id == pk))).scalars().first()

        # Open-vocabulary kinds the agent registered: volume, file, notebook,
        # genie_space, external_connection, and so on.
        return (
            await self._db.execute(
                select(DiscoveredEntity).where(DiscoveredEntity.entity_id == node_id)
            )
        ).scalars().first()

    # ── Expansion ────────────────────────────────────────────────────

    async def expand(
        self,
        node_id: str,
        *,
        relations: Set[str],
        limit: int,
    ) -> Tuple[List[Edge], List[Dict[str, Any]]]:
        """Return every incident edge for one node, plus truncation notes."""
        kind, _ = split_node_id(node_id)
        entity = await self.resolve(node_id)
        if entity is None:
            return [], []

        edges: List[Edge] = []
        truncations: List[Dict[str, Any]] = []

        async def collect(
            relation: str,
            query,
            *,
            to_node,
            reverse: bool = False,
        ) -> None:
            """Run a capped query and turn each row into an edge."""
            if relation not in relations:
                return
            rows = (await self._db.execute(query.limit(limit + 1))).scalars().all()
            if len(rows) > limit:
                truncations.append(
                    {"node": node_id, "relation": relation, "shown": limit, "has_more": True}
                )
                rows = rows[:limit]
            for row in rows:
                other = to_node(row)
                if not other:
                    continue
                edges.append(Edge(other, node_id, relation) if reverse else Edge(node_id, other, relation))

        # A minted stub has no structural columns of its own, so only the
        # agent-discovered edges below apply to it.
        is_stub = isinstance(entity, DiscoveredEntity)

        # ── workspace ────────────────────────────────────────────────
        if is_stub:
            pass
        elif kind == "workspace":
            await collect(
                "CONTAINS",
                select(Catalog).where(Catalog.workspace_id == entity.id).order_by(Catalog.name),
                to_node=lambda r: r.entity_id,
            )
            await collect(
                "CONTAINS",
                select(Job).where(Job.workspace_id == entity.id).order_by(Job.name),
                to_node=lambda r: r.entity_id,
            )
            await collect(
                "HAS_SYNC_STATE",
                select(SyncState).where(SyncState.workspace_id == entity.id).order_by(SyncState.domain),
                to_node=lambda r: f"syncstate:{r.id}",
            )

        # ── catalog ──────────────────────────────────────────────────
        elif kind == "catalog":
            parent = await self._workspace_node_for(entity.workspace_id)
            if parent and "CONTAINS" in relations:
                edges.append(Edge(parent, node_id, "CONTAINS"))
            await collect(
                "CONTAINS",
                select(Schema).where(Schema.catalog_id == entity.id).order_by(Schema.name),
                to_node=lambda r: r.entity_id,
            )

        # ── schema ───────────────────────────────────────────────────
        elif kind == "schema":
            if "CONTAINS" in relations:
                catalog = (
                    await self._db.execute(select(Catalog).where(Catalog.id == entity.catalog_id))
                ).scalars().first()
                if catalog:
                    edges.append(Edge(catalog.entity_id, node_id, "CONTAINS"))
            await collect(
                "CONTAINS",
                select(Table).where(Table.schema_id == entity.id).order_by(Table.name),
                to_node=lambda r: r.entity_id,
            )

        # ── table ────────────────────────────────────────────────────
        elif kind == "table":
            if "CONTAINS" in relations:
                schema = (
                    await self._db.execute(select(Schema).where(Schema.id == entity.schema_id))
                ).scalars().first()
                if schema:
                    edges.append(Edge(schema.entity_id, node_id, "CONTAINS"))
            await collect(
                "HAS_COLUMN",
                select(Column)
                .where(Column.table_id == entity.id)
                .order_by(Column.ordinal_position),
                to_node=lambda r: r.entity_id,
            )
            await self._add_lineage(node_id, edges, relations, limit, truncations)

        # ── column ───────────────────────────────────────────────────
        elif kind == "column":
            if "HAS_COLUMN" in relations:
                table = (
                    await self._db.execute(select(Table).where(Table.id == entity.table_id))
                ).scalars().first()
                if table:
                    edges.append(Edge(table.entity_id, node_id, "HAS_COLUMN"))
            await self._add_lineage(node_id, edges, relations, limit, truncations)

        # ── job ──────────────────────────────────────────────────────
        elif kind == "job":
            parent = await self._workspace_node_for(entity.workspace_id)
            if parent and "CONTAINS" in relations:
                edges.append(Edge(parent, node_id, "CONTAINS"))
            await collect(
                "HAS_TASK",
                select(Task).where(Task.job_id == entity.id).order_by(Task.task_key),
                to_node=lambda r: r.entity_id,
            )
            await collect(
                "HAS_RUN",
                select(Run).where(Run.job_id == entity.id).order_by(Run.start_time.desc()),
                to_node=lambda r: r.entity_id,
            )

        # ── task ─────────────────────────────────────────────────────
        elif kind == "task":
            job = (await self._db.execute(select(Job).where(Job.id == entity.job_id))).scalars().first()
            if job and "HAS_TASK" in relations:
                edges.append(Edge(job.entity_id, node_id, "HAS_TASK"))
            if job and "DEPENDS_ON" in relations:
                # Every task in the job, so the dependency chain can be read in
                # both directions. Reading only this task's own depends_on
                # shows what it waits on but never what waits on it, which
                # leaves the first task of a pipeline looking unconnected.
                siblings = (
                    await self._db.execute(select(Task).where(Task.job_id == entity.job_id))
                ).scalars().all()
                by_key = {s.task_key: s for s in siblings}

                # Upstream: tasks this one waits on.
                for dependency_key in _depends_on_keys(entity.depends_on):
                    upstream = by_key.get(dependency_key)
                    if upstream:
                        edges.append(Edge(upstream.entity_id, node_id, "DEPENDS_ON"))

                # Downstream: tasks that wait on this one.
                for sibling in siblings:
                    if sibling.entity_id == node_id:
                        continue
                    if entity.task_key in _depends_on_keys(sibling.depends_on):
                        edges.append(Edge(node_id, sibling.entity_id, "DEPENDS_ON"))
            await collect(
                "INSTANCE_OF",
                select(TaskRun)
                .where(TaskRun.task_id == entity.id)
                .order_by(TaskRun.start_time.desc()),
                to_node=lambda r: r.entity_id,
                reverse=True,
            )

        # ── run ──────────────────────────────────────────────────────
        elif kind == "run":
            job = (await self._db.execute(select(Job).where(Job.id == entity.job_id))).scalars().first()
            if job and "HAS_RUN" in relations:
                edges.append(Edge(job.entity_id, node_id, "HAS_RUN"))
            await collect(
                "HAS_TASK_RUN",
                select(TaskRun).where(TaskRun.run_id == entity.id).order_by(TaskRun.task_key),
                to_node=lambda r: r.entity_id,
            )

        # ── taskrun ──────────────────────────────────────────────────
        elif kind == "taskrun":
            run = (await self._db.execute(select(Run).where(Run.id == entity.run_id))).scalars().first()
            if run and "HAS_TASK_RUN" in relations:
                edges.append(Edge(run.entity_id, node_id, "HAS_TASK_RUN"))
            if "INSTANCE_OF" in relations:
                task = await self._task_for_task_run(entity, run)
                if task:
                    edges.append(Edge(node_id, task.entity_id, "INSTANCE_OF"))

        # ── evidence ─────────────────────────────────────────────────
        elif kind == "evidence":
            if "EVIDENCED_BY" in relations and entity.entity_id:
                edges.append(Edge(entity.entity_id, node_id, "EVIDENCED_BY"))
            await collect(
                "SUPPORTED_BY",
                select(ChangeEvent).where(ChangeEvent.evidence_id == entity.id),
                to_node=lambda r: f"change:{r.id}",
                reverse=True,
            )

        # ── change event ─────────────────────────────────────────────
        elif kind == "change":
            if "CHANGED_BY" in relations and entity.entity_id:
                edges.append(Edge(entity.entity_id, node_id, "CHANGED_BY"))
            if "SUPPORTED_BY" in relations and entity.evidence_id:
                edges.append(Edge(node_id, f"evidence:{entity.evidence_id}", "SUPPORTED_BY"))

        # ── sync state ───────────────────────────────────────────────
        elif kind == "syncstate":
            parent = await self._workspace_node_for(entity.workspace_id)
            if parent and "HAS_SYNC_STATE" in relations:
                edges.append(Edge(parent, node_id, "HAS_SYNC_STATE"))

        # Relationships the enrichment agent asserted. These use an open
        # vocabulary and can attach to any node, including ones the agent
        # minted itself, so they are collected for every kind.
        if "DISCOVERED" in relations:
            discovered = (
                await self._db.execute(
                    select(DiscoveredRelation)
                    .where(
                        DiscoveredRelation.status != "contradicted",
                        or_(
                            DiscoveredRelation.source_entity_id == node_id,
                            DiscoveredRelation.target_entity_id == node_id,
                        )
                    )
                    .limit(limit * 2 + 1)
                )
            ).scalars().all()

            if len(discovered) > limit * 2:
                truncations.append(
                    {"node": node_id, "relation": "DISCOVERED", "shown": limit * 2, "has_more": True}
                )
                discovered = discovered[: limit * 2]

            for row in discovered:
                edges.append(
                    Edge(
                        row.source_entity_id,
                        row.target_entity_id,
                        row.relation_type,
                        group="discovered",
                    )
                )

        # Provenance hangs off every entity that owns an entity_id.
        if kind in NATURAL_KINDS and not is_stub:
            await collect(
                "EVIDENCED_BY",
                select(Evidence)
                .where(Evidence.entity_id == node_id)
                .order_by(Evidence.observed_at.desc()),
                to_node=lambda r: f"evidence:{r.id}",
            )
            await collect(
                "CHANGED_BY",
                select(ChangeEvent)
                .where(ChangeEvent.entity_id == node_id)
                .order_by(ChangeEvent.detected_at.desc()),
                to_node=lambda r: f"change:{r.id}",
            )

        return edges, truncations

    async def _add_lineage(
        self,
        node_id: str,
        edges: List[Edge],
        relations: Set[str],
        limit: int,
        truncations: List[Dict[str, Any]],
    ) -> None:
        """Attach FLOWS_TO edges in both directions for a table or column."""
        if "FLOWS_TO" not in relations:
            return
        rows = (
            await self._db.execute(
                select(LineageEdge)
                .where(
                    or_(
                        LineageEdge.source_entity_id == node_id,
                        LineageEdge.target_entity_id == node_id,
                    )
                )
                .limit(limit * 2 + 1)
            )
        ).scalars().all()

        if len(rows) > limit * 2:
            truncations.append(
                {"node": node_id, "relation": "FLOWS_TO", "shown": limit * 2, "has_more": True}
            )
            rows = rows[: limit * 2]

        for row in rows:
            # Self-referential lineage carries no navigable information.
            if row.source_entity_id == row.target_entity_id:
                continue
            edges.append(Edge(row.source_entity_id, row.target_entity_id, "FLOWS_TO"))

    async def _task_for_task_run(self, task_run: TaskRun, run: Run | None) -> Optional[Task]:
        """Resolve a task run to its task definition.

        ``task_runs.task_id`` is only populated for a small fraction of rows,
        so fall back to matching on the owning job plus task_key.
        """
        if task_run.task_id:
            found = (
                await self._db.execute(select(Task).where(Task.id == task_run.task_id))
            ).scalars().first()
            if found:
                return found
        if run is None:
            return None
        return (
            await self._db.execute(
                select(Task).where(Task.job_id == run.job_id, Task.task_key == task_run.task_key)
            )
        ).scalars().first()

    # ── Traversal ────────────────────────────────────────────────────

    async def traverse(
        self,
        root: str,
        *,
        depth: int,
        relation_groups: Sequence[str] | None = None,
        limit_per_relation: int = 25,
    ) -> Dict[str, Any]:
        """Breadth-first walk out from ``root`` across the entity graph."""
        groups = list(relation_groups or DEFAULT_RELATION_GROUPS)
        relations = relation_names_for_groups(groups)

        hops: Dict[str, int] = {root: 0}
        all_edges: Dict[str, Edge] = {}
        truncations: List[Dict[str, Any]] = []

        frontier = [root]
        expanded: Set[str] = set()

        for hop in range(1, depth + 1):
            next_frontier: List[str] = []
            for node_id in frontier:
                edges, node_truncations = await self.expand(
                    node_id, relations=relations, limit=limit_per_relation
                )
                expanded.add(node_id)
                truncations.extend(node_truncations)
                for edge in edges:
                    all_edges[edge["id"]] = edge
                    for endpoint in (edge["source"], edge["target"]):
                        if endpoint not in hops:
                            hops[endpoint] = hop
                            next_frontier.append(endpoint)
            frontier = next_frontier
            if not frontier:
                break

        # Close the graph. Nodes on the outer frontier were added but never
        # expanded, so edges *between* them were never collected — a pipeline
        # whose tasks all sit at the frontier renders as a fan of siblings
        # with none of the ordering between them. Expand them for edges only;
        # no new nodes are admitted, so the size is unchanged.
        for node_id in list(hops):
            if node_id in expanded:
                continue
            edges, _ = await self.expand(node_id, relations=relations, limit=limit_per_relation)
            for edge in edges:
                if edge["source"] in hops and edge["target"] in hops:
                    all_edges[edge["id"]] = edge

        nodes = await self.materialize(set(hops))
        for node in nodes:
            node["depth"] = hops.get(node["id"], 0)
            node["is_root"] = node["id"] == root

        # Frontier nodes were never expanded, so they always hide more.
        max_hop = max(hops.values()) if hops else 0
        expanded = {n for n, d in hops.items() if d < max_hop} if depth > 0 else set()
        for node in nodes:
            node["expandable"] = node["id"] not in expanded or any(
                t["node"] == node["id"] for t in truncations
            )

        edges = [e for e in all_edges.values() if e["source"] in hops and e["target"] in hops]

        return {
            "root": root,
            "depth": depth,
            "relation_groups": groups,
            "nodes": nodes,
            "edges": edges,
            "truncations": truncations,
            "stats": {
                "nodes": len(nodes),
                "edges": len(edges),
                "by_kind": _count_by(nodes, "kind"),
                "by_relation": _count_by(edges, "relation"),
                "truncated": bool(truncations),
            },
        }

    # ── Materialization ──────────────────────────────────────────────

    async def materialize(self, node_ids: Set[str]) -> List[Dict[str, Any]]:
        """Turn node ids into display payloads, batched per kind."""
        by_kind: Dict[str, List[str]] = defaultdict(list)
        for node_id in node_ids:
            by_kind[split_node_id(node_id)[0]].append(node_id)

        payloads: Dict[str, Dict[str, Any]] = {}

        if "workspace" in by_kind:
            await self._load_workspaces()
            for node_id in by_kind["workspace"]:
                workspace = await self.resolve(node_id)
                payloads[node_id] = _workspace_payload(node_id, workspace)

        for kind in NATURAL_KINDS & by_kind.keys():
            model = MODEL_BY_KIND[kind]
            ids = by_kind[kind]
            rows = (
                await self._db.execute(select(model).where(model.entity_id.in_(ids)))
            ).scalars().all()
            found = {row.entity_id: row for row in rows}
            for node_id in ids:
                payloads[node_id] = _entity_payload(kind, node_id, found.get(node_id))

        for kind in SYNTHETIC_KINDS & by_kind.keys():
            model = {"evidence": Evidence, "change": ChangeEvent, "syncstate": SyncState}[kind]
            pks = []
            for node_id in by_kind[kind]:
                try:
                    pks.append(uuid.UUID(split_node_id(node_id)[1]))
                except ValueError:
                    continue
            rows = (
                (await self._db.execute(select(model).where(model.id.in_(pks)))).scalars().all()
                if pks
                else []
            )
            found = {f"{kind}:{row.id}": row for row in rows}
            for node_id in by_kind[kind]:
                payloads[node_id] = _entity_payload(kind, node_id, found.get(node_id))

        # Nodes the agent minted, plus synced kinds whose row is missing.
        unresolved = [
            n for n in node_ids if n not in payloads or payloads[n].get("known") is False
        ]
        if unresolved:
            stubs = (
                await self._db.execute(
                    select(DiscoveredEntity).where(DiscoveredEntity.entity_id.in_(unresolved))
                )
            ).scalars().all()
            for stub in stubs:
                payloads[stub.entity_id] = {
                    "id": stub.entity_id,
                    "kind": stub.kind,
                    "label": stub.name,
                    "sublabel": stub.full_name or stub.entity_id,
                    # Real, but known only because the agent found it.
                    "known": True,
                    "discovered": True,
                    "status": None,
                    "attrs": {"origin": stub.origin, "rationale": stub.rationale, **(stub.attrs or {})},
                }

        # Anything still unresolved (lineage pointing outside the synced scope).
        for node_id in node_ids:
            if node_id not in payloads:
                payloads[node_id] = _entity_payload(split_node_id(node_id)[0], node_id, None)

        return list(payloads.values())

    # ── Per-entity detail ────────────────────────────────────────────

    async def entity_detail(self, node_id: str) -> Dict[str, Any]:
        """Full attributes plus exact per-relation neighbour counts."""
        kind, _ = split_node_id(node_id)
        entity = await self.resolve(node_id)

        edges, _ = await self.expand(
            node_id,
            relations={r["name"] for r in RELATIONS},
            # High cap: this is one node, and agents need true counts.
            limit=500,
        )

        neighbours: Dict[str, List[str]] = defaultdict(list)
        # Carry the group from the edge itself. Re-deriving it from the
        # relation name would mislabel every agent-discovered relation, whose
        # names are open vocabulary and absent from the seed map.
        group_by_relation: Dict[str, str] = {}
        for edge in edges:
            other = edge["target"] if edge["source"] == node_id else edge["source"]
            neighbours[edge["relation"]].append(other)
            group_by_relation[edge["relation"]] = edge["group"]

        relation_summary = [
            {
                "relation": relation,
                "group": group_by_relation.get(relation, "structural"),
                "count": len(targets),
                "sample": targets[:10],
            }
            for relation, targets in sorted(neighbours.items())
        ]

        return {
            "id": node_id,
            "kind": kind,
            "known": entity is not None,
            "attributes": _full_attributes(kind, entity),
            "relations": relation_summary,
            "relation_total": sum(len(t) for t in neighbours.values()),
        }

    # ── Search ───────────────────────────────────────────────────────

    async def search(
        self, query: str, *, kinds: Sequence[str] | None = None, limit: int = 30
    ) -> List[Dict[str, Any]]:
        """Find entities by name across every grain — the agent's entry point."""
        wanted = set(kinds) if kinds else set(NATURAL_KINDS)
        pattern = f"%{query}%"
        results: List[Dict[str, Any]] = []

        searchable = [
            ("catalog", Catalog, Catalog.name),
            ("schema", Schema, Schema.full_name),
            ("table", Table, Table.full_name),
            ("column", Column, Column.full_name),
            ("job", Job, Job.name),
            ("task", Task, Task.task_key),
            ("run", Run, Run.entity_id),
            ("taskrun", TaskRun, TaskRun.task_key),
        ]

        for kind, model, field in searchable:
            if kind not in wanted:
                continue
            rows = (
                await self._db.execute(select(model).where(field.ilike(pattern)).limit(limit))
            ).scalars().all()
            for row in rows:
                results.append(_entity_payload(kind, row.entity_id, row))

        return results[:limit]


# ── Payload builders ─────────────────────────────────────────────────


def _workspace_payload(node_id: str, workspace: Workspace | None) -> Dict[str, Any]:
    if workspace is None:
        return {
            "id": node_id,
            "kind": "workspace",
            "label": split_node_id(node_id)[1],
            "sublabel": "",
            "known": False,
            "attrs": {},
        }
    return {
        "id": node_id,
        "kind": "workspace",
        "label": workspace.name,
        "sublabel": workspace.host,
        "known": True,
        "attrs": {
            "cloud": workspace.cloud,
            "region": workspace.region,
            "status": workspace.status,
            "last_synced_at": workspace.last_synced_at.isoformat()
            if workspace.last_synced_at
            else None,
        },
    }


def _entity_payload(kind: str, node_id: str, entity: Any) -> Dict[str, Any]:
    """Compact payload for graph rendering. Unresolved nodes degrade gracefully."""
    if entity is None:
        fqn = _fqn(node_id)
        return {
            "id": node_id,
            "kind": kind,
            "label": fqn.split(".")[-1] if fqn else node_id,
            "sublabel": fqn,
            "known": False,
            "attrs": {},
        }

    if kind == "catalog":
        return _payload(node_id, kind, entity.name, entity.catalog_type or "", {"owner": entity.owner})
    if kind == "schema":
        return _payload(node_id, kind, entity.name, entity.full_name, {"owner": entity.owner})
    if kind == "table":
        return _payload(
            node_id,
            kind,
            entity.name,
            entity.full_name,
            {
                "table_type": entity.table_type,
                "format": entity.data_source_format,
                "owner": entity.owner,
                "row_count": entity.row_count,
            },
        )
    if kind == "column":
        return _payload(
            node_id,
            kind,
            entity.name,
            entity.full_name,
            {
                "data_type": entity.data_type,
                "nullable": entity.is_nullable,
                "position": entity.ordinal_position,
            },
        )
    if kind == "job":
        return _payload(
            node_id,
            kind,
            entity.name,
            f"job {entity.source_native_id}",
            {"owner": entity.owner, "max_concurrent_runs": entity.max_concurrent_runs},
        )
    if kind == "task":
        return _payload(
            node_id,
            kind,
            entity.task_key,
            entity.task_type or "",
            {"notebook_path": entity.notebook_path},
        )
    if kind == "run":
        return _payload(
            node_id,
            kind,
            entity.run_name or f"run {entity.source_native_id}",
            entity.result_state or entity.state,
            {
                "state": entity.state,
                "result_state": entity.result_state,
                "start_time": entity.start_time.isoformat() if entity.start_time else None,
                "duration_ms": entity.execution_duration_ms,
                "error_message": entity.error_message,
                "run_page_url": entity.run_page_url,
            },
            status=entity.result_state,
        )
    if kind == "taskrun":
        return _payload(
            node_id,
            kind,
            entity.task_key,
            entity.result_state or entity.state,
            {
                "state": entity.state,
                "result_state": entity.result_state,
                "attempt_number": entity.attempt_number,
                "source_native_id": entity.source_native_id,
                "error_message": entity.error_message,
            },
            status=entity.result_state,
        )
    if kind == "evidence":
        return _payload(
            node_id,
            kind,
            entity.source_type,
            entity.entity_id,
            {
                "content_hash": entity.content_hash[:12],
                "observed_at": entity.observed_at.isoformat(),
            },
        )
    if kind == "change":
        return _payload(
            node_id,
            kind,
            entity.change_type,
            entity.field_name or entity.entity_type,
            {
                "entity_type": entity.entity_type,
                "field_name": entity.field_name,
                "old_value": entity.old_value,
                "new_value": entity.new_value,
                "detected_at": entity.detected_at.isoformat(),
            },
        )
    if kind == "syncstate":
        return _payload(
            node_id,
            kind,
            entity.domain,
            entity.status,
            {
                "status": entity.status,
                "items_synced": entity.items_synced,
                "last_sync_at": entity.last_sync_at.isoformat() if entity.last_sync_at else None,
                "error_message": entity.error_message,
            },
            status="FAILED" if entity.status == "error" else None,
        )

    return _payload(node_id, kind, node_id, "", {})


def _payload(
    node_id: str,
    kind: str,
    label: str,
    sublabel: str,
    attrs: Dict[str, Any],
    *,
    status: str | None = None,
) -> Dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "label": label,
        "sublabel": sublabel,
        "known": True,
        "status": status,
        "attrs": attrs,
    }


def _full_attributes(kind: str, entity: Any) -> Dict[str, Any]:
    """Every scalar column on the row, for the detail panel."""
    if entity is None:
        return {}
    result: Dict[str, Any] = {}
    for column in entity.__table__.columns:
        value = getattr(entity, column.name, None)
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        result[column.name] = value
    return result


def _depends_on_keys(depends_on: Any) -> List[str]:
    """Databricks writes depends_on as [{"task_key": "..."}]; tolerate strings."""
    if not depends_on:
        return []
    keys: List[str] = []
    for item in depends_on:
        if isinstance(item, dict):
            key = item.get("task_key")
            if key:
                keys.append(key)
        elif isinstance(item, str):
            keys.append(item)
    return keys


def _count_by(items: Iterable[Dict[str, Any]], field: str) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for item in items:
        counts[item.get(field, "unknown")] += 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
