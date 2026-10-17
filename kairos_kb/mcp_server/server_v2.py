"""Kairos MCP server, v2: the same map through fewer, non-overlapping tools.

v1 (/mcp) grew to 20 tools, several of which answer the same question in
slightly different ways (search_entities vs find_data, get_entity vs
get_entity_profile vs get_context, three graph walks). v2 (/mcp-v2) gives
each job exactly one tool:

  orient      get_overview
  products    list_data_products, get_data_product, query_data_product — concepts served as one unit
  find        find            — data (tables, pipelines, columns) and industry knowledge, one search
  understand  get_context     — any entity; get_concept for an industry concept
  connect     trace, find_join_path
  operate     list_incidents
  verify      check_key_uniqueness, run_sql, volume_files
  improve     report_context_issue

Both servers run side by side over the same map, permissions and audit log;
v2 calls are recorded on channel "mcp-v2" under v2 tool names, so the two can
be compared on the Agents screen. v2 reuses v1's implementations (through
their undecorated functions, so nothing is audited twice) and changes only
how they are grouped and presented.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from mcp.server import MCPServer
from sqlalchemy import func, select

from kairos_kb.context.access import audited, current_agent
from kairos_kb.db.engine import async_session_factory
from kairos_kb.mcp_server import server as v1
from kairos_kb.models.column import Column

logger = logging.getLogger(__name__)

INSTRUCTIONS = """Kairos is the context layer over this organisation's data platform (Databricks), plus
industry knowledge for its sector (US pharma commercial). Every catalog, schema, table, column,
pipeline and task is mapped; the important ones are profiled and checked by code. No setup needed.

1. get_overview() — what this platform covers: workspaces, data products, pipelines, trust,
   freshness, and which industry dataset types the warehouse holds.
2. find(question) — one search over the warehouse (tables, pipelines, columns) and the industry
   knowledge (dataset types, identifiers, metrics, regulations). Plain words or names.
3. get_context(entity_id) — one entity in full: meaning, grain, columns, flow, example SQL, joins,
   caveats, and for tables the industry dataset type, identifier columns and rules that apply.
   get_concept(concept_id) — one industry concept, and the tables and columns bound to it.
4. trace(entity_id, direction) — what feeds an entity and what depends on it; find_join_path(a, b)
   — how to join two tables. list_incidents() — recent failed runs with the exact error.
5. check_key_uniqueness / run_sql / volume_files — check against the live platform (read-only;
   run_sql needs the query permission, volume_files the files permission).
6. report_context_issue(entity_id, kind, message) — when something here is wrong or missing.
7. list_data_products() / get_data_product(product) — business concepts served as one unit (Sales,
   Delivery performance …): metrics defined once, dimensions, rules, contracts. query_data_product(product,
   metrics, by, filters) answers from a product without naming tables. When a question fits one, use it.

Trust: verified (profiled, every check passed) > profiled (read the caveats) > synced (metadata only).
Industry bindings marked "proposed" are Kairos's reading, not yet confirmed by a person.
Kairos never changes the platform.
"""

READ_ONLY = v1.READ_ONLY
KAIROS_WRITE = v1.KAIROS_WRITE
PLATFORM_READ = v1.PLATFORM_READ

server = MCPServer(
    name="kairos-v2",
    title="Kairos v2 — Data Platform Intelligence",
    instructions=INSTRUCTIONS,
)


def _raw(tool):
    """A v1 tool without its audit wrapper: v2 records the call under its own name."""
    return getattr(tool, "__wrapped__", tool)


# ── Orient ───────────────────────────────────────────────────────────


@server.tool(annotations=READ_ONLY)
@audited()
async def get_overview() -> Dict[str, Any]:
    """What you are connected to. Call this first.

    Workspaces and how much of each Kairos has verified, the data products and
    their key tables, pipelines and what they write, freshness, the kinds of
    entity in the map with counts, and the industry knowledge loaded — with the
    dataset types this warehouse holds.
    """
    from kairos_kb.context.orientation import overview

    async with async_session_factory() as db:
        out = await overview(db, current_agent())
    entity_map = await _raw(v1.get_entity_map)()
    out["map"] = {
        "entity_kinds": {k["kind"]: k.get("count", 0) for k in entity_map.get("kinds", [])},
        "totals": entity_map.get("totals"),
        "caveat": entity_map.get("caveat"),
    }
    out["how_to_use"] = {**(out.get("how_to_use") or {}), "workflow": [
        "find(question) — tables, pipelines, columns and industry concepts in one search",
        "get_context(entity_id) — understand one entity; get_concept(concept_id) for an industry concept",
        "trace(entity_id, direction) — upstream sources, downstream dependants, or direct neighbours",
        "find_join_path(a, b) — keys and evidence for joining two tables",
        "check_key_uniqueness / run_sql / volume_files — verify on the live platform",
        "report_context_issue(entity_id, kind, message) — when something here is wrong or missing",
    ]}
    return out


# ── Find ─────────────────────────────────────────────────────────────


@server.tool(annotations=READ_ONLY)
@audited()
async def find(question: str, scope: str = "all", kinds: str = "", limit: int = 8) -> Dict[str, Any]:
    """Search the warehouse and the industry knowledge at once.

    Ask the way a person would ("ICS sales at invoice line level", "net sales from
    distributor data", "which columns hold NPIs") or give a name or part of one.
    Returns up to three sections:
      data       tables, pipelines, tasks, schemas — by meaning, keywords and name, with trust
      columns    columns whose name matches, when the question is or contains a name
      knowledge  industry concepts — dataset types, identifiers, metrics, regulations — with
                 how many warehouse tables and columns are bound to each

    Args:
        question: What you are looking for, in plain words or as a name.
        scope: "all" (default), "data" (warehouse only) or "knowledge" (industry only).
        kinds: Optional comma-separated filter for data: table, job, task, schema, catalog, column.
        limit: Maximum results per section (default 8).
    """
    from kairos_kb.context.search import _name_query, find_data, looks_like_a_name
    from kairos_kb.knowledge.search import find_knowledge

    question = (question or "").strip()
    if not question:
        return {"error": "Ask a question or give a name to search for."}
    scope = scope if scope in ("all", "data", "knowledge") else "all"
    limit = max(1, min(limit, 30))
    kind_list = [k.strip() for k in kinds.split(",") if k.strip()]
    data_kinds = [k for k in kind_list if k != "column"] or None
    want_columns = "column" in kind_list or (not kind_list and looks_like_a_name(question))
    agent = current_agent()
    out: Dict[str, Any] = {"question": question}

    async with async_session_factory() as db:
        if scope in ("all", "data") and kind_list != ["column"]:
            found = await find_data(db, question, agent, kinds=data_kinds, limit=limit)
            out["data"] = found.get("results", [])
        if scope in ("all", "data") and want_columns:
            # Match the column's own name, not its table's (npi_info.insert_date is not an NPI):
            # exact names first, then prefixes, then any column containing it.
            name = _name_query(question).lower()
            low = func.lower(Column.name)
            rows = (await db.execute(
                select(Column.entity_id, Column.name, Column.full_name, Column.data_type)
                .where(low.contains(name))
                .order_by((low == name).desc(), low.startswith(name).desc(), func.length(Column.name), Column.full_name)
                .limit(400)
            )).all()
            hits = [r for r in rows if agent.sees_entity(r.entity_id)]
            out["columns"] = [{"entity_id": r.entity_id, "name": r.name, "type": r.data_type,
                               "table": r.full_name[: -len(r.name) - 1] if r.full_name.endswith(r.name) else r.full_name}
                              for r in hits[:limit * 3]]
            if len(hits) > limit * 3:
                out["columns_more"] = len(hits) - limit * 3
        if scope in ("all", "knowledge"):
            known = await find_knowledge(db, question, limit=limit)
            out["knowledge"] = known.get("results", [])

    out["next"] = ("get_context(entity_id) for a table, pipeline or column; get_concept(concept_id) for an "
                   "industry concept — it lists the warehouse tables and columns bound to it. Knowledge "
                   "describes the industry in general, not this warehouse.")
    return out


# ── Understand ───────────────────────────────────────────────────────


@server.tool(annotations=READ_ONLY)
@audited()
async def get_context(entity_id: str, detail: str = "summary", max_columns: int = 150) -> Dict[str, Any]:
    """Everything needed to understand and use one entity.

    For a table: summary and purpose, trust and checks, grain and key, columns with
    meanings, what produces and reads it, example SQL, join candidates, caveats, and
    the industry section (dataset type, identifier columns, rules that apply).
    For a pipeline or task: its tasks, what it reads and writes, run health with errors.
    For any other entity (a column, a run, a schema…): its stored attributes and links.

    Args:
        entity_id: From find() or any other tool, e.g. 'table:<workspace>:<catalog>.<schema>.<table>'.
        detail: "summary" (default) — the essentials. "full" — every column, all neighbours,
            full run history with tracebacks. "raw" — also every stored platform attribute
            and the full profile document Kairos generated.
        max_columns: Cap on columns returned in full detail for very wide tables.
    """
    from kairos_kb.context.cards import entity_card, summarize_card

    if entity_id.startswith("product:"):
        # A data product: the same view get_data_product gives, resolved through the entity
        # (two connections may each have a product called "sales").
        from kairos_kb.models.discovered import DiscoveredEntity

        async with async_session_factory() as db:
            ent = (await db.execute(select(DiscoveredEntity).where(
                DiscoveredEntity.entity_id == entity_id))).scalars().first()
        if ent is None or not current_agent().sees_entity(entity_id):
            return {"error": f"Unknown data product: {entity_id}. Use list_data_products() to see what exists."}
        return await _raw(get_data_product)((ent.attrs or {}).get("product_id") or ent.full_name)
    async with async_session_factory() as db:
        card = await entity_card(db, entity_id, max_columns=max(10, min(max_columns, 1000)))
    if card is None:
        # Not a kind with a card (a column, a run…): the stored record and its links.
        record = await _raw(v1.get_entity)(entity_id)
        if not record.get("known") and not record.get("attributes"):
            return {"error": f"Unknown entity: {entity_id}. Use find() to find it."}
        return record
    if detail == "raw":
        card["stored"] = await _raw(v1.get_entity)(entity_id)
        profile = await _raw(v1.get_entity_profile)(entity_id, include_document=True)
        card["profile_document"] = profile.get("document")
        return card
    return card if detail == "full" else summarize_card(card)


@server.tool(annotations=READ_ONLY)
@audited()
async def get_concept(concept_id: str) -> Dict[str, Any]:
    """One industry concept in full, and where it appears in this warehouse.

    Definition, grain and keys, schema, pitfalls, typical uses, related concepts,
    sources — and the tables and columns bound to it (proposed by Kairos or
    confirmed by a person).

    Args:
        concept_id: From find() or a table's industry section, e.g. '/identifiers/provider/npi'.
    """
    return await _raw(v1.get_concept)(concept_id)


# ── Data products ────────────────────────────────────────────────────


@server.tool(annotations=READ_ONLY)
@audited()
async def list_data_products() -> Dict[str, Any]:
    """The data products on this platform: business concepts (Sales, Delivery performance …) served as one unit.

    Each consolidates a concept from its warehouse: metrics defined once, dimensions,
    named tools, contracts and health. When a question fits a product, answer from it
    with query_data_product() instead of writing SQL against tables.
    """
    from kairos_kb.models.data_product import DataProduct
    from kairos_kb.models.workspace import Workspace
    from kairos_kb.products.service import contracts_of

    agent = current_agent()
    products = []
    async with async_session_factory() as db:
        names = {w.id: w.name for w in (await db.execute(select(Workspace))).scalars()}
        for p in (await db.execute(select(DataProduct).order_by(DataProduct.name))).scalars().all():
            ws = names.get(p.workspace_id, "")
            if not agent.sees_workspace_name(ws):
                continue
            model = (p.spec or {}).get("model") or {}
            products.append({
                "product": p.name, "id": p.slug, "connection": ws, "domain": p.domain, "status": p.status,
                "health": (await contracts_of(db, p))["health"]["status"], "description": p.description,
                "metrics": [m["name"] for m in model.get("metrics") or []],
                "dimensions": [d["name"] for d in model.get("dimensions") or []],
                "tools": [t["name"] for t in model.get("tools") or []],
            })
    return {"products": products, "count": len(products),
            "next": "get_data_product(id) for its definitions and rules; query_data_product(id, metrics, by) to answer."}


async def _product_for(ref: str):
    from kairos_kb.models.workspace import Workspace
    from kairos_kb.products.service import find_product

    agent = current_agent()
    async with async_session_factory() as db:
        allowed = None
        if agent.workspace_names is not None:
            allowed = [w.id for w in (await db.execute(select(Workspace))).scalars()
                       if agent.sees_workspace_name(w.name)]
        return await find_product(db, ref, allowed)


@server.tool(annotations=READ_ONLY)
@audited()
async def get_data_product(product: str) -> Dict[str, Any]:
    """One data product: how to ask it, what its metrics and dimensions mean, its rules, ports and contracts.

    Returns the metrics (each defined once, with its formula and caveats), the dimensions
    to slice by, named tools, entities, glossary, rules for answering, input ports,
    supply chain, contracts with their status, and policies.

    Args:
        product: The product's id or name, from list_data_products().
    """
    from kairos_kb.models.workspace import Workspace
    from kairos_kb.products.service import for_agent

    p = await _product_for(product)
    if p is None:
        return {"error": f"No data product '{product}'. Use list_data_products() to see what exists."}
    async with async_session_factory() as db:
        ws = await db.get(Workspace, p.workspace_id)
        return await for_agent(db, p, ws.name if ws else "")


@server.tool(annotations=PLATFORM_READ)
@audited("query")
async def query_data_product(product: str, metrics: List[str] | None = None, by: List[str] | None = None,
                             filters: List[Dict[str, Any]] | None = None, tool: str = "", order: str = "",
                             limit: int = 100) -> Dict[str, Any]:
    """Answer a question from a data product: name metrics and dimensions, never tables.

    Kairos compiles the request to read-only SQL, using a pre-aggregated table when
    one answers it and the base table otherwise, and runs it on the platform with
    personal data masked. The result includes the SQL. Needs the 'query' permission.

    Args:
        product: The product's id or name.
        metrics: Metric names from get_data_product(), e.g. ["gmv", "orders"].
        by: Dimension names; a time dimension takes a grain, e.g. ["city", "order_date:month"].
        filters: e.g. [{"dimension": "city", "op": "=", "value": "Delhi"}]; ops: = != > >= < <= in, not in, between, like.
        tool: Instead of metrics/by, run one of the product's named tools.
        order: A requested metric or dimension, optionally "asc"/"desc", e.g. "gmv desc".
        limit: Maximum rows (default 100).
    """
    from kairos_kb.products.service import query, run_tool

    p = await _product_for(product)
    if p is None:
        return {"error": f"No data product '{product}'. Use list_data_products() to see what exists."}
    async with async_session_factory() as db:
        if tool:
            return await run_tool(db, p, current_agent(), tool, filters, limit)
        return await query(db, p, current_agent(), metrics=metrics or [], by=by, filters=filters, order=order,
                           limit=limit)


# ── Connect ──────────────────────────────────────────────────────────


@server.tool(annotations=READ_ONLY)
@audited()
async def trace(entity_id: str, direction: str = "both", relations: str = "", limit: int = 25) -> Dict[str, Any]:
    """Follow the data flow from one entity.

    upstream    what feeds it: tables it is built from (platform lineage), the tasks
                that write it, and — for a task — the tables it reads
    downstream  what depends on it: tables built from it, tasks that read it, and —
                for a task — the tables it writes. Use before changing or deleting.
    both        upstream and downstream (default)
    neighbours  every direct link of any kind: a table's columns, a schema's tables, a
                job's tasks, evidence and discovered relations; filter with `relations`

    Links found by reading pipeline code carry a confidence and rationale — weigh them
    as inference; platform lineage is reported by Databricks.

    Args:
        entity_id: A table, task, job or any other entity_id.
        direction: upstream | downstream | both | neighbours.
        relations: For neighbours only: comma-separated relation filter, e.g. 'HAS_COLUMN'.
        limit: For neighbours only: maximum neighbours per relation.
    """
    direction = direction.lower().strip()
    if direction == "neighbours" or direction == "neighbors":
        return await _raw(v1.explore_entity)(entity_id, relations, max(1, min(limit, 100)))
    if direction not in ("upstream", "downstream", "both"):
        return {"error": "direction must be upstream, downstream, both or neighbours."}

    deps = await _raw(v1.get_data_dependencies)(entity_id)
    impact = await _raw(v1.get_blast_radius)(entity_id)
    out: Dict[str, Any] = {"entity_id": entity_id}
    if direction in ("upstream", "both"):
        out["upstream"] = {
            "built_from_tables": deps.get("lineage_upstream", []),
            "written_by": impact.get("written_by", []),
            "reads": deps.get("reads", []),
        }
    if direction in ("downstream", "both"):
        out["downstream"] = {
            "tables_built_from_it": sorted(set(deps.get("lineage_downstream", [])) | set(impact.get("flows_into", []))),
            "read_by": impact.get("read_by", []),
            "writes": deps.get("writes", []),
        }
    if deps.get("other_links"):
        out["other_links"] = deps["other_links"]
    if deps.get("note"):
        out["note"] = deps["note"]
    return out


@server.tool(annotations=READ_ONLY)
@audited()
async def find_join_path(from_entity: str, to_entity: str) -> Dict[str, Any]:
    """How to join two tables, with the evidence for it.

    The recommended key columns (grain keys and identifier columns the tables share,
    with type compatibility), whether a pipeline already combines them, example SQL —
    or, when they share no key, bridge tables to go through.

    Args:
        from_entity: A table entity_id.
        to_entity: Another table entity_id.
    """
    return await _raw(v1.find_join_path)(from_entity, to_entity)


# ── Operate ──────────────────────────────────────────────────────────


@server.tool(annotations=READ_ONLY)
@audited()
async def list_incidents(pipeline: str = "", limit: int = 25) -> Dict[str, Any]:
    """Recent failed pipeline runs, newest first, with what failed and why as recorded.

    Each failure names the pipeline, when it ran, and the tasks that failed — with the
    exact error and where it was raised (notebook cell, line, function) when Kairos has
    read it. Facts as of the last sync; get_context() on a pipeline or task gives its
    full run history and traceback.

    Args:
        pipeline: Optional pipeline name or entity_id (partial names work).
        limit: Maximum failed runs (default 25).
    """
    return await _raw(v1.list_incidents)(pipeline, limit)


# ── Verify on the live platform ──────────────────────────────────────


@server.tool(annotations=PLATFORM_READ)
@audited()
async def check_key_uniqueness(entity_id: str, columns: str) -> Dict[str, Any]:
    """Test whether a set of columns uniquely identifies rows of a table, on the live data.

    Runs a read-only COUNT DISTINCT (cached for an hour) and returns rows, distinct keys,
    duplicates, NULLs in the key and example duplicates. Use before aggregating or
    joining on a key you are not sure of.

    Args:
        entity_id: A table entity_id.
        columns: Key columns, comma-separated, e.g. 'INVOICE_ID, INVOICE_ITEM'.
    """
    return await _raw(v1.check_key_uniqueness)(entity_id, columns)


@server.tool(annotations=PLATFORM_READ)
@audited("query")
async def run_sql(sql: str, limit: int = 100) -> Dict[str, Any]:
    """Run one read-only SQL query on the data platform and return the rows.

    Only SELECT, WITH, SHOW, DESCRIBE and EXPLAIN run; fully qualified tables from the
    map only. Values in personal-data columns are masked (aggregate or filter on them
    instead). Each result restates what the map knows about its tables. Use
    get_context() and find_join_path() first. Needs the 'query' permission.

    Args:
        sql: A single read-only statement (Databricks SQL), with fully qualified table names.
        limit: Maximum rows to return (default 100).
    """
    return await _raw(v1.run_sql)(sql, limit)


@server.tool(annotations=PLATFORM_READ)
@audited("files")
async def volume_files(path: str, action: str = "list", max_rows: int = 50) -> Dict[str, Any]:
    """List a Unity Catalog Volume folder, or read the start of a text file in one.

    For files no table answers: an upload not yet loaded, a config or mapping file a
    pipeline reads, the raw feed behind a failure. Reading masks columns whose header
    names identifying data and redacts e-mail addresses and phone numbers, and names
    the tables built from the file — prefer those when they hold what you need.
    Needs the 'files' permission.

    Args:
        path: '/Volumes/<catalog>/<schema>/<volume>/<folder>' to list, or a file path to read.
        action: "list" (default) or "read".
        max_rows: For read: rows (or about four times as many lines of text), up to 500.
    """
    if action == "read":
        return await _raw(v1.read_volume_file)(path, max_rows)
    if action != "list":
        return {"error": "action must be list or read."}
    return await _raw(v1.list_volume_files)(path)


# ── Improve ──────────────────────────────────────────────────────────


@server.tool(annotations=KAIROS_WRITE)
@audited()
async def report_context_issue(entity_id: str, kind: str, message: str, field: str = "",
                               suggestion: str = "") -> Dict[str, Any]:
    """Tell Kairos that context about an entity is wrong, missing, stale or confusing.

    Shown to every other agent in that entity's context at once, and verified by the
    enrichment agent on its next pass. kind='useful' confirms context that helped.
    Writes only to Kairos, never to the data platform.

    Args:
        entity_id: The entity the report is about.
        kind: incorrect | missing | stale | confusing | useful
        message: What is wrong or missing, specifically.
        field: Optional: which part (e.g. 'grain', 'columns.ORG_VID', 'summary').
        suggestion: Optional: what it should say instead.
    """
    return await _raw(v1.report_context_issue)(entity_id, kind, message, field, suggestion)


# ── Resources and prompts ────────────────────────────────────────────


@server.resource("kairos://guide", name="guide", title="How to use Kairos",
                 description="The recommended workflow and what trust levels mean.", mime_type="text/markdown")
async def guide_resource() -> str:
    return INSTRUCTIONS


@server.prompt(name="start_here", title="Get oriented in this data platform")
def start_here(goal: str = "") -> str:
    """A first message for any agent new to this warehouse."""
    goal_line = f"My goal: {goal}\n\n" if goal else ""
    return (goal_line + "You are connected to Kairos. Call get_overview() first, then find() with what you "
            "need, then get_context() on the best match before using it. Prefer verified entities, read "
            "caveats, use find_join_path() before joining, and report anything wrong with report_context_issue().")


TOOL_NAMES: List[str] = [
    "get_overview", "find", "get_context", "get_concept", "trace", "find_join_path",
    "list_incidents", "check_key_uniqueness", "run_sql", "volume_files", "report_context_issue",
    "list_data_products", "get_data_product", "query_data_product",
]
