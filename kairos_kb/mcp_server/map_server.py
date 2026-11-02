"""Kairos Map over MCP: the map Kairos draws, for any application to draw too.

    /mcp-map

The same graph the Map screen shows — connections, catalogs, schemas, tables,
columns, pipelines, tasks, runs, files, evidence and change events, the links
between them, and each entity's enrichment profile — as data an outside
application can render. Nothing is an opaque id: every node comes with a
label, a one-line summary and its connection; every link the agent discovered
comes with why it believes it (rationale, confidence, where it was seen) and
the evidence it saw, in words, with e-mail addresses masked.

  orient   map_overview      connections, how many of each kind, the relation vocabulary
  find     search_map        entities by name
  draw     get_map           a neighbourhood: nodes + edges, ready to lay out
           get_mesh          the whole map as nested bundles (catalog → schema → table,
                             pipeline → task) with the flow between them
  inspect  get_map_entity    one entity in full: attributes, profile, evidence, relations

Nothing is capped: every match, every neighbour, the whole evidence text and
the whole profile flow through. Read-only. Scope is the agent key's: entities in connections the key cannot
see are left out. Calls are recorded on channel "mcp-map".
"""

from __future__ import annotations

from typing import Any, Dict

from mcp.server import MCPServer

from kairos_kb.context.access import audited, current_agent
from kairos_kb.db.engine import async_session_factory
from kairos_kb.mcp_server.server import READ_ONLY
from kairos_kb.warehouse import map_view

INSTRUCTIONS = """Kairos Map: the graph of a data platform — every catalog, schema, table, column, pipeline, task,
run, file, piece of evidence and change, how they connect, and what each one means — as data you can draw.

1. map_overview() — the connections and what each holds; the kinds of node and the relations between them.
2. search_map(query) — find an entity by name. Every result has an id you pass to the tools below.
3. get_map(node_id, depth) — a neighbourhood around one entity: nodes (label, summary, kind, connection) and edges
   (source, target, relation, group). Draw it as a left-to-right graph; edges point the way data or work flows.
   Start at a connection's root ("workspace:<name>") or at a table. Every neighbour comes back: no caps.
4. get_mesh(connection) — the whole connection at once as nested bundles with flow between them (dbt-style).
5. get_map_entity(node_id) — what to show when someone clicks a node: attributes, the whole enrichment profile
   (as a document and as YAML), the whole evidence text, and every related entity described.

Groups: lineage (data flow), discovered (links the agent found, each with a reason and evidence), pipeline (jobs and
tasks), structural (containment, columns), operational (runs), provenance (evidence, changes)."""

server = MCPServer(name="kairos-map", title="Kairos — Map", instructions=INSTRUCTIONS)


@audited()
async def map_overview(connection: str = "") -> Dict[str, Any]:
    """What the map holds: each connection with counts per kind, the node kinds and the relation vocabulary.

    Args:
        connection: Optional connection name (or slug) to describe just that one.
    """
    async with async_session_factory() as db:
        return await map_view.map_overview(db, current_agent(), connection)


@audited()
async def search_map(query: str, kinds: str = "", connection: str = "") -> Dict[str, Any]:
    """Find entities on the map by name: tables, columns, pipelines (jobs), tasks, runs, schemas, catalogs.
    Every match is returned.

    Args:
        query: Part of a name, e.g. "orders" or "ingest".
        kinds: Optional comma-separated kinds: catalog, schema, table, column, job, task, run, taskrun.
        connection: Optional connection name to search within.
    """
    kind_list = [k.strip() for k in kinds.split(",") if k.strip()] or None
    async with async_session_factory() as db:
        results = await map_view.search_map(db, query, identity=current_agent(), kinds=kind_list,
                                            connection=connection or None)
    return {"query": query, "count": len(results), "results": results}


@audited()
async def get_map(node_id: str, depth: int = 1, relation_groups: str = "") -> Dict[str, Any]:
    """A neighbourhood of the map around one entity, ready to draw: nodes and edges, every node described.
    Every neighbour at every hop is included.

    Each node: id, kind, label, sublabel, summary (from its profile, evidence or change), connection, status,
    depth from the root. Each edge: source, target, relation, group, and for a discovered link its reason
    (rationale, confidence, where it was seen, the evidence in words).

    Args:
        node_id: Where to start: an id from search_map or map_overview (a connection root is "workspace:<name>").
        depth: Hops out from the start (default 1). Each hop can multiply the size.
        relation_groups: Comma-separated subset of lineage, discovered, pipeline, structural, operational,
            provenance. Default: all of them.
    """
    from kairos_kb.warehouse.entity_map import RELATION_GROUPS

    groups = [g.strip() for g in relation_groups.split(",") if g.strip() in RELATION_GROUPS] or list(RELATION_GROUPS)
    async with async_session_factory() as db:
        return await map_view.map_graph(db, node_id, identity=current_agent(), depth=max(0, depth),
                                        relation_groups=groups)


@audited()
async def get_mesh(connection: str = "") -> Dict[str, Any]:
    """The whole map as nested bundles: catalog → schema → table, pipeline → task, plus volumes and data products,
    with relationships (containment, pipeline, depends_on, flow, storage) between them. Columns, runs and task
    runs are folded into their bundle as counts.

    Args:
        connection: Optional connection name; default every connection this key sees.
    """
    async with async_session_factory() as db:
        return await map_view.mesh_for(db, current_agent(), connection)


@audited()
async def get_map_entity(node_id: str) -> Dict[str, Any]:
    """One entity in full — what to show when someone clicks it on the map. Nothing is cut short.

    Its label and summary, stored attributes, the whole enrichment profile (as a document and as its YAML), the
    whole evidence text for an evidence node, and every relation with every related entity described (and for
    discovered links, the reason and evidence).

    Args:
        node_id: Any id from the map: table:…, job:…, evidence:…, change:…, workspace:…
    """
    async with async_session_factory() as db:
        card = await map_view.entity_card(db, node_id, identity=current_agent())
    return card if card is not None else {"error": f"No such entity for this agent: {node_id}"}


for _fn in (map_overview, search_map, get_map, get_mesh, get_map_entity):
    server.add_tool(_fn, annotations=READ_ONLY)

TOOL_NAMES = ["map_overview", "search_map", "get_map", "get_mesh", "get_map_entity"]


@server.resource("kairos://map-guide", name="map-guide", title="How to draw the Kairos map",
                 description="The node kinds, relation groups and the order to call the tools in.",
                 mime_type="text/markdown")
async def guide() -> str:
    return INSTRUCTIONS
