"""The map as information: every node and link said in words, for the UI and for outside applications.

The entity graph speaks in ids (``evidence:7f3c…``, ``change:…``). This layer
turns them into what a person or another application can show: a label, a
one-line summary (the profile's, the evidence's, the change's), the
connection it belongs to, and for links the agent discovered, why it believes
them and what it saw. ``entity_card`` is one entity in full — attributes,
profile, evidence, and every relation with the related entities described.

Used by the REST map (/api/v1/warehouse/card) and by the map MCP endpoint
(/mcp-map). Access is the caller's identity: an entity in a connection the
caller cannot see is left out, as if it were not there.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

import yaml
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.context.access import AgentIdentity
from kairos_kb.models.change_event import ChangeEvent
from kairos_kb.models.discovered import DiscoveredRelation
from kairos_kb.models.entity_profile import EntityProfile
from kairos_kb.models.evidence import Evidence
from kairos_kb.models.sync_state import SyncState
from kairos_kb.models.workspace import Workspace
from kairos_kb.warehouse.entity_graph import SYNTHETIC_KINDS, EntityGraph, split_node_id
from kairos_kb.warehouse.evidence_text import change_summary, evidence_digest, mask_emails

HIDDEN_ATTRS = {"id", "workspace_id", "created_at", "updated_at", "content", "content_hash"}
# The map passes everything on: every neighbour, the whole evidence text. A bound no warehouse reaches stands in
# for "no limit" where the graph's queries need a number.
EVERYTHING = 1_000_000_000
WHOLE_TEXT = -1
_SYNTHETIC = {"evidence": Evidence, "change": ChangeEvent, "syncstate": SyncState}


def _mask(value: Any) -> Any:
    if isinstance(value, str):
        return mask_emails(value)
    if isinstance(value, dict):
        return {k: _mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    return value


def _pk(node_id: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(split_node_id(node_id)[1])
    except ValueError:
        return None


async def _workspace_names(db: AsyncSession) -> Dict[uuid.UUID, str]:
    return {w.id: w.name for w in (await db.execute(select(Workspace.id, Workspace.name))).all()}


def visible(identity: Optional[AgentIdentity], item: Dict[str, Any]) -> bool:
    """Whether the caller may see this described item (its connection is one they are allowed)."""
    if identity is None or identity.workspace_names is None:
        return True
    return item.get("connection") in identity.workspace_names


async def enrich(db: AsyncSession, payloads: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Graph payloads → items in words: label, sublabel, one-line summary, connection."""
    ids = [p["id"] for p in payloads]
    by_kind: Dict[str, List[uuid.UUID]] = defaultdict(list)
    for node_id in ids:
        kind = split_node_id(node_id)[0]
        if kind in _SYNTHETIC and (pk := _pk(node_id)):
            by_kind[kind].append(pk)
    rows: Dict[str, Any] = {}
    for kind, pks in by_kind.items():
        model = _SYNTHETIC[kind]
        for row in (await db.execute(select(model).where(model.id.in_(pks)))).scalars().all():
            rows[f"{kind}:{row.id}"] = row
    profiles = {
        r.entity_id: r for r in (await db.execute(
            select(EntityProfile.entity_id, EntityProfile.summary, EntityProfile.data_product)
            .where(EntityProfile.entity_id.in_(ids))
        )).all()
    } if ids else {}
    names = await _workspace_names(db)

    out: Dict[str, Dict[str, Any]] = {}
    for p in payloads:
        node_id, kind = p["id"], p["kind"]
        row = rows.get(node_id)
        item: Dict[str, Any] = {
            "id": node_id,
            "kind": kind,
            "label": p.get("label") or node_id,
            "sublabel": p.get("sublabel") or "",
            "summary": None,
            "known": p.get("known", False),
            "discovered": bool(p.get("discovered")),
            "status": p.get("status"),
            "profiled": node_id in profiles,
        }
        if row is not None:
            item["connection"] = names.get(row.workspace_id)
        elif kind == "workspace":
            item["connection"] = split_node_id(node_id)[1]
        else:
            parts = node_id.split(":")
            item["connection"] = parts[1] if len(parts) >= 3 else None
        if kind == "evidence" and row is not None:
            digest = evidence_digest(row)
            item.update(summary=digest["summary"], sublabel=f"{digest['source_label']} · {digest['observed_at'][:10]}"
                        if digest["observed_at"] else digest["source_label"])
        elif kind == "change" and row is not None:
            item["summary"] = change_summary(row)
        elif kind == "syncstate" and row is not None:
            item["summary"] = f"{row.domain} sync {row.status}, {row.items_synced} items" + (
                f" — {row.error_message[:160]}" if row.error_message else "")
        elif node_id in profiles:
            item["summary"] = profiles[node_id].summary
            if profiles[node_id].data_product:
                item["data_product"] = profiles[node_id].data_product
        elif p.get("discovered"):
            item["summary"] = (p.get("attrs") or {}).get("rationale")
        out[node_id] = _mask(item)
    return out


async def describe(db: AsyncSession, ids: Iterable[str], graph: Optional[EntityGraph] = None) -> Dict[str, Dict[str, Any]]:
    """Any node ids → items in words."""
    ids = set(ids)
    if not ids:
        return {}
    return await enrich(db, await (graph or EntityGraph(db)).materialize(ids))


async def link_reasons(db: AsyncSession, node_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """For links the agent discovered: why it believes them and what it saw, keyed by edge id."""
    node_ids = list(set(node_ids))
    if not node_ids:
        return {}
    rows = (await db.execute(
        select(DiscoveredRelation).where(
            DiscoveredRelation.status != "contradicted",
            or_(DiscoveredRelation.source_entity_id.in_(node_ids), DiscoveredRelation.target_entity_id.in_(node_ids)),
        )
    )).scalars().all()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        out[f"{r.source_entity_id}|{r.relation_type}|{r.target_entity_id}"] = _mask({
            "rationale": r.rationale,
            "confidence": r.confidence,
            "status": r.status,
            "seen_in": r.source_ref,
            "observed_at": r.observed_at.isoformat() if r.observed_at else None,
            "evidence": evidence_digest(r.evidence) if r.evidence is not None else None,
        })
    return out


async def load_profile(db: AsyncSession, entity_id: str, *, with_yaml: bool) -> Optional[Dict[str, Any]]:
    """The enrichment profile of one entity: headline fields and the whole document."""
    from kairos_kb.enrichment.profile_writer import load_profile_yaml

    row = (await db.execute(select(EntityProfile).where(EntityProfile.entity_id == entity_id))).scalars().first()
    if row is None:
        return None
    text = await load_profile_yaml(db, entity_id)
    try:
        document = yaml.safe_load(text) if text else None
    except yaml.YAMLError:
        document = None
    out: Dict[str, Any] = {
        "summary": row.summary,
        "purpose": row.purpose,
        "data_product": row.data_product,
        "tags": row.semantic_tags or [],
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "model": row.model,
        "document": document if isinstance(document, dict) else None,
    }
    if with_yaml:
        out["yaml"] = text
    return _mask(out)


async def entity_card(db: AsyncSession, node_id: str, *, identity: Optional[AgentIdentity] = None,
                      per_relation: Optional[int] = None, with_yaml: bool = True) -> Optional[Dict[str, Any]]:
    """One entity in full, every id resolved: attributes, profile, evidence, relations with reasons.

    None when there is no such entity for this caller.
    """
    graph = EntityGraph(db)
    detail = await graph.entity_detail(node_id, sample=per_relation, limit=EVERYTHING)
    me = (await describe(db, [node_id], graph)).get(node_id)
    if me is None or not visible(identity, me):
        return None
    kind = detail["kind"]

    sampled = {t for r in detail["relations"] for t in r["sample"]}
    items = await describe(db, sampled, graph)
    reasons = await link_reasons(db, [node_id])

    relations = []
    for r in detail["relations"]:
        related = []
        for other in r["sample"]:
            item = items.get(other)
            if item is None or not visible(identity, item):
                continue
            reason = (reasons.get(f"{node_id}|{r['relation']}|{other}")
                      or reasons.get(f"{other}|{r['relation']}|{node_id}"))
            related.append({**item, **({"reason": reason} if reason else {})})
        relations.append({"relation": r["relation"], "group": r["group"], "count": r["count"], "items": related})

    attributes = {k: v for k, v in detail["attributes"].items() if k not in HIDDEN_ATTRS and v not in (None, "")}
    card: Dict[str, Any] = {
        **me,
        "attributes": _mask(attributes),
        "relations": relations,
        "relation_total": detail["relation_total"],
        "profile": await load_profile(db, node_id, with_yaml=with_yaml),
    }
    if not detail["known"] and not me.get("discovered"):
        card["note"] = ("Referenced by other records (typically lineage) but never synced, so Kairos holds nothing "
                        "more about it.")
    if kind == "evidence" and (pk := _pk(node_id)):
        row = await db.get(Evidence, pk)
        if row is not None:
            card["evidence"] = evidence_digest(row, excerpt_chars=WHOLE_TEXT)
    return card


async def map_graph(db: AsyncSession, root: str, *, identity: Optional[AgentIdentity] = None, depth: int = 1,
                    relation_groups: Optional[Sequence[str]] = None,
                    limit_per_relation: int = EVERYTHING) -> Dict[str, Any]:
    """A neighbourhood of the map with every node in words and every discovered link's reason."""
    graph = EntityGraph(db)
    walked = await graph.traverse(root, depth=depth, relation_groups=relation_groups,
                                  limit_per_relation=limit_per_relation)
    items = await enrich(db, walked["nodes"])
    shown = {i for i, item in items.items() if visible(identity, item)}
    if root not in shown:
        return {"error": f"No such entity for this caller: {root}"}
    nodes = []
    for n in walked["nodes"]:
        if n["id"] in shown:
            nodes.append({**items[n["id"]], "depth": n.get("depth", 0), "is_root": n.get("is_root", False),
                          "expandable": n.get("expandable", False)})
    reasons = await link_reasons(db, shown)
    edges = []
    for e in walked["edges"]:
        if e["source"] in shown and e["target"] in shown:
            reason = reasons.get(e["id"])
            edges.append({**e, **({"reason": reason} if reason else {})})
    return {
        "root": root,
        "depth": walked["depth"],
        "relation_groups": walked["relation_groups"],
        "nodes": nodes,
        "edges": edges,
        "truncated": bool(walked["truncations"]),
        "stats": {"nodes": len(nodes), "edges": len(edges)},
    }


async def search_map(db: AsyncSession, query: str, *, identity: Optional[AgentIdentity] = None,
                     kinds: Optional[Sequence[str]] = None, connection: Optional[str] = None,
                     limit: Optional[int] = None) -> List[Dict[str, Any]]:
    found = await EntityGraph(db).search(query, kinds=kinds, limit=EVERYTHING)
    items = await enrich(db, found)
    out = []
    for p in found:
        item = items[p["id"]]
        if not visible(identity, item) or (connection and item.get("connection") != connection):
            continue
        out.append(item)
        if limit and len(out) >= limit:
            break
    return out


_SLUG = re.compile(r"[^a-z0-9]+")


async def resolve_connections(db: AsyncSession, identity: Optional[AgentIdentity],
                              connection: str = "") -> List[Workspace]:
    """The connections the caller sees, narrowed to one when named (by name, slug or id)."""
    rows = (await db.execute(select(Workspace).order_by(Workspace.name))).scalars().all()
    rows = [w for w in rows if identity is None or identity.workspace_names is None
            or w.name in identity.workspace_names]
    wanted = (connection or "").strip().lower()
    if not wanted:
        return rows
    slug = _SLUG.sub("-", wanted).strip("-")
    return [w for w in rows if wanted in (w.name.lower(), str(w.id)) or _SLUG.sub("-", w.name.lower()).strip("-") == slug]


async def map_overview(db: AsyncSession, identity: Optional[AgentIdentity] = None,
                       connection: str = "") -> Dict[str, Any]:
    """What the map holds: the connections, how many of each kind, and the relation vocabulary."""
    from kairos_kb.models.catalog import Catalog
    from kairos_kb.models.column import Column
    from kairos_kb.models.job import Job
    from kairos_kb.models.lineage_edge import LineageEdge
    from kairos_kb.models.run import Run
    from kairos_kb.models.schema import Schema
    from kairos_kb.models.table import Table
    from kairos_kb.models.task import Task
    from kairos_kb.warehouse.entity_map import DEFAULT_RELATION_GROUPS, RELATIONS, entity_map_document

    workspaces = await resolve_connections(db, identity, connection)
    if connection and not workspaces:
        return {"error": f"No connection '{connection}' for this caller."}
    models = {"catalog": Catalog, "schema": Schema, "table": Table, "column": Column, "job": Job, "task": Task,
              "run": Run, "evidence": Evidence, "change": ChangeEvent, "profile": EntityProfile,
              "discovered_link": DiscoveredRelation, "lineage_edge": LineageEdge}

    connections = []
    for w in workspaces:
        counts = {}
        for name, model in models.items():
            counts[name] = (await db.execute(
                select(func.count()).select_from(model).where(model.workspace_id == w.id))).scalar() or 0
        connections.append({"name": w.name, "platform": w.platform or "databricks", "status": w.status,
                            "root": f"workspace:{w.name}", "last_synced_at":
                                w.last_synced_at.isoformat() if w.last_synced_at else None, "counts": counts})

    doc = entity_map_document()
    return {
        "connections": connections,
        "kinds": [{"kind": k["kind"], "label": k["label"], "id_format": k["id_format"], "grain": k["grain"]}
                  for k in doc["kinds"]],
        "relations": [{"name": r["name"], "from": r["source"], "to": r["target"], "group": r["group"],
                       "meaning": r["description"]} for r in RELATIONS],
        "relation_groups": doc["relation_groups"],
        "default_relation_groups": list(DEFAULT_RELATION_GROUPS),
        "discovered_relations": "Links the enrichment agent found (READS_TABLE, WRITES_TABLE, FEEDS …) are in "
                                "group 'discovered'; each carries a reason: rationale, confidence, where it was "
                                "seen, and the evidence.",
        "total_entities": sum(sum(v for k, v in c["counts"].items() if k not in ("profile", "discovered_link",
                                                                                 "lineage_edge"))
                              for c in connections),
    }


async def mesh_for(db: AsyncSession, identity: Optional[AgentIdentity] = None, connection: str = "") -> Dict[str, Any]:
    """The bundle mesh (catalog → schema → table, pipeline → task, with flow between them) for visible connections."""
    from kairos_kb.warehouse.mesh import build_mesh

    workspaces = await resolve_connections(db, identity, connection)
    if not workspaces:
        return {"error": f"No connection '{connection}' for this caller." if connection else "No connections."}
    if identity is None or identity.workspace_names is None:
        if not connection:
            return await build_mesh(db, None)
    merged: Dict[str, Any] = {"workspaces": [], "bundles": [], "relationships": []}
    for w in workspaces:
        part = await build_mesh(db, str(w.id))
        for key in merged:
            merged[key].extend(part.get(key) or [])
    merged["stats"] = {"bundles": len(merged["bundles"]), "relationships": len(merged["relationships"])}
    return merged
