"""One MCP endpoint per connection, with tools for its platform.

    /mcp/c/<connection>    e.g. /mcp/c/ics-sales-warehouse, /mcp/c/zomato-snowflake

Every connection gets its own URL the moment it is added: an agent pointed at
it sees only that connection's map, in that platform's words. Underneath there
is one server per platform, not per connection:

  shared core   get_overview, find, get_context, get_concept, trace, find_join_path,
                list_incidents, check_key_uniqueness, run_sql, report_context_issue,
                list_data_products, get_data_product, query_data_product —
                the same functions as /mcp-v2, so an agent, prompt or evaluation
                that works on one endpoint works on all of them
  Databricks    + volume_files (Unity Catalog Volumes), table_history (Delta history)
  Snowflake     + stage_files (@stage files), object_ddl (GET_DDL definitions)

Scope comes from the URL: the request's agent identity is narrowed to the one
connection, and every tool already filters by the identity, so search, cards,
SQL, lineage and incidents all stay inside it. An agent key limited to other
connections is refused here. Calls are audited on channel "mcp:<connection>".
"""

from __future__ import annotations

import dataclasses
import json
import logging
from typing import Any, Dict

from mcp.server import MCPServer

from kairos_kb.context.access import AccessDenied, audited, current_agent, key_from_headers, resolve_identity, set_current_agent
from kairos_kb.db.engine import async_session_factory
from kairos_kb.mcp_server import server as v1
from kairos_kb.mcp_server import server_v2 as v2

logger = logging.getLogger(__name__)

PREFIX = "/mcp/c/"

_COMMON = """
1. get_overview() — what this connection holds: data products, key tables, pipelines, trust, freshness,
   and which industry dataset types it contains.
2. find(question) — one search over this connection's tables, pipelines and columns and over the
   industry knowledge (dataset types, identifiers, metrics, regulations). Plain words or names.
3. get_context(entity_id) — one entity in full: meaning, grain, columns, flow, example SQL, joins,
   caveats, industry bindings. get_concept(concept_id) — one industry concept and where it appears here.
4. trace(entity_id, direction) — upstream sources and downstream dependants; find_join_path(a, b) —
   how to join two tables; list_incidents() — recent failed runs with the exact error.
5. check_key_uniqueness / run_sql — verify on the live platform (read-only; run_sql needs the query
   permission). Use fully qualified names from the map; personal data is masked.
6. report_context_issue(entity_id, kind, message) — when something here is wrong or missing.
7. list_data_products() / get_data_product(product) — business concepts served as one unit (Sales …): metrics
   defined once, dimensions, rules, contracts. query_data_product(product, metrics, by, filters) answers from it.

Trust: verified (profiled, every check passed) > profiled (read the caveats) > synced (metadata only).
Kairos never changes the platform."""

INSTRUCTIONS = {
    "databricks": (
        "Kairos context for one Databricks workspace: Unity Catalog catalogs, schemas, tables and columns, "
        "Jobs with their tasks and runs, and lineage from system tables — profiled, checked by code, and "
        "linked to US pharma industry knowledge. Names are catalog.schema.table; SQL is Databricks SQL."
        + _COMMON + """
Databricks only:
7. volume_files(path, action) — list or read files in a Unity Catalog Volume (/Volumes/…; files permission).
8. table_history(entity_id) — a Delta table's write history: each version, operation, job and time."""),
    "snowflake": (
        "Kairos context for one Snowflake account: databases, schemas, tables, views, dynamic tables and "
        "streams with their columns, task graphs, Snowpipes and dynamic-table refreshes with their runs, and "
        "lineage from object dependencies and access history — profiled, checked by code, and linked to US "
        "pharma industry knowledge. Names are DATABASE.SCHEMA.OBJECT (upper case unless quoted); SQL is "
        "Snowflake SQL." + _COMMON + """
Snowflake only:
7. stage_files(path, action) — list or read files on a stage (@DATABASE.SCHEMA.STAGE/…; files permission).
8. object_ddl(object_name, kind) — the definition of a view, procedure, task, pipe, stream or table."""),
}

CORE = [
    (v2.get_overview, v1.READ_ONLY), (v2.find, v1.READ_ONLY), (v2.get_context, v1.READ_ONLY),
    (v2.get_concept, v1.READ_ONLY), (v2.trace, v1.READ_ONLY), (v2.find_join_path, v1.READ_ONLY),
    (v2.list_incidents, v1.READ_ONLY), (v2.check_key_uniqueness, v1.PLATFORM_READ),
    (v2.run_sql, v1.PLATFORM_READ), (v2.report_context_issue, v1.KAIROS_WRITE),
    (v2.list_data_products, v1.READ_ONLY), (v2.get_data_product, v1.READ_ONLY),
    (v2.query_data_product, v1.PLATFORM_READ),
]


# ── Platform-only tools ──────────────────────────────────────────────


@audited()
async def table_history(entity_id: str, limit: int = 20) -> Dict[str, Any]:
    """A Delta table's write history, newest first: version, time, operation, the job that wrote it.

    Use it to see when a table last changed, which pipeline writes it, and how big each write was.
    Views and non-Delta tables have no history.

    Args:
        entity_id: A table entity_id from find() or get_context().
        limit: Versions to return (default 20, at most 50).
    """
    from kairos_kb.context.platform_tools import table_history as run

    async with async_session_factory() as db:
        return await run(db, current_agent(), entity_id, limit)


@audited("files")
async def stage_files(path: str, action: str = "list", max_rows: int = 50) -> Dict[str, Any]:
    """List files on a Snowflake stage, or read the start of one.

    For files no table answers: a file waiting to be loaded, a Snowpipe's source, a mapping file.
    Reading masks columns whose header names identifying data and redacts e-mail addresses and phone
    numbers. Needs the 'files' permission.

    Args:
        path: '@DATABASE.SCHEMA.STAGE' or '@DATABASE.SCHEMA.STAGE/folder' to list, or '…/file.csv' to read.
        action: "list" (default) or "read".
        max_rows: For read: rows (or about four times as many lines of text), up to 500.
    """
    from kairos_kb.context.files import list_stage_files, read_stage_file

    async with async_session_factory() as db:
        if action == "read":
            return await read_stage_file(db, current_agent(), path, max_rows)
        if action != "list":
            return {"error": "action must be list or read."}
        return await list_stage_files(db, current_agent(), path)


@audited()
async def object_ddl(object_name: str, kind: str = "") -> Dict[str, Any]:
    """The definition of a Snowflake object, as GET_DDL returns it.

    For a view's or dynamic table's SQL, a procedure's code (what a task's CALL runs), a task's
    statement and schedule, a pipe's COPY statement or a stream's source.

    Args:
        object_name: DATABASE.SCHEMA.OBJECT; a procedure may add argument types, e.g. DB.SCH.LOAD(DATE).
        kind: procedure, task, pipe, function, stream, view, dynamic_table or table. Optional for tables
            and views in the map.
    """
    from kairos_kb.context.platform_tools import object_ddl as run

    async with async_session_factory() as db:
        return await run(db, current_agent(), object_name, kind)


EXTRAS = {
    "databricks": [(v2.volume_files, v1.PLATFORM_READ), (table_history, v1.PLATFORM_READ)],
    "snowflake": [(stage_files, v1.PLATFORM_READ), (object_ddl, v1.PLATFORM_READ)],
}


def _build(platform: str) -> MCPServer:
    srv = MCPServer(name=f"kairos-{platform}", title=f"Kairos — {platform.title()}",
                    instructions=INSTRUCTIONS[platform])
    for fn, hints in CORE + EXTRAS[platform]:
        srv.add_tool(fn, annotations=hints)

    @srv.resource("kairos://guide", name="guide", title="How to use Kairos",
                  description="The recommended workflow and what trust levels mean.", mime_type="text/markdown")
    async def guide() -> str:
        return INSTRUCTIONS[platform]

    @srv.prompt(name="start_here", title="Get oriented in this data platform")
    def start_here(goal: str = "") -> str:
        """A first message for any agent new to this connection."""
        return ((f"My goal: {goal}\n\n" if goal else "") +
                "You are connected to Kairos for one data platform. Call get_overview() first, then find() with "
                "what you need, then get_context() on the best match before using it.")

    return srv


SERVERS: Dict[str, MCPServer] = {p: _build(p) for p in INSTRUCTIONS}
TOOL_NAMES = {p: [fn.__name__ for fn, _ in CORE + EXTRAS[p]] for p in INSTRUCTIONS}


# ── Routing /mcp/c/<connection> to its platform's server ─────────────


async def _send_json(send, status: int, payload: Dict[str, Any]) -> None:
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": json.dumps(payload).encode("utf-8")})


class ConnectionEndpoints:
    """ASGI middleware: requests under /mcp/c/<slug> go to that connection's platform server, scoped to it."""

    def __init__(self, app, platform_apps: Dict[str, Any]) -> None:
        self.app = app
        self.platform_apps = platform_apps

    async def __call__(self, scope, receive, send):
        path = scope.get("path") or ""
        if scope["type"] != "http" or not path.startswith(PREFIX):
            await self.app(scope, receive, send)
            return
        slug, _, rest = path[len(PREFIX):].partition("/")
        from kairos_kb.connectors.factory import connections_by_slug

        async with async_session_factory() as db:
            ws = (await connections_by_slug(db)).get(slug) or (await connections_by_slug(db, fresh=True)).get(slug)
        if ws is None:
            await _send_json(send, 404, {"error": f"No connection '{slug}'. The Connections screen lists each "
                                                  "connection's endpoint."})
            return
        platform = ws.platform or "databricks"
        sub = self.platform_apps.get(platform)
        if sub is None:
            await _send_json(send, 503, {"error": f"The {platform} endpoint is not available."})
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        try:
            identity = await resolve_identity(key_from_headers(headers), f"mcp:{slug}")
        except AccessDenied as exc:
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b'Bearer realm="kairos"')]})
            await send({"type": "http.response.body", "body": json.dumps({"error": str(exc)}).encode("utf-8")})
            return
        if identity.workspace_ids is not None and str(ws.id) not in identity.workspace_ids:
            await _send_json(send, 403, {"error": f"This agent key is not allowed on the '{ws.name}' connection."})
            return
        # The URL is the scope: this request sees one connection and nothing else.
        scoped = dataclasses.replace(identity, workspace_ids=frozenset({str(ws.id)}),
                                     workspace_names=frozenset({ws.name}))
        root = f"{PREFIX}{slug}"
        sub_scope = dict(scope, root_path=root, path=f"{root}/{rest}",
                         raw_path=f"{root}/{rest}".encode("utf-8"))
        token = set_current_agent(scoped)
        try:
            await sub(sub_scope, receive, send)
        finally:
            from kairos_kb.context.access import _current

            _current.reset(token)
            logger.info("MCP %s %s connection=%s platform=%s agent=%s", scope.get("method"), path, ws.name,
                        platform, identity.name)
