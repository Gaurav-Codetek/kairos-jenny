"""Lineage visualization endpoints.

Serves the Knowledge Catalog sidebar and the scoped neighborhood graph.

Two things make this non-trivial and are handled here rather than in the UI:

1. Column-level lineage is rolled up into table-level edges. Databricks
   emits far more ``system.access.column_lineage`` rows than table lineage
   rows, so rolling up materially increases observed table connectivity.
2. Lineage frequently references tables outside the synced catalog scope.
   Those endpoints are kept as ``known=False`` nodes instead of being
   dropped, so the graph shows the real topology and makes the gap visible.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.db.engine import get_db
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.change_event import ChangeEvent
from kairos_kb.models.column import Column
from kairos_kb.models.evidence import Evidence
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.models.schema import Schema
from kairos_kb.models.table import Table

router = APIRouter(prefix="/lineage", tags=["lineage"])

# Hard ceiling on traversal depth so one click cannot fan out into the
# entire warehouse.
MAX_DEPTH = 10


# ── Entity ID helpers ────────────────────────────────────────────────
# Entity IDs are colon-joined: "<kind>:<workspace>:<fully.qualified.name>"


def _split_entity(entity_id: str) -> Tuple[str, str, str]:
    """Split an entity_id into (kind, workspace, fqn). Tolerant of junk."""
    parts = entity_id.split(":", 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return "", "", entity_id


def _as_table_entity(entity_id: str) -> Optional[str]:
    """Normalize a table or column entity_id to its table entity_id."""
    kind, workspace, fqn = _split_entity(entity_id)
    if kind == "table":
        return entity_id
    if kind == "column" and "." in fqn:
        return f"table:{workspace}:{fqn.rsplit('.', 1)[0]}"
    return None


def _fqn_parts(entity_id: str) -> Tuple[str, str, str]:
    """Return (catalog, schema, table) parsed from a table entity_id."""
    _, _, fqn = _split_entity(entity_id)
    bits = fqn.split(".")
    while len(bits) < 3:
        bits.append("")
    return bits[0], bits[1], ".".join(bits[2:])


# ── Lineage index ────────────────────────────────────────────────────


class LineageIndex:
    """In-memory table-level adjacency built from all lineage edges.

    The edge table is small (hundreds of rows), so building this per
    request is cheaper than maintaining a denormalized table.
    """

    def __init__(self) -> None:
        self.upstream: Dict[str, Set[str]] = defaultdict(set)
        self.downstream: Dict[str, Set[str]] = defaultdict(set)
        self.edges: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def add(self, source: str, target: str, edge: LineageEdge) -> None:
        self.upstream[target].add(source)
        self.downstream[source].add(target)

        key = (source, target)
        meta: Dict[str, Any] | None = self.edges.get(key)
        if meta is None:
            meta = {
                "source": source,
                "target": target,
                "via": set(),
                "column_pairs": 0,
                "confidence": edge.confidence,
                "transformation": edge.transformation,
                "observed_at": edge.observed_at,
            }
            self.edges[key] = meta

        meta["via"].add(edge.source_type)
        if edge.source_type == "COLUMN":
            meta["column_pairs"] += 1
        if edge.transformation and not meta["transformation"]:
            meta["transformation"] = edge.transformation
        # Keep the most conservative confidence observed for this pair.
        meta["confidence"] = min(meta["confidence"], edge.confidence)
        if edge.observed_at and (not meta["observed_at"] or edge.observed_at > meta["observed_at"]):
            meta["observed_at"] = edge.observed_at

    def degree(self, node: str) -> Tuple[int, int]:
        return len(self.upstream.get(node, ())), len(self.downstream.get(node, ()))

    def neighbors(self, node: str, direction: str) -> Set[str]:
        side = self.upstream if direction == "upstream" else self.downstream
        return side.get(node, set())


async def _load_index(db: AsyncSession, workspace_id: uuid.UUID | None = None) -> LineageIndex:
    """Build the table-level lineage adjacency, rolling up column edges."""
    query = select(LineageEdge)
    if workspace_id:
        query = query.where(LineageEdge.workspace_id == workspace_id)

    result = await db.execute(query)
    index = LineageIndex()

    for edge in result.scalars().all():
        source = _as_table_entity(edge.source_entity_id)
        target = _as_table_entity(edge.target_entity_id)
        # Self-loops carry no topology; Databricks emits many for tables
        # rewritten in place (MERGE / INSERT OVERWRITE).
        if not source or not target or source == target:
            continue
        index.add(source, target, edge)

    return index


def _traverse(index: LineageIndex, root: str, depth: int, direction: str) -> Dict[str, int]:
    """Breadth-first walk in one direction. Returns {entity_id: hop_distance}."""
    seen: Dict[str, int] = {root: 0}
    frontier = [root]

    for hop in range(1, depth + 1):
        next_frontier: List[str] = []
        for node in frontier:
            for neighbor in index.neighbors(node, direction):
                if neighbor not in seen:
                    seen[neighbor] = hop
                    next_frontier.append(neighbor)
        frontier = next_frontier
        if not frontier:
            break

    return seen


async def _table_metadata(db: AsyncSession, entity_ids: Set[str]) -> Dict[str, Table]:
    """Fetch the Table rows backing a set of entity IDs, where they exist."""
    if not entity_ids:
        return {}
    result = await db.execute(select(Table).where(Table.entity_id.in_(entity_ids)))
    return {t.entity_id: t for t in result.scalars().all()}


def _node_payload(
    entity_id: str,
    *,
    index: LineageIndex,
    table: Table | None,
    direction: str,
    depth: int,
    included: Set[str],
) -> Dict[str, Any]:
    """Shape one graph node, flagging whether it can still be expanded."""
    catalog_name, schema_name, table_name = _fqn_parts(entity_id)
    up_count, down_count = index.degree(entity_id)

    hidden_upstream = len(index.neighbors(entity_id, "upstream") - included)
    hidden_downstream = len(index.neighbors(entity_id, "downstream") - included)

    return {
        "id": entity_id,
        "entity_id": entity_id,
        "label": table.name if table else (table_name or entity_id),
        "full_name": table.full_name if table else f"{catalog_name}.{schema_name}.{table_name}",
        "catalog": catalog_name,
        "schema": schema_name,
        "table_type": table.table_type if table else None,
        # Tables outside the synced catalog scope still appear, dimmed.
        "known": table is not None,
        "table_id": str(table.id) if table else None,
        "comment": table.comment if table else None,
        "row_count": table.row_count if table else None,
        "direction": direction,
        "depth": depth,
        "upstream_count": up_count,
        "downstream_count": down_count,
        "hidden_upstream": hidden_upstream,
        "hidden_downstream": hidden_downstream,
        "expandable": bool(hidden_upstream or hidden_downstream),
    }


# ── Knowledge Catalog sidebar ────────────────────────────────────────


@router.get("/catalog-tree")
async def get_catalog_tree(
    workspace_id: uuid.UUID | None = None,
    lineage_only: bool = Query(False, description="Only return tables that have lineage edges"),
    db: AsyncSession = Depends(get_db),
):
    """Catalog → schema → table tree for the Knowledge Catalog sidebar.

    Each table is annotated with its lineage degree so the UI can show
    which entities will actually produce a graph.
    """
    index = await _load_index(db, workspace_id)

    catalog_query = select(Catalog).order_by(Catalog.name)
    schema_query = select(Schema).order_by(Schema.name)
    table_query = select(Table).order_by(Table.name)
    if workspace_id:
        catalog_query = catalog_query.where(Catalog.workspace_id == workspace_id)
        schema_query = schema_query.where(Schema.workspace_id == workspace_id)
        table_query = table_query.where(Table.workspace_id == workspace_id)

    catalogs = (await db.execute(catalog_query)).scalars().all()
    schemas = (await db.execute(schema_query)).scalars().all()
    tables = (await db.execute(table_query)).scalars().all()

    tables_by_schema: Dict[uuid.UUID, List[Dict[str, Any]]] = defaultdict(list)
    for table in tables:
        up_count, down_count = index.degree(table.entity_id)
        if lineage_only and not (up_count or down_count):
            continue
        tables_by_schema[table.schema_id].append(
            {
                "id": str(table.id),
                "entity_id": table.entity_id,
                "name": table.name,
                "full_name": table.full_name,
                "table_type": table.table_type,
                "upstream_count": up_count,
                "downstream_count": down_count,
                "has_lineage": bool(up_count or down_count),
            }
        )

    schemas_by_catalog: Dict[uuid.UUID, List[Dict[str, Any]]] = defaultdict(list)
    for schema in schemas:
        schema_tables = tables_by_schema.get(schema.id, [])
        if lineage_only and not schema_tables:
            continue
        schemas_by_catalog[schema.catalog_id].append(
            {
                "id": str(schema.id),
                "entity_id": schema.entity_id,
                "name": schema.name,
                "full_name": schema.full_name,
                "table_count": len(schema_tables),
                "lineage_table_count": sum(1 for t in schema_tables if t["has_lineage"]),
                "tables": schema_tables,
            }
        )

    tree: List[Dict[str, Any]] = []
    for catalog in catalogs:
        catalog_schemas = schemas_by_catalog.get(catalog.id, [])
        if lineage_only and not catalog_schemas:
            continue
        tree.append(
            {
                "id": str(catalog.id),
                "entity_id": catalog.entity_id,
                "name": catalog.name,
                "catalog_type": catalog.catalog_type,
                "schema_count": len(catalog_schemas),
                "table_count": sum(s["table_count"] for s in catalog_schemas),
                "lineage_table_count": sum(s["lineage_table_count"] for s in catalog_schemas),
                "schemas": catalog_schemas,
            }
        )

    known_entity_ids = {t.entity_id for t in tables}
    lineage_nodes = set(index.upstream) | set(index.downstream)

    # Every entity that participates in lineage, grouped by catalog. Lineage
    # is pulled metastore-wide from system.access.*, so it routinely covers
    # catalogs the catalog sync never scoped in — without this list those
    # subgraphs would be unreachable from the sidebar.
    roots_by_catalog: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for node_id in lineage_nodes:
        node_catalog, node_schema, node_table = _fqn_parts(node_id)
        up_count, down_count = index.degree(node_id)
        roots_by_catalog[node_catalog].append(
            {
                "entity_id": node_id,
                "name": node_table,
                "schema": node_schema,
                "full_name": f"{node_catalog}.{node_schema}.{node_table}",
                "known": node_id in known_entity_ids,
                "upstream_count": up_count,
                "downstream_count": down_count,
                "degree": up_count + down_count,
            }
        )

    lineage_roots = [
        {
            "catalog": catalog_name,
            "entity_count": len(entries),
            "known_count": sum(1 for e in entries if e["known"]),
            "entities": sorted(entries, key=lambda e: (-e["degree"], e["full_name"])),
        }
        for catalog_name, entries in sorted(roots_by_catalog.items())
    ]

    return {
        "catalogs": tree,
        "lineage_roots": lineage_roots,
        "stats": {
            "catalogs": len(tree),
            "schemas": sum(len(c["schemas"]) for c in tree),
            "tables": sum(c["table_count"] for c in tree),
            "tables_with_lineage": sum(c["lineage_table_count"] for c in tree),
            "lineage_edges": len(index.edges),
            # Lineage endpoints that were never synced into the catalog.
            "external_lineage_nodes": len(lineage_nodes - known_entity_ids),
        },
    }


# ── Scoped neighborhood graph ────────────────────────────────────────


@router.get("/neighborhood")
async def get_neighborhood(
    entity_id: str = Query(..., description="Root table or column entity_id"),
    upstream: int = Query(2, ge=0, le=MAX_DEPTH),
    downstream: int = Query(2, ge=0, le=MAX_DEPTH),
    workspace_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Return the lineage neighborhood around one entity.

    Walks ``upstream`` hops backwards and ``downstream`` hops forwards.
    Nodes report how many neighbors remain hidden so the UI can offer a
    per-node expand affordance instead of rendering the whole warehouse.
    """
    index = await _load_index(db, workspace_id)
    root = _as_table_entity(entity_id) or entity_id

    upstream_hops = _traverse(index, root, upstream, "upstream")
    downstream_hops = _traverse(index, root, downstream, "downstream")

    included: Set[str] = set(upstream_hops) | set(downstream_hops)
    metadata = await _table_metadata(db, included)

    nodes: List[Dict[str, Any]] = []
    for node_id in included:
        in_up = node_id in upstream_hops
        in_down = node_id in downstream_hops

        if node_id == root:
            direction = "root"
            depth = 0
        elif in_up and in_down:
            # Reachable both ways — a cycle or a diamond around the root.
            direction = "both"
            depth = min(upstream_hops[node_id], downstream_hops[node_id])
        elif in_up:
            direction = "upstream"
            depth = upstream_hops[node_id]
        else:
            direction = "downstream"
            depth = downstream_hops[node_id]

        nodes.append(
            _node_payload(
                node_id,
                index=index,
                table=metadata.get(node_id),
                direction=direction,
                depth=depth,
                included=included,
            )
        )

    # Include every edge between selected nodes, not only those the walk
    # traversed, so cross-links inside the neighborhood stay visible.
    edges: List[Dict[str, Any]] = []
    for (source, target), meta in index.edges.items():
        if source in included and target in included:
            edges.append(
                {
                    "id": f"{source}->{target}",
                    "source": source,
                    "target": target,
                    "via": sorted(meta["via"]),
                    "column_pairs": meta["column_pairs"],
                    "confidence": meta["confidence"],
                    "transformation": meta["transformation"],
                }
            )

    root_table = metadata.get(root)
    root_catalog, root_schema, root_name = _fqn_parts(root)

    return {
        "root": {
            "entity_id": root,
            "label": root_table.name if root_table else root_name,
            "full_name": root_table.full_name if root_table else f"{root_catalog}.{root_schema}.{root_name}",
            "known": root_table is not None,
        },
        "nodes": nodes,
        "edges": edges,
        "depth": {"upstream": upstream, "downstream": downstream},
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "external_nodes": sum(1 for n in nodes if not n["known"]),
            "truncated": any(n["expandable"] for n in nodes),
        },
    }


# ── Node context: how this table ties to the rest of the warehouse ───


@router.get("/context")
async def get_node_context(
    entity_id: str = Query(..., description="Table entity_id"),
    db: AsyncSession = Depends(get_db),
):
    """Everything the Synthetic Warehouse knows about one table.

    This is the join point between the graph and the rest of the
    warehouse: structural metadata, columns, change history, evidence,
    and the column-level lineage underlying its table edges.
    """
    root = _as_table_entity(entity_id) or entity_id

    table = (await db.execute(select(Table).where(Table.entity_id == root))).scalars().first()

    catalog_name, schema_name, table_name = _fqn_parts(root)

    columns: List[Dict[str, Any]] = []
    if table:
        column_rows = (
            await db.execute(
                select(Column).where(Column.table_id == table.id).order_by(Column.ordinal_position)
            )
        ).scalars().all()
        columns = [
            {
                "name": c.name,
                "data_type": c.data_type,
                "full_data_type": c.full_data_type,
                "is_nullable": c.is_nullable,
                "is_partition_column": c.is_partition_column,
                "comment": c.comment,
                "ordinal_position": c.ordinal_position,
            }
            for c in column_rows
        ]

    changes = (
        await db.execute(
            select(ChangeEvent)
            .where(ChangeEvent.entity_id == root)
            .order_by(ChangeEvent.detected_at.desc())
            .limit(25)
        )
    ).scalars().all()

    evidence = (
        await db.execute(
            select(Evidence)
            .where(Evidence.entity_id == root)
            .order_by(Evidence.observed_at.desc())
            .limit(10)
        )
    ).scalars().all()

    # Column-level lineage touching this table, in both directions. This is
    # the detail that the rolled-up table edges hide.
    prefix = f"column:{_split_entity(root)[1]}:{catalog_name}.{schema_name}.{table_name}."
    column_edges = (
        await db.execute(
            select(LineageEdge).where(
                LineageEdge.source_type == "COLUMN",
                (LineageEdge.source_entity_id.startswith(prefix))
                | (LineageEdge.target_entity_id.startswith(prefix)),
            )
        )
    ).scalars().all()

    column_lineage = []
    for edge in column_edges:
        outgoing = edge.source_entity_id.startswith(prefix)
        local_id = edge.source_entity_id if outgoing else edge.target_entity_id
        remote_id = edge.target_entity_id if outgoing else edge.source_entity_id
        column_lineage.append(
            {
                "direction": "downstream" if outgoing else "upstream",
                "column": local_id.rsplit(".", 1)[-1],
                "remote_entity_id": remote_id,
                "remote_full_name": _split_entity(remote_id)[2],
                "transformation": edge.transformation,
            }
        )

    return {
        "entity_id": root,
        "known": table is not None,
        "table": {
            "id": str(table.id) if table else None,
            "name": table.name if table else table_name,
            "full_name": table.full_name if table else f"{catalog_name}.{schema_name}.{table_name}",
            "catalog": catalog_name,
            "schema": schema_name,
            "table_type": table.table_type if table else None,
            "data_source_format": table.data_source_format if table else None,
            "owner": table.owner if table else None,
            "comment": table.comment if table else None,
            "storage_location": table.storage_location if table else None,
            "row_count": table.row_count if table else None,
            "size_bytes": table.size_bytes if table else None,
            "first_seen_at": table.first_seen_at.isoformat() if table else None,
            "last_seen_at": table.last_seen_at.isoformat() if table else None,
        },
        "columns": columns,
        "column_count": len(columns),
        "changes": [
            {
                "change_type": c.change_type,
                "field_name": c.field_name,
                "old_value": c.old_value,
                "new_value": c.new_value,
                "detected_at": c.detected_at.isoformat(),
            }
            for c in changes
        ],
        "evidence": [
            {
                "source_type": e.source_type,
                "source_id": e.source_id,
                "content_hash": e.content_hash[:12],
                "observed_at": e.observed_at.isoformat(),
                "content_preview": e.content[:400],
            }
            for e in evidence
        ],
        "column_lineage": column_lineage,
    }
