"""The answer to an agent's first question: what have I been connected to?

Business first, then structure: the data products and the tables that carry
them, the pipelines that produce them, how much Kairos has verified, how
fresh it is, and how to work with the tools. Compact on purpose — an agent
reads this once, then searches.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.knowledge.search import knowledge_overview
from kairos_kb.context.access import AgentIdentity, visible_workspace_filter
from kairos_kb.context.documents import first_sentence
from kairos_kb.enrichment.pipeline import canonical_relation
from kairos_kb.models.column import Column
from kairos_kb.models.context import ContextDocument, ContextFeedback
from kairos_kb.models.discovered import DiscoveredRelation
from kairos_kb.models.enrichment_run import EnrichmentRun
from kairos_kb.models.entity_profile import EntityProfile
from kairos_kb.models.job import Job
from kairos_kb.models.table import Table
from kairos_kb.models.task import Task
from kairos_kb.models.workspace import Workspace

# Which tables to show first for a data product: the ones an analyst would query.
ROLE_ORDER = ["aggregate_mart", "fact_event", "fact_snapshot", "dimension", "reference_lookup",
              "bridge_mapping", "staging", "raw_file_ingest", "log_audit", "scratch_test"]

GUIDE = {
    "workflow": [
        "find_data(question) — search by meaning, business terms or names; results carry a trust level",
        "get_context(entity_id) — meaning, grain, columns, where it comes from and goes, how to query it, caveats",
        "find_knowledge(question) / get_concept(concept_id) — industry knowledge: what a dataset type, identifier, "
        "metric or regulation means, and which tables here are bound to it",
        "find_join_path(a, b) — before joining two tables: the keys, the evidence, example SQL",
        "explore_entity(entity_id) / get_data_dependencies(entity_id) / get_blast_radius(entity_id) — walk the graph",
        "report_context_issue(entity_id, kind, message) — when something here is wrong, missing or stale",
    ],
    "trust_levels": {
        "verified": "Profiled by Kairos and every automated check passed (grain uniqueness, column coverage, "
                    "writer consistency). Safe to rely on.",
        "profiled": "Described by Kairos from code, history and data, but a check failed or could not run. "
                    "Read the card's caveats before relying on it.",
        "synced": "Only the platform's own metadata (names, types, comments). Kairos has not profiled it yet.",
    },
    "principles": [
        "Kairos is read-only: it never changes the data platform.",
        "Links carry evidence (Delta history, pipeline code, Databricks lineage). Prefer evidenced links.",
        "Entity ids are stable: kind:workspace:qualified_name.",
    ],
}


def _role(tags: List[str]) -> str:
    for t in tags or []:
        if isinstance(t, str) and t.startswith("role:"):
            return t[5:]
    return ""


def _layer(tags: List[str]) -> str:
    for t in tags or []:
        if isinstance(t, str) and t.startswith("layer:"):
            return t[6:]
    return ""


async def overview(db: AsyncSession, identity: AgentIdentity) -> Dict[str, Any]:
    ws_filter = visible_workspace_filter(identity, Workspace.id)
    workspaces = (await db.execute(select(Workspace).where(*ws_filter).order_by(Workspace.name))).scalars().all()
    out_ws = []
    for ws in workspaces:
        async def count(model, *extra):
            return (await db.execute(
                select(func.count()).select_from(model).where(model.workspace_id == ws.id, *extra)
            )).scalar() or 0

        tables = await count(Table)
        if not tables and not await count(Job):
            out_ws.append({"workspace": ws.name, "platform": ws.platform, "status": "not synced yet"})
            continue
        trust = dict((await db.execute(
            select(ContextDocument.trust_level, func.count())
            .where(ContextDocument.workspace_id == ws.id, ContextDocument.kind == "table")
            .group_by(ContextDocument.trust_level)
        )).all())
        last_enrichment = (await db.execute(
            select(func.max(EnrichmentRun.finished_at)).where(EnrichmentRun.workspace_id == ws.id)
        )).scalar()
        out_ws.append({
            "workspace": ws.name,
            "platform": ws.platform,
            "host": ws.host,
            "holds": {"tables": tables, "columns": await count(Column), "pipelines": await count(Job),
                      "tasks": await count(Task)},
            "table_trust": {
                "verified": trust.get("verified", 0),
                "profiled": trust.get("profiled", 0),
                "synced_only": trust.get("synced", 0),
                "not_indexed": max(0, tables - sum(trust.values())),
            },
            "freshness": {
                "last_sync": ws.last_synced_at.isoformat() if ws.last_synced_at else None,
                "last_enrichment": last_enrichment.isoformat() if last_enrichment else None,
            },
        })

    ws_ids = [w.id for w in workspaces]
    profiles = (await db.execute(
        select(EntityProfile).where(EntityProfile.workspace_id.in_(ws_ids))
    )).scalars().all() if ws_ids else []
    docs = {d.entity_id: d for d in (await db.execute(
        select(ContextDocument).where(ContextDocument.workspace_id.in_(ws_ids))
    )).scalars()} if ws_ids else {}

    products: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"tables": [], "pipelines": [], "kinds": Counter()})
    layers: Counter = Counter()
    for p in profiles:
        tags = p.semantic_tags or []
        if p.kind == "table" and _layer(tags):
            layers[_layer(tags)] += 1
        if not p.data_product:
            continue
        entry = products[p.data_product]
        entry["kinds"][p.kind] += 1
        doc = docs.get(p.entity_id)
        item = {"entity_id": p.entity_id, "name": p.entity_id.split(":")[-1],
                "what_it_is": first_sentence(p.summary, 160),
                "trust_level": doc.trust_level if doc else "profiled"}
        if p.kind == "table":
            item["role"] = _role(tags)
            entry["tables"].append(item)
        elif p.kind == "job":
            entry["pipelines"].append(item)

    def role_rank(t):
        r = t.get("role", "")
        return ROLE_ORDER.index(r) if r in ROLE_ORDER else len(ROLE_ORDER)

    # Data products: the business concepts defined on each connection, each served as one unit.
    from kairos_kb.models.data_product import DataProduct
    from kairos_kb.products.service import contracts_of

    ws_name = {w.id: w.name for w in workspaces}
    data_products = []
    for dp in (await db.execute(select(DataProduct).where(DataProduct.workspace_id.in_(ws_ids))
                                .order_by(DataProduct.name))).scalars().all() if ws_ids else []:
        model = (dp.spec or {}).get("model") or {}
        data_products.append({
            "product": dp.name, "id": dp.slug, "entity_id": f"product:{ws_name.get(dp.workspace_id)}:{dp.slug}",
            "connection": ws_name.get(dp.workspace_id), "domain": dp.domain, "status": dp.status,
            "health": (await contracts_of(db, dp))["health"]["status"],
            "what_it_answers": first_sentence(dp.description, 200),
            "metrics": [m["name"] for m in model.get("metrics") or []],
            "inputs": [i["table"] for i in (dp.spec or {}).get("inputs") or []][:10],
        })
    # The enrichment's free-text domains, for connections without products yet.
    domains = [{"domain": name, "profiled_entities": dict(e["kinds"]),
                "key_tables": sorted(e["tables"], key=lambda t: (role_rank(t), t["name"]))[:8],
                "pipelines": e["pipelines"][:5]}
               for name, e in sorted(products.items(), key=lambda kv: -sum(kv[1]["kinds"].values()))]

    # Pipelines and what they demonstrably produce.
    writes = defaultdict(set)
    rels = (await db.execute(select(DiscoveredRelation).where(
        DiscoveredRelation.status == "verified", DiscoveredRelation.workspace_id.in_(ws_ids)
    ))).scalars().all() if ws_ids else []
    for r in rels:
        canonical, flip, _ = canonical_relation(r.relation_type)
        src, dst = (r.target_entity_id, r.source_entity_id) if flip else (r.source_entity_id, r.target_entity_id)
        if canonical == "WRITES_TABLE" and src.startswith("job:"):
            writes[src].add(dst.split(":")[-1])
    job_names = dict((await db.execute(
        select(Job.entity_id, Job.name).where(Job.entity_id.in_(list(writes)))
    )).all()) if writes else {}
    pipelines = [
        {"entity_id": j, "name": job_names.get(j, j.split(":")[-1]), "writes": sorted(t)[:8],
         "writes_count": len(t)}
        for j, t in sorted(writes.items(), key=lambda kv: -len(kv[1]))
    ][:15]

    open_feedback = (await db.execute(
        select(func.count()).select_from(ContextFeedback).where(ContextFeedback.status == "open")
    )).scalar() or 0

    return {
        "kairos": "A context layer over your data platform: every entity described, verified where possible, "
                  "linked by evidence, and searchable by meaning. Read-only.",
        "you_are": {"agent": identity.name, "scopes": sorted(identity.scopes)},
        "workspaces": out_ws,
        "data_products": data_products,
        "data_products_how": ("Answer a question that fits a product with query_data_product(id, metrics, by); "
                              "get_data_product(id) gives its metrics, rules and contracts."),
        "domains": domains[:10],
        "layers": dict(layers.most_common()),
        "pipelines_with_verified_outputs": pipelines,
        "open_context_issues": open_feedback,
        "industry_knowledge": await knowledge_overview(db, identity),
        "how_to_use": GUIDE,
    }
