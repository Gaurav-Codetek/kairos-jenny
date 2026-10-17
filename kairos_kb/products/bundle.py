"""Assemble a data product's bundle from the map — code only, no LLM.

Starting from the output ports a person picked, walk upstream along data flow
(platform lineage, and FEEDS / WRITES_TABLE / LOADS_INTO / READS_* relations
that are not contradicted) to everything that feeds them. Then gather what is
attached to any of it: the pipelines that write it, the platform objects linked
to it (stages, locations, integrations, warehouses, policies …), its grants,
industry bindings and open agent reports — and each table's enriched profile,
checks and freshness. The result is what the product *is*; the business layer
on top only interprets it.

Lanes place each table in the flow: source → raw → staging → core → mart.
They come from the enrichment classification (layer and role); a table the
classifier could not place sits one lane after the tables that feed it.
"""

from __future__ import annotations

import uuid
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.context.documents import load_profile, trust_level
from kairos_kb.models.column import Column
from kairos_kb.models.context import ContextFeedback
from kairos_kb.models.discovered import DiscoveredEntity, DiscoveredRelation
from kairos_kb.models.job import Job
from kairos_kb.models.knowledge import KnowledgeBinding, KnowledgeConcept
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.models.run import Run
from kairos_kb.models.table import Table
from kairos_kb.models.task import Task

LANES = ["source", "raw", "staging", "core", "mart"]

# Relations whose source sends data into the target.
INTO = {"FEEDS", "WRITES_TABLE", "LOADS_INTO", "WRITES_FILE"}
# Relations whose source takes data from the target.
FROM = {"READS_TABLE", "READS_FILE"}
# Kinds that run code: they carry data between tables rather than hold it.
ACTORS = {"job", "task", "procedure", "function", "pipe", "notebook", "alert", "dynamic_table_refresh"}
# Kinds that hold data before it reaches a table.
SOURCES = {"stage", "location", "volume", "file", "path", "external_location", "integration", "storage_integration"}

MAX_NODES = 200
MAX_DEPTH = 12
BUILD_SQL_CHARS = 6000


def kind_of(entity_id: str) -> str:
    return entity_id.split(":", 1)[0]


def short(entity_id: str) -> str:
    return entity_id.split(":", 2)[-1]


def lane_from_classification(role: Optional[str], layer: Optional[str], *, by_role: bool = False) -> Optional[str]:
    """The lane the enrichment classification puts a table in; None when it cannot tell.

    The layer decides (a fact landed raw is still raw); the role only separates
    marts from facts and dimensions in the serving layers. With by_role, a table
    whose layer is unknown is placed by its role alone.
    """
    role, layer = (role or "").upper(), (layer or "").upper()
    if layer == "RAW_LANDING" or role == "RAW_FILE_INGEST":
        return "raw"
    if layer == "BRONZE_STAGING":
        return "staging"
    if layer in ("SILVER_CURATED", "GOLD_SERVING"):
        if role == "AGGREGATE_MART":
            return "mart"
        return "core" if layer == "SILVER_CURATED" or role in ("FACT_EVENT", "DIMENSION_MASTER", "MAPPING_CROSSWALK")             else "mart"
    if by_role:
        return {"AGGREGATE_MART": "mart", "FACT_EVENT": "core", "DIMENSION_MASTER": "core",
                "MAPPING_CROSSWALK": "core"}.get(role)
    return None


def assign_lanes(tables: List[str], classified: Dict[str, Optional[str]],
                 upstream: Dict[str, Set[str]], roles: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, str]:
    """Each table's lane: its classified layer; else raw when no table feeds it, a mart when its role
    says so, or one lane after what feeds it."""
    roles = roles or {}
    lanes: Dict[str, str] = {t: classified[t] for t in tables if classified.get(t)}
    for _ in range(len(tables) + 1):
        changed = False
        for t in tables:
            if t in lanes and classified.get(t):
                continue
            ins = [lanes[u] for u in upstream.get(t, ()) if u in lanes]
            if not upstream.get(t):
                lane = "raw"
            elif (roles.get(t) or "").upper() == "AGGREGATE_MART":
                lane = "mart"
            elif ins:
                lane = LANES[min(len(LANES) - 1, max(LANES.index(x) for x in ins) + 1)]
            else:
                continue
            if lanes.get(t) != lane:
                lanes[t], changed = lane, True
        if not changed:
            break
    for t in tables:
        lanes.setdefault(t, "core")
    return lanes


async def _relations_touching(db: AsyncSession, ids: List[str]) -> List[DiscoveredRelation]:
    if not ids:
        return []
    return list((await db.execute(select(DiscoveredRelation).where(
        DiscoveredRelation.status != "contradicted",
        or_(DiscoveredRelation.source_entity_id.in_(ids), DiscoveredRelation.target_entity_id.in_(ids)),
    ))).scalars())


async def _upstream_of(db: AsyncSession, node: str) -> List[Tuple[str, Dict[str, Any]]]:
    """What sends data into one node: (upstream entity, edge)."""
    out: List[Tuple[str, Dict[str, Any]]] = []
    if kind_of(node) == "table":
        for e in (await db.execute(select(LineageEdge).where(
                LineageEdge.target_entity_id == node, LineageEdge.source_type == "TABLE"))).scalars():
            out.append((e.source_entity_id, {"relation": "LINEAGE", "status": "verified", "via": "platform lineage"}))
    for r in (await db.execute(select(DiscoveredRelation).where(
            DiscoveredRelation.status != "contradicted",
            or_(DiscoveredRelation.target_entity_id == node, DiscoveredRelation.source_entity_id == node)))).scalars():
        rel = (r.relation_type or "").upper()
        if r.target_entity_id == node and rel in INTO:
            other = r.source_entity_id
        elif r.source_entity_id == node and rel in FROM:
            other = r.target_entity_id
        else:
            continue
        out.append((other, {"relation": rel, "status": r.status, "via": r.source_ref or "enrichment",
                            "rationale": (r.rationale or "")[:240] or None}))
    if kind_of(node) == "job":
        job = (await db.execute(select(Job).where(Job.entity_id == node))).scalars().first()
        if job:
            for t in (await db.execute(select(Task).where(Task.job_id == job.id))).scalars():
                out.append((t.entity_id, {"relation": "RUNS_TASK", "status": "verified", "via": "job settings"}))
    return out


async def _downstream_of(db: AsyncSession, node: str) -> List[Tuple[str, str]]:
    """What takes data from one node: (consumer, relation)."""
    out: List[Tuple[str, str]] = []
    for e in (await db.execute(select(LineageEdge).where(
            LineageEdge.source_entity_id == node, LineageEdge.source_type == "TABLE"))).scalars():
        out.append((e.target_entity_id, "LINEAGE"))
    for r in (await db.execute(select(DiscoveredRelation).where(
            DiscoveredRelation.status != "contradicted",
            or_(DiscoveredRelation.target_entity_id == node, DiscoveredRelation.source_entity_id == node)))).scalars():
        rel = (r.relation_type or "").upper()
        if r.source_entity_id == node and rel in INTO:
            out.append((r.target_entity_id, rel))
        elif r.target_entity_id == node and rel in FROM:
            out.append((r.source_entity_id, rel))
    return out


def _columns_from(profile: Optional[Dict[str, Any]], synced: List[Column]) -> List[Dict[str, Any]]:
    shape = (profile or {}).get("shape") if isinstance((profile or {}).get("shape"), dict) else {}
    described = {str(c.get("name", "")).lower(): c for c in (shape.get("columns") or []) if isinstance(c, dict)}
    out = []
    for c in synced:
        d = described.get(c.name.lower(), {})
        tags = d.get("tags")
        tags = [t.strip() for t in tags.split(",")] if isinstance(tags, str) else (tags or [])
        out.append({
            "name": c.name,
            "type": c.data_type,
            "meaning": d.get("meaning") or c.comment,
            "aggregation": d.get("aggregation"),
            "tags": [t for t in tags if t],
        })
    return out


def _freshness(table: Table, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    props = table.properties or {}
    facts = (profile or {}).get("facts") or {}
    origin = facts.get("code_origin") or {}
    return {k: v for k, v in {
        "last_altered": props.get("last_altered") or facts.get("last_write") or origin.get("at"),
        "built_by_role": origin.get("role") or props.get("table_owner"),
        "built_by": origin.get("by") or props.get("last_ddl_by"),
        "build_kind": origin.get("kind") or facts.get("code_source"),
    }.items() if v}


async def _table_member(db: AsyncSession, entity_id: str, lane: str, profile: Optional[Dict[str, Any]],
                        output_port: bool) -> Optional[Dict[str, Any]]:
    table = (await db.execute(select(Table).where(Table.entity_id == entity_id))).scalars().first()
    if table is None:
        return None
    cols = list((await db.execute(select(Column).where(Column.table_id == table.id)
                                  .order_by(Column.ordinal_position))).scalars())
    profile = profile or {}
    cls = profile.get("classification") or {}
    verification = profile.get("verification") or {}
    shape = profile.get("shape") if isinstance(profile.get("shape"), dict) else {}
    props = table.properties or {}
    build_sql = props.get("build_sql") or props.get("view_definition") or props.get("text")
    return {
        "entity_id": entity_id,
        "kind": "table",
        "name": table.name,
        "full_name": table.full_name,
        "lane": lane,
        "output_port": output_port,
        "trust": trust_level(profile or None),
        "role": cls.get("role") if cls.get("status") == "ok" else None,
        "layer": cls.get("layer") if cls.get("status") == "ok" else None,
        "personal_data": cls.get("personal_data"),
        "summary": profile.get("summary") or table.comment,
        "purpose": profile.get("purpose"),
        "grain": shape.get("grain"),
        "grain_key": profile.get("grain_key"),
        "table_type": table.table_type,
        "row_count": table.row_count,
        "size_bytes": table.size_bytes,
        "freshness": _freshness(table, profile),
        "checks": [{"check": c.get("check"), "result": c.get("result"), "detail": c.get("detail")}
                   for c in verification.get("checks") or []],
        "checks_passed": verification.get("passed"),
        "open_questions": list(profile.get("open_questions") or [])[:8],
        "grants": props.get("grants"),
        "columns": _columns_from(profile, cols),
        "build_sql": str(build_sql)[:BUILD_SQL_CHARS] if build_sql else None,
    }


async def _object_member(db: AsyncSession, entity_id: str, role: str) -> Dict[str, Any]:
    ent = (await db.execute(select(DiscoveredEntity).where(DiscoveredEntity.entity_id == entity_id))).scalars().first()
    attrs = dict((ent.attrs if ent else None) or {})
    profile = await load_profile(db, entity_id)
    out = {
        "entity_id": entity_id,
        "kind": kind_of(entity_id),
        "name": ent.name if ent else short(entity_id),
        "role_in_product": role,
        "origin": ent.origin if ent else None,
        "owner": attrs.get("owner"),
        "comment": attrs.get("comment"),
        "summary": (profile or {}).get("summary"),
        "trust": trust_level(profile) if profile else None,
    }
    props = attrs.get("properties") or {}
    if props:
        out["properties"] = {k: v for k, v in list(props.items())[:12] if not isinstance(v, (dict, list))}
    if attrs.get("grants"):
        out["grants"] = attrs["grants"]
    return {k: v for k, v in out.items() if v not in (None, {}, [])}


async def _pipeline_member(db: AsyncSession, entity_id: str) -> Dict[str, Any]:
    kind = kind_of(entity_id)
    profile = await load_profile(db, entity_id)
    out: Dict[str, Any] = {"entity_id": entity_id, "kind": kind, "name": short(entity_id).split(":")[-1],
                           "summary": (profile or {}).get("summary"), "trust": trust_level(profile)}
    job = None
    if kind == "job":
        job = (await db.execute(select(Job).where(Job.entity_id == entity_id))).scalars().first()
    elif kind == "task":
        task = (await db.execute(select(Task).where(Task.entity_id == entity_id))).scalars().first()
        if task:
            out["name"] = task.task_key
            job = await db.get(Job, task.job_id)
            out["job"] = job.entity_id if job else None
    if job is not None:
        out["job_name"] = job.name
        out["schedule"] = (job.schedule or {}).get("quartz_cron_expression") if isinstance(job.schedule, dict) else None
        runs = list((await db.execute(select(Run).where(Run.job_id == job.id)
                                      .order_by(Run.start_time.desc()).limit(10))).scalars())
        if runs:
            done = [r for r in runs if r.result_state]
            ok = sum(1 for r in done if r.result_state == "SUCCESS")
            last_fail = next((r for r in runs if r.result_state and r.result_state != "SUCCESS"), None)
            out["runs"] = {
                "recent": len(runs),
                "succeeded": ok,
                "last_state": runs[0].result_state or runs[0].state,
                "last_run_at": runs[0].start_time.isoformat() if runs[0].start_time else None,
                "last_failure": ({"at": last_fail.start_time.isoformat() if last_fail.start_time else None,
                                  "state": last_fail.result_state,
                                  "error": (last_fail.error_message or "")[:240] or None} if last_fail else None),
            }
    return {k: v for k, v in out.items() if v not in (None, {}, [])}


async def assemble(db: AsyncSession, workspace_id: uuid.UUID, seeds: List[str]) -> Dict[str, Any]:
    """The product's bundle: members in lanes, the flow between them, attached objects and health."""
    # ── 1. Walk upstream from the output ports along data flow ──
    depth: Dict[str, int] = {s: 0 for s in seeds}
    edges: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    queue = deque(seeds)
    while queue and len(depth) < MAX_NODES:
        node = queue.popleft()
        if depth[node] >= MAX_DEPTH:
            continue
        for other, edge in await _upstream_of(db, node):
            if other == node:
                continue
            edges.setdefault((other, node, edge["relation"]), {"source": other, "target": node, **edge})
            if other not in depth:
                depth[other] = depth[node] + 1
                queue.append(other)

    nodes = list(depth)
    tables = [n for n in nodes if kind_of(n) == "table"]
    actors = [n for n in nodes if kind_of(n) in ACTORS]
    others = [n for n in nodes if n not in tables and n not in actors]

    # Table → table flow, including flow that passes through a pipeline (A read by task, task writes B).
    table_set = set(tables)
    upstream: Dict[str, Set[str]] = {t: set() for t in tables}
    reads: Dict[str, Set[str]] = {}
    for (src, tgt, rel), e in edges.items():
        if src in table_set and tgt in table_set:
            upstream[tgt].add(src)
        if kind_of(tgt) in ACTORS and src in table_set:
            reads.setdefault(tgt, set()).add(src)
    flow: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for (src, tgt, rel), e in edges.items():
        if src in table_set and tgt in table_set:
            key = (src, tgt)
            prev = flow.get(key)
            if prev is None or (prev["status"] != "verified" and e["status"] == "verified"):
                flow[key] = {"source": src, "target": tgt, "relation": rel, "status": e["status"], "via": e["via"]}
        elif kind_of(src) in ACTORS and tgt in table_set:
            for inp in reads.get(src, ()):
                if inp != tgt:
                    upstream[tgt].add(inp)
                    flow.setdefault((inp, tgt), {"source": inp, "target": tgt, "relation": "THROUGH",
                                                 "status": e["status"], "via": short(src)})

    # ── 2. Profiles and lanes ──
    profiles = {t: await load_profile(db, t) for t in tables}
    classified, roles = {}, {}
    for t in tables:
        cls = (profiles.get(t) or {}).get("classification") or {}
        ok = cls.get("status") == "ok"
        classified[t] = lane_from_classification(cls.get("role"), cls.get("layer")) if ok else None
        roles[t] = cls.get("role") if ok else None
    lanes = assign_lanes(tables, classified, upstream, roles)

    members = []
    for t in tables:
        m = await _table_member(db, t, lanes[t], profiles.get(t), t in seeds)
        if m:
            members.append(m)
    member_ids = {m["entity_id"] for m in members}

    # Sources (stages, locations) sit in the first lane; anything else upstream is an attached object.
    objects: Dict[str, Dict[str, Any]] = {}
    for n in others:
        role = "source" if kind_of(n) in SOURCES else "upstream object"
        objects[n] = await _object_member(db, n, role)
        if role == "source":
            for (src, tgt, rel), e in edges.items():
                if src == n and tgt in member_ids:
                    flow.setdefault((n, tgt), {"source": n, "target": tgt, "relation": rel,
                                               "status": e["status"], "via": e["via"]})
    pipelines = [await _pipeline_member(db, a) for a in actors]
    for p in pipelines:
        p["writes"] = sorted({short(t) for (s, t, _r) in edges if s == p["entity_id"] and t in member_ids})
        p["reads"] = sorted({short(s) for s in reads.get(p["entity_id"], ())})

    # ── 3. Everything attached to the flow: one hop of any relation not already in it ──
    flow_nodes = set(nodes)
    attached: List[Dict[str, Any]] = []
    for r in await _relations_touching(db, list(flow_nodes)):
        a, b = r.source_entity_id, r.target_entity_id
        inside_a, inside_b = a in flow_nodes, b in flow_nodes
        if inside_a and inside_b:
            continue
        outside = b if inside_a else a
        anchor = a if inside_a else b
        if kind_of(outside) == "table" and (r.relation_type or "").upper() in INTO | FROM:
            continue  # a consumer, listed below
        if outside not in objects:
            objects[outside] = await _object_member(db, outside, "attached")
        attached.append({"object": outside, "relation": r.relation_type, "anchor": anchor,
                         "direction": "out" if inside_a else "in", "status": r.status})

    # Infrastructure behind infrastructure: the integration that opens a bucket, the location a stage reads.
    infra = [o for o, v in objects.items() if kind_of(o) in SOURCES]
    for r in await _relations_touching(db, infra):
        a, b = r.source_entity_id, r.target_entity_id
        outside = b if a in infra else a
        if outside in flow_nodes or kind_of(outside) not in SOURCES | {"warehouse"}:
            continue
        if outside not in objects:
            objects[outside] = await _object_member(db, outside, "attached")
        attached.append({"object": outside, "relation": r.relation_type, "anchor": a if a in infra else b,
                         "direction": "out" if a in infra else "in", "status": r.status})

    # Who owns and who may read each table: the owner role and the grants synced from the platform.
    ws_name = seeds[0].split(":", 2)[1] if seeds and seeds[0].count(":") >= 2 else ""
    for m in members:
        owner = (m.get("freshness") or {}).get("built_by_role")
        holders = {owner: "OWNS"} if owner else {}
        # Grants are stored role → privileges.
        for role_name, privileges in (m.get("grants") or {}).items():
            privileges = {str(p).upper() for p in privileges or []}
            rel = "OWNS" if "OWNERSHIP" in privileges else "CAN_WRITE" if privileges & {"INSERT", "UPDATE", "DELETE"}                 else "CAN_READ" if "SELECT" in privileges else None
            if rel and holders.get(role_name) != "OWNS":
                holders[role_name] = rel
        for role_name, rel in holders.items():
            rid = f"role:{ws_name}:{role_name}"
            if not (await db.execute(select(DiscoveredEntity.id).where(DiscoveredEntity.entity_id == rid))).first():
                continue
            if rid not in objects:
                objects[rid] = await _object_member(db, rid, "access")
            attached.append({"object": rid, "relation": rel, "anchor": m["entity_id"], "direction": "out",
                             "status": "verified"})

    # Who uses the output ports: downstream of them, outside the product.
    consumers: Dict[str, Dict[str, Any]] = {}
    for s in seeds:
        for other, rel in await _downstream_of(db, s):
            if other not in flow_nodes:
                consumers.setdefault(other, {"entity_id": other, "kind": kind_of(other), "name": short(other),
                                             "reads": [], "relation": rel})["reads"].append(short(s))

    # ── 4. Industry bindings and open agent reports on any member ──
    bindings = []
    if member_ids:
        rows = (await db.execute(
            select(KnowledgeBinding, KnowledgeConcept.title)
            .outerjoin(KnowledgeConcept, KnowledgeConcept.concept_id == KnowledgeBinding.concept_id)
            .where(or_(KnowledgeBinding.entity_id.in_(list(member_ids)),
                       *[KnowledgeBinding.entity_id.like(f"column:{e.split(':', 1)[1]}.%") for e in member_ids]),
                   KnowledgeBinding.status != "rejected"))).all()
        seen = set()
        for b, title in rows:
            key = (b.entity_id, b.concept_id)
            if key in seen:
                continue
            seen.add(key)
            bindings.append({"entity_id": b.entity_id, "concept_id": b.concept_id, "concept": title,
                             "predicate": b.predicate, "status": b.status, "confidence": round(b.confidence, 2)})
    feedback = []
    if flow_nodes:
        for f in (await db.execute(select(ContextFeedback).where(
                ContextFeedback.entity_id.in_(list(flow_nodes)), ContextFeedback.status == "open"))).scalars():
            feedback.append({"entity_id": f.entity_id, "kind": f.kind, "message": f.message[:300]})

    # ── 5. Health ──
    trust = {"verified": 0, "profiled": 0, "synced": 0}
    for m in members:
        trust[m["trust"]] = trust.get(m["trust"], 0) + 1
    failing = [{"entity_id": m["entity_id"], "check": c["check"], "result": c["result"], "detail": c["detail"]}
               for m in members for c in m["checks"] if c.get("result") in ("fails", "incomplete", "missing")]
    stamps = sorted(m["freshness"]["last_altered"] for m in members if m["freshness"].get("last_altered"))
    pipeline_failures = [p for p in pipelines if (p.get("runs") or {}).get("last_failure")]

    return {
        "lanes": LANES,
        "members": sorted(members, key=lambda m: (LANES.index(m["lane"]), m["full_name"])),
        "flow": [e for e in flow.values() if e["source"] in member_ids | set(objects) and e["target"] in member_ids],
        "sources": [o for o in objects.values() if o.get("role_in_product") == "source"],
        "objects": [o for o in objects.values() if o.get("role_in_product") != "source"],
        "attached": list({(x["object"], x["relation"], x["anchor"]): x for x in attached}.values()),
        "pipelines": pipelines,
        "consumers": list(consumers.values()),
        "knowledge": bindings,
        "feedback": feedback,
        "health": {
            "tables": len(members),
            "trust": trust,
            "failing_checks": failing,
            "oldest_update": stamps[0] if stamps else None,
            "newest_update": stamps[-1] if stamps else None,
            "pipelines_with_failures": len(pipeline_failures),
            "open_reports": len(feedback),
            "truncated": len(depth) >= MAX_NODES,
        },
    }
