"""Kairos MCP server — the knowledge layer, exposed to outside agents.

Kairos is a map, not a set of answers: every tool here reads (or, for
report_context_issue, annotates) the map, and agents do their own reasoning
over it. Task-specific capabilities — root-cause analysis of failed runs
among them — are deliberately not exposed here. Nothing in this surface
writes to the connected data platform, which is what makes it safe to hand
to third-party developers.

The package is deliberately named ``mcp_server`` rather than ``mcp`` so it
cannot shadow the installed SDK.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from sqlalchemy import func, or_, select

from kairos_kb.context.access import audited, current_agent
from kairos_kb.db.engine import async_session_factory
from kairos_kb.enrichment.profile_writer import load_profile_yaml
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.discovered import DiscoveredRelation
from kairos_kb.models.entity_profile import EntityProfile
from kairos_kb.models.job import Job
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.models.run import Run
from kairos_kb.models.workspace import Workspace
from kairos_kb.warehouse.entity_graph import EntityGraph, workspace_node_id
from kairos_kb.warehouse.entity_map import RELATIONS, entity_map_document

logger = logging.getLogger(__name__)

INSTRUCTIONS = """Kairos is the context layer over this organisation's data platform (Databricks).
Every catalog, schema, table, column, pipeline and task is mapped; the important ones are
profiled — what they mean, their grain, where they come from and go — and checked by code.
You need no setup: everything you need to understand and use the data is here.

Start here:
1. get_overview() — what this warehouse covers: data products, key tables, pipelines, trust, freshness.
2. find_data(question) — find tables, pipelines or columns by meaning ("account level sales by month"),
   business terms or names. Each result says how far it can be trusted.
3. get_context(entity_id) — one entity in full: meaning, grain and key, every column, what produces and
   reads it, example SQL, join candidates, and caveats you must know before relying on it.
   Compact by default; detail="full" adds every column, all neighbours and full run history.
4. find_join_path(from_entity, to_entity) — before joining two tables: the keys, evidence and example SQL.
   check_key_uniqueness(entity_id, columns) — test any candidate key on the live data before relying on it.
   run_sql(sql, limit) — run a read-only query once you know the right tables (needs the query permission).
   Use fully qualified tables from the map; files, paths and unmapped tables are refused; identifying
   personal data is masked (counting it is fine). Each result restates what the map knows about its tables.
   list_volume_files(path) / read_volume_file(path) — when a file itself matters (needs the files
   permission); each read names the tables built from the file, which are usually the better source.
5. find_knowledge(question) / get_concept(concept_id) — Kairos's industry knowledge (US pharma
   commercial): dataset types (867, DDD, Xponent, claims…), identifiers (NDC, NPI, DEA, HIN…), metrics,
   regulations. A table's context names the dataset type it is bound to, its identifier columns and
   the rules that apply; get_concept shows which tables here are bound to a concept.
6. report_context_issue(entity_id, kind, message) — when something here is wrong, missing or stale.
   Every other agent benefits from your report.

Trust levels: verified (profiled, every automated check passed) > profiled (described, some check
failed or did not run — read the caveats) > synced (platform metadata only).

Graph tools (explore_entity, get_data_dependencies, get_blast_radius) walk lineage and data flow.
list_incidents() lists recent failed runs across pipelines with the exact error and where it was
raised; a pipeline's or task's context holds its full run history, so you can reason about operational
questions from the map itself. Kairos is read-only toward the platform: it never changes data.
"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
# Writes only to Kairos (never the platform).
KAIROS_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
# Reads the platform itself (a query), never changes it.
PLATFORM_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)

server = MCPServer(
    name="kairos",
    title="Kairos — Data Platform Intelligence",
    instructions=INSTRUCTIONS,
)


# ── Context: orient, find, understand, join, report ─────────────────


@server.tool(annotations=READ_ONLY)
@audited()
async def get_overview() -> Dict[str, Any]:
    """What you are connected to. Call this first.

    Returns the data products this warehouse serves and their key tables, the
    pipelines and what they demonstrably write, how much of each workspace
    Kairos has verified, how fresh it is, and how to use these tools.
    """
    from kairos_kb.context.orientation import overview

    async with async_session_factory() as db:
        return await overview(db, current_agent())


@server.tool(annotations=READ_ONLY)
@audited()
async def find_data(question: str, kinds: str = "", limit: int = 10) -> Dict[str, Any]:
    """Find tables, pipelines, tasks, schemas or catalogs by what they mean.

    Ask the way a person would ("ICS sales at invoice line level", "where are
    load failures logged", "HCO master data"), or give a name or part of one.
    Combines meaning-based search, keywords and name matching. Every result has
    a trust_level and says which retrievers matched it.

    Args:
        question: What you are looking for, in plain words or as a name.
        kinds: Optional comma-separated filter: table, job, task, schema, catalog.
        limit: Maximum results (default 10).
    """
    from kairos_kb.context.search import find_data as search

    kind_list = [k.strip() for k in kinds.split(",") if k.strip()] or None
    async with async_session_factory() as db:
        return await search(db, question, current_agent(), kinds=kind_list, limit=max(1, min(limit, 50)))


@server.tool(annotations=READ_ONLY)
@audited()
async def find_knowledge(question: str, types: str = "", limit: int = 8) -> Dict[str, Any]:
    """Search Kairos's industry knowledge — what things mean in this industry, not in this warehouse.

    For business questions the warehouse alone cannot answer: what an 867 feed or
    DDD outlet is, how NDC or NPI are formatted, what TRx and NBRx mean, which
    dataset answers which question, PHI and licensing rules. Each result says how
    many warehouse tables or columns are bound to it.

    Args:
        question: Plain words or a term, e.g. "net sales from distributor data", "NPI".
        types: Optional comma-separated concept types, e.g. "Dataset Type,Identifier,Metric".
        limit: Maximum results (default 8).
    """
    from kairos_kb.knowledge.search import find_knowledge as search

    type_list = [t.strip() for t in types.split(",") if t.strip()] or None
    async with async_session_factory() as db:
        return await search(db, question, types=type_list, limit=max(1, min(limit, 30)))


@server.tool(annotations=READ_ONLY)
@audited()
async def get_concept(concept_id: str) -> Dict[str, Any]:
    """One industry concept in full, and where it appears in this warehouse.

    Definition, grain and keys, schema, pitfalls, typical uses, related concepts,
    sources — and the tables and columns bound to it (proposed by Kairos or
    confirmed by a person).

    Args:
        concept_id: From find_knowledge or a table's industry section, e.g. '/identifiers/provider/npi'.
    """
    from kairos_kb.knowledge.search import get_concept as read

    async with async_session_factory() as db:
        concept = await read(db, current_agent(), concept_id)
    return concept or {"error": f"Unknown concept: {concept_id}. Use find_knowledge() to find one."}


@server.tool(annotations=READ_ONLY)
@audited()
async def get_context(entity_id: str, detail: str = "summary", max_columns: int = 150) -> Dict[str, Any]:
    """Everything needed to understand and use one entity.

    For a table: summary and purpose, trust (level, checks, staleness), grain and
    grain key, every column with its meaning, what produces and reads it,
    upstream and downstream tables, example SQL, join candidates, and caveats
    (failed checks, personal data, open questions, reports from other agents).
    For a pipeline or task: its tasks, the tables it reads and writes, run health.

    Args:
        entity_id: From find_data or any other tool, e.g. 'table:<workspace>:<catalog>.<schema>.<table>'.
        detail: "summary" (default) — the essentials: meaning, trust, grain, caveats, key and
            personal-data columns, every column name, recent runs. "full" — every column with its
            meaning, all neighbours, full run history with tracebacks.
        max_columns: Cap on columns returned in full detail for very wide tables.
    """
    from kairos_kb.context.cards import entity_card, summarize_card

    async with async_session_factory() as db:
        card = await entity_card(db, entity_id, max_columns=max(10, min(max_columns, 1000)))
    if card is None:
        return {"error": f"Unknown entity: {entity_id}. Use find_data() to find it."}
    return card if detail == "full" else summarize_card(card)


@server.tool(annotations=READ_ONLY)
@audited()
async def find_join_path(from_entity: str, to_entity: str) -> Dict[str, Any]:
    """How to join two tables, with the evidence for it.

    Returns the recommended key columns (grain keys and identifier columns the
    tables share, with type compatibility), whether a pipeline already combines
    them, example SQL — or, when they share no key, bridge tables to go through.

    Args:
        from_entity: A table entity_id.
        to_entity: Another table entity_id.
    """
    from kairos_kb.context.joins import join_path

    async with async_session_factory() as db:
        return await join_path(db, from_entity, to_entity)


@server.tool(annotations=PLATFORM_READ)
@audited()
async def check_key_uniqueness(entity_id: str, columns: str) -> Dict[str, Any]:
    """Test whether a set of columns uniquely identifies rows of a table, on the live data.

    Use before aggregating or joining on a key you are not sure of. Runs a
    read-only COUNT DISTINCT on the platform (cached for an hour) and returns
    rows, distinct keys, duplicates, NULLs in the key, and example duplicates.
    get_context() already reports the check for the key Kairos states; use
    this for any other key.

    Args:
        entity_id: A table entity_id.
        columns: Key columns, comma-separated, e.g. 'ORG_VID, INVOICE_ID, INVOICE_ITEM'.
    """
    from kairos_kb.context.quality import check_key_uniqueness as check

    async with async_session_factory() as db:
        return await check(db, entity_id, columns)


@server.tool(annotations=PLATFORM_READ)
@audited("query")
async def run_sql(sql: str, limit: int = 100) -> Dict[str, Any]:
    """Run one read-only SQL query on the data platform and return the rows.

    Only SELECT, WITH, SHOW, DESCRIBE and EXPLAIN run; anything that writes or
    changes state is refused. Results are capped at `limit` rows. Values in
    columns Kairos knows hold personal data are masked — aggregate or filter on
    them in SQL instead. Use get_context() and find_join_path() first so the
    query uses the right tables, grain and keys. Needs the 'query' permission.

    Args:
        sql: A single read-only statement (Databricks SQL), with fully qualified table names.
        limit: Maximum rows to return (default 100).
    """
    from kairos_kb.context.query import run_sql as run

    async with async_session_factory() as db:
        return await run(db, current_agent(), sql, limit)


@server.tool(annotations=PLATFORM_READ)
@audited("files")
async def list_volume_files(path: str) -> Dict[str, Any]:
    """List the files and folders in a Unity Catalog Volume directory.

    Needs the 'files' permission. Use read_volume_file() to read one.

    Args:
        path: A Volume directory, e.g. '/Volumes/<catalog>/<schema>/<volume>/<folder>'.
    """
    from kairos_kb.context.files import list_volume_files as run

    async with async_session_factory() as db:
        return await run(db, current_agent(), path)


@server.tool(annotations=PLATFORM_READ)
@audited("files")
async def read_volume_file(path: str, max_rows: int = 50) -> Dict[str, Any]:
    """Read the start of a text file in a Unity Catalog Volume (CSV, TSV, JSON, text, config).

    For files no table answers: an upload not yet loaded, a config or mapping file a
    pipeline reads, the raw feed behind a failure. Only the beginning is read; binary
    formats are refused. Columns whose header names identifying data are masked, and
    e-mail addresses and phone numbers are redacted everywhere. The result names the
    tasks that read the file and the tables they load — prefer those tables when they
    hold what you need. Needs the 'files' permission.

    Args:
        path: The file, e.g. '/Volumes/<catalog>/<schema>/<volume>/<folder>/<file>.csv'.
        max_rows: Rows (or about four times as many lines of text) to return, up to 500.
    """
    from kairos_kb.context.files import read_volume_file as run

    async with async_session_factory() as db:
        return await run(db, current_agent(), path, max_rows)


@server.tool(annotations=KAIROS_WRITE)
@audited()
async def report_context_issue(entity_id: str, kind: str, message: str, field: str = "",
                               suggestion: str = "") -> Dict[str, Any]:
    """Tell Kairos that context about an entity is wrong, missing, stale or confusing.

    Your report is shown to every other agent in that entity's context at once,
    and the enrichment agent verifies it and corrects the profile on its next
    pass. Use kind='useful' to confirm context that helped. Writes only to
    Kairos, never to the data platform.

    Args:
        entity_id: The entity the report is about.
        kind: incorrect | missing | stale | confusing | useful
        message: What is wrong or missing, specifically.
        field: Optional: which part (e.g. 'grain', 'columns.ORG_VID', 'summary').
        suggestion: Optional: what it should say instead.
    """
    from kairos_kb.context.feedback import report_issue

    async with async_session_factory() as db:
        return await report_issue(db, current_agent(), entity_id, kind, message, field or None, suggestion or None)


@server.resource("kairos://overview", name="overview", title="What this warehouse covers",
                 description="Data products, key tables, pipelines, trust and freshness.",
                 mime_type="application/json")
async def overview_resource() -> str:
    import json

    from kairos_kb.context.orientation import overview

    async with async_session_factory() as db:
        return json.dumps(await overview(db, current_agent()), default=str, indent=1)


@server.resource("kairos://guide", name="guide", title="How to use Kairos",
                 description="The recommended workflow and what trust levels mean.", mime_type="text/markdown")
async def guide_resource() -> str:
    return INSTRUCTIONS


@server.prompt(name="start_here", title="Get oriented in this data platform")
def start_here(goal: str = "") -> str:
    """A first message for any agent new to this warehouse."""
    goal_line = f"My goal: {goal}\n\n" if goal else ""
    return (goal_line + "You are connected to Kairos, the context layer for this data platform. "
            "Call get_overview() first to see what it covers, then find_data() with what you need, "
            "then get_context() on the best match before using it. Prefer verified entities; read "
            "caveats; use find_join_path() before joining; report anything wrong with report_context_issue().")


# ── Discovery ────────────────────────────────────────────────────────


@server.tool(annotations=READ_ONLY)
@audited()
async def get_entity_map() -> Dict[str, Any]:
    """Describe the terrain: every entity kind, every relationship, with live counts.

    Read this first. It tells you what grains exist and how much of each has
    been synced, so you can plan a traversal instead of guessing.
    """
    from kairos_kb.api.v1.warehouse import COUNT_MODELS

    document = entity_map_document()
    async with async_session_factory() as db:
        counts = {}
        for kind, model in COUNT_MODELS.items():
            counts[kind] = (await db.execute(select(func.count()).select_from(model))).scalar() or 0
        for entry in document["kinds"]:
            entry["count"] = counts.get(entry["kind"], 0)

        profiles = (await db.execute(select(func.count()).select_from(EntityProfile))).scalar() or 0
        discovered = (
            await db.execute(select(func.count()).select_from(DiscoveredRelation))
        ).scalar() or 0
        lineage = (await db.execute(select(func.count()).select_from(LineageEdge))).scalar() or 0

    document["totals"] = {
        "entities": sum(counts.values()),
        "semantic_profiles": profiles,
        "discovered_relations": discovered,
        "lineage_edges": lineage,
    }
    # Be explicit when the semantic layer is empty rather than letting a
    # consumer read zero links as "this platform has no data flow".
    if not discovered:
        document["caveat"] = (
            "No discovered relations yet — enrichment has not run. Data-flow answers "
            "will be limited to platform-reported lineage."
        )
    return document


@server.tool(annotations=READ_ONLY)
@audited()
async def list_workspaces() -> List[Dict[str, Any]]:
    """List connected platform workspaces, the natural entry points."""
    async with async_session_factory() as db:
        rows = (await db.execute(select(Workspace).order_by(Workspace.name))).scalars().all()
        agent = current_agent()
        out = []
        for w in rows:
            if not agent.sees_workspace_name(w.name):
                continue
            catalogs = (
                await db.execute(
                    select(func.count()).select_from(Catalog).where(Catalog.workspace_id == w.id)
                )
            ).scalar() or 0
            jobs = (
                await db.execute(
                    select(func.count()).select_from(Job).where(Job.workspace_id == w.id)
                )
            ).scalar() or 0
            failed = (
                await db.execute(
                    select(func.count())
                    .select_from(Run)
                    .where(Run.workspace_id == w.id, Run.result_state == "FAILED")
                )
            ).scalar() or 0
            out.append(
                {
                    "entity_id": workspace_node_id(w),
                    "name": w.name,
                    "host": w.host,
                    "catalogs": catalogs,
                    "jobs": jobs,
                    "failed_runs": failed,
                    "last_synced_at": w.last_synced_at.isoformat() if w.last_synced_at else None,
                }
            )
        return out


@server.tool(annotations=READ_ONLY)
@audited()
async def search_entities(query: str, kinds: str = "", limit: int = 25) -> List[Dict[str, Any]]:
    """Find entities by name across every grain.

    Args:
        query: Substring to match.
        kinds: Optional comma-separated filter, e.g. 'table,job,column'.
        limit: Maximum results.
    """
    async with async_session_factory() as db:
        graph = EntityGraph(db)
        kind_list = [k.strip() for k in kinds.split(",") if k.strip()] or None
        results = await graph.search(query, kinds=kind_list, limit=limit)
        agent = current_agent()
        return [
            {"entity_id": r["id"], "kind": r["kind"], "name": r["label"], "detail": r["sublabel"]}
            for r in results
            if agent.sees_entity(r["id"])
        ]


# ── Navigation ───────────────────────────────────────────────────────


@server.tool(annotations=READ_ONLY)
@audited()
async def get_entity(entity_id: str) -> Dict[str, Any]:
    """Every stored attribute of one entity, plus its neighbour count per relation.

    Args:
        entity_id: Any node id, e.g. 'table:<workspace>:<catalog>.<schema>.<table>'.
    """
    async with async_session_factory() as db:
        detail = await EntityGraph(db).entity_detail(entity_id)
        attributes = {
            k: v
            for k, v in (detail.get("attributes") or {}).items()
            if k not in {"id", "workspace_id", "created_at", "updated_at"} and v not in (None, "")
        }
        return {
            "entity_id": detail["id"],
            "kind": detail["kind"],
            "known": detail["known"],
            "attributes": attributes,
            "relations": [
                {"relation": r["relation"], "count": r["count"], "sample": r["sample"][:5]}
                for r in detail.get("relations", [])
            ],
            "note": None
            if detail["known"]
            else "Referenced by other records but never synced into the warehouse.",
        }


@server.tool(annotations=READ_ONLY)
@audited()
async def explore_entity(entity_id: str, relations: str = "", limit: int = 25) -> Dict[str, Any]:
    """Walk one hop from any node, along any relationship.

    This reaches everything: a table's columns, a schema's tables, a job's
    tasks, an entity's evidence and change events, and any relationship the
    enrichment agent discovered. Call without a filter first to see what
    connects, then filter when one relation has many neighbours.

    Args:
        entity_id: Any node id.
        relations: Optional comma-separated filter, e.g. 'HAS_COLUMN'.
        limit: Maximum neighbours per relation.
    """
    async with async_session_factory() as db:
        graph = EntityGraph(db)
        wanted = {r.strip().upper() for r in relations.split(",") if r.strip()}
        allowed = wanted or ({r["name"] for r in RELATIONS} | {"DISCOVERED"})
        edges, truncations = await graph.expand(entity_id, relations=allowed, limit=limit)

        grouped: Dict[str, List[Dict[str, str]]] = {}
        for edge in edges:
            outgoing = edge["source"] == entity_id
            peer = edge["target"] if outgoing else edge["source"]
            grouped.setdefault(edge["relation"], []).append(
                {
                    "entity_id": peer,
                    "kind": peer.split(":", 1)[0],
                    "direction": "outgoing" if outgoing else "incoming",
                }
            )

        return {
            "entity_id": entity_id,
            "relation_counts": {k: len(v) for k, v in sorted(grouped.items())},
            "neighbours": grouped,
            "truncated": [t["relation"] for t in truncations] or None,
        }


# ── Semantics and data flow ──────────────────────────────────────────


@server.tool(annotations=READ_ONLY)
@audited()
async def get_entity_profile(entity_id: str, include_document: bool = False) -> Dict[str, Any]:
    """The semantic profile of an entity: what it is, what it serves, how it is produced.

    Args:
        entity_id: Any node id.
        include_document: Also return the full YAML profile document.
    """
    async with async_session_factory() as db:
        profile = (
            await db.execute(select(EntityProfile).where(EntityProfile.entity_id == entity_id))
        ).scalars().first()
        if not profile:
            return {
                "entity_id": entity_id,
                "profiled": False,
                "note": "Enrichment has not reached this entity yet.",
            }

        payload = {
            "entity_id": entity_id,
            "profiled": True,
            "kind": profile.kind,
            "summary": profile.summary,
            "purpose": profile.purpose,
            "data_product": profile.data_product,
            "semantic_tags": profile.semantic_tags,
            "generated_at": profile.generated_at.isoformat(),
        }
        # The code-authored blocks, as structure an agent can branch on.
        from kairos_kb.context.documents import load_profile, trust_level

        parsed = await load_profile(db, entity_id) or {}
        payload["trust_level"] = trust_level(parsed or None)
        payload["classification"] = parsed.get("classification")
        payload["verification"] = parsed.get("verification")
        payload["facts"] = parsed.get("facts")
        payload["grain"] = (parsed.get("shape") or {}).get("grain")
        payload["grain_key"] = parsed.get("grain_key")
        payload["tip"] = "get_context(entity_id) gives this plus columns, flow, joins, example SQL and caveats."
        if include_document:
            payload["document"] = await load_profile_yaml(db, entity_id)
        return payload


@server.tool(annotations=READ_ONLY)
@audited()
async def get_data_dependencies(entity_id: str) -> Dict[str, Any]:
    """What an entity reads and writes.

    Relations sourced from 'discovered' were inferred by an agent reading real
    pipeline code and carry a confidence and rationale — weigh them as
    inference. Relations from 'lineage' were reported by the platform.

    Args:
        entity_id: A task or table entity_id.
    """
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(DiscoveredRelation)
                .where(
                    DiscoveredRelation.status != "contradicted",
                    or_(
                        DiscoveredRelation.source_entity_id == entity_id,
                        DiscoveredRelation.target_entity_id == entity_id,
                    )
                )
                .limit(60)
            )
        ).scalars().all()

        reads, writes, other = [], [], []
        for row in rows:
            outgoing = row.source_entity_id == entity_id
            peer = row.target_entity_id if outgoing else row.source_entity_id
            item = {
                "entity_id": peer,
                "relation": row.relation_type,
                "confidence": round(row.confidence, 2),
                "rationale": (row.rationale or "")[:240],
                "source": "discovered",
            }
            name = row.relation_type.upper()
            if "READ" in name and outgoing:
                reads.append(item)
            elif "WRITE" in name and outgoing:
                writes.append(item)
            else:
                other.append(item)

        lineage = (
            await db.execute(
                select(LineageEdge)
                .where(
                    or_(
                        LineageEdge.source_entity_id == entity_id,
                        LineageEdge.target_entity_id == entity_id,
                    )
                )
                .limit(40)
            )
        ).scalars().all()

        return {
            "entity_id": entity_id,
            "reads": reads,
            "writes": writes,
            "other_links": other,
            "lineage_upstream": [
                e.source_entity_id for e in lineage if e.target_entity_id == entity_id
            ],
            "lineage_downstream": [
                e.target_entity_id for e in lineage if e.source_entity_id == entity_id
            ],
            "note": None
            if rows
            else "No discovered links. Enrichment has not profiled this entity — absence here is not evidence it touches nothing.",
        }


@server.tool(annotations=READ_ONLY)
@audited()
async def get_blast_radius(entity_id: str) -> Dict[str, Any]:
    """Who is affected downstream if this asset is wrong or missing.

    Args:
        entity_id: A table entity_id.
    """
    async with async_session_factory() as db:
        incoming = (
            await db.execute(
                select(DiscoveredRelation)
                .where(DiscoveredRelation.target_entity_id == entity_id)
                .limit(60)
            )
        ).scalars().all()
        downstream = (
            await db.execute(
                select(LineageEdge).where(LineageEdge.source_entity_id == entity_id).limit(40)
            )
        ).scalars().all()

        return {
            "entity_id": entity_id,
            "written_by": [
                {"entity_id": r.source_entity_id, "relation": r.relation_type}
                for r in incoming
                if "WRITE" in r.relation_type.upper()
            ],
            "read_by": [
                {"entity_id": r.source_entity_id, "relation": r.relation_type}
                for r in incoming
                if "READ" in r.relation_type.upper()
            ],
            "flows_into": [e.target_entity_id for e in downstream],
        }


# ── Operations ───────────────────────────────────────────────────────


@server.tool(annotations=READ_ONLY)
@audited()
async def list_incidents(pipeline: str = "", limit: int = 25) -> Dict[str, Any]:
    """Recent failed pipeline runs, newest first, with what failed and why as recorded.

    Each failure names the pipeline, when it ran, and the tasks that failed —
    with the exact error and where it was raised (notebook cell, line,
    function) when Kairos has read it. These are facts from the platform, as of
    the last sync; reason about causes from them, and use get_context() on a
    pipeline or task for its full run history and traceback.

    Args:
        pipeline: Optional pipeline name or entity_id to filter to (partial names work).
        limit: Maximum failed runs to return (default 25).
    """
    from kairos_kb.context.cards import FAILED_RESULTS, task_failure
    from kairos_kb.models.task_run import TaskRun

    agent = current_agent()
    limit = max(1, min(limit, 100))
    async with async_session_factory() as db:
        # A run is an incident if it failed, or if any task in it failed — a
        # repaired run ends SUCCESS but its failed attempt still happened.
        failing_runs = select(TaskRun.run_id).where(TaskRun.result_state.in_(FAILED_RESULTS))
        query = (
            select(Run, Job)
            .join(Job, Job.id == Run.job_id)
            .where(or_(Run.result_state.in_(FAILED_RESULTS), Run.id.in_(failing_runs)))
            .order_by(Run.start_time.desc().nulls_last())
        )
        wanted = pipeline.strip()
        if wanted:
            query = query.where(or_(Job.entity_id == wanted, Job.name.ilike(f"%{wanted}%"),
                                    Job.source_native_id == wanted))
        rows = [(r, j) for r, j in (await db.execute(query.limit(limit * 3))).all()
                if agent.sees_entity(j.entity_id)][:limit]

        failed: Dict[Any, List[TaskRun]] = {}
        retried: Dict[Any, set] = {}
        if rows:
            for tr in (await db.execute(select(TaskRun).where(
                TaskRun.run_id.in_([r.id for r, _ in rows])
            ))).scalars():
                if tr.result_state in FAILED_RESULTS:
                    failed.setdefault(tr.run_id, []).append(tr)
                elif tr.result_state == "SUCCESS" and tr.attempt_number:
                    retried.setdefault(tr.run_id, set()).add(tr.task_key)

        synced = {}
        for _, j in rows:
            if j.workspace_id not in synced:
                synced[j.workspace_id] = (await db.execute(
                    select(Workspace.last_synced_at).where(Workspace.id == j.workspace_id)
                )).scalar()

    incidents = []
    for r, j in rows:
        tasks = failed.get(r.id, [])
        incidents.append({
            "pipeline": j.name,
            "pipeline_entity_id": j.entity_id,
            "run_started_at": r.start_time.isoformat() if r.start_time else None,
            "result": r.result_state,
            "recovered_on_retry": (r.result_state not in FAILED_RESULTS
                                   and any(t.task_key in retried.get(r.id, set()) for t in tasks)),
            "failed_tasks": [
                {"task_key": t.task_key, "attempt": t.attempt_number,
                 "task_entity_id": f"task:{j.entity_id.split(':', 1)[1]}:{t.task_key}",
                 "later_attempt_succeeded": t.task_key in retried.get(r.id, set()),
                 **(task_failure(t) or {})}
                for t in tasks
            ] or None,
            "status_message": None if tasks else (r.error_message or None),
        })
    return {
        "incidents": incidents,
        "count": len(incidents),
        "as_of": {str(k): v.isoformat() if v else None for k, v in synced.items()},
        "note": ("Failures recorded as of the last sync. A failed attempt followed by a successful retry "
                 "appears here too; get_context(pipeline) shows the full run history."),
    }
