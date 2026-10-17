"""Per-connection MCP endpoints: slugs, platform tool sets, and the /mcp/c/<slug> dispatcher's scoping."""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from kairos_kb.connectors import factory
from kairos_kb.context import access
from kairos_kb.mcp_server import connections as conn


def test_slugs_are_url_safe_names():
    assert factory.connection_slug("ICS Sales Warehouse") == "ics-sales-warehouse"
    assert factory.connection_slug("Zomato  (Snowflake)!") == "zomato-snowflake"
    assert factory.connection_slug("") == "connection"


def test_each_platform_serves_the_shared_core_plus_its_own_tools():
    core = {"get_overview", "find", "get_context", "get_concept", "trace", "find_join_path", "list_incidents",
            "check_key_uniqueness", "run_sql", "report_context_issue", "list_data_products", "get_data_product",
            "query_data_product"}
    dbx, sf = set(conn.TOOL_NAMES["databricks"]), set(conn.TOOL_NAMES["snowflake"])
    assert core <= dbx and core <= sf
    assert dbx - core == {"volume_files", "table_history"}
    assert sf - core == {"stage_files", "object_ddl"}

    async def listed(platform):
        tools = await conn.SERVERS[platform].list_tools()
        return {t.name: t for t in getattr(tools, "tools", tools)}

    sf_tools = asyncio.run(listed("snowflake"))
    assert sf_tools["run_sql"].annotations.open_world_hint is True
    assert sf_tools["report_context_issue"].annotations.read_only_hint is False
    assert "Snowflake" in conn.INSTRUCTIONS["snowflake"] and "DATABASE.SCHEMA.OBJECT" in conn.INSTRUCTIONS["snowflake"]


WS = SimpleNamespace(id=uuid.UUID("11111111-1111-1111-1111-111111111111"), name="Zomato Snowflake",
                     platform="snowflake")


@pytest.fixture
def dispatch(monkeypatch):
    seen = {}

    async def platform_app(scope, receive, send):
        seen["scope"] = scope
        seen["identity"] = access.current_agent()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def passthrough(scope, receive, send):
        seen["passthrough"] = scope["path"]

    async def by_slug(db, fresh=False):
        return {"zomato-snowflake": WS}

    monkeypatch.setattr(factory, "connections_by_slug", by_slug)
    app = conn.ConnectionEndpoints(passthrough, {"snowflake": platform_app})

    def call(path, identity=None):
        if identity is not None:
            async def resolve(key, channel):
                return identity
            monkeypatch.setattr(conn, "resolve_identity", resolve)
        sent = []

        async def send(msg):
            sent.append(msg)

        async def receive():
            return {"type": "http.request", "body": b""}

        asyncio.run(app({"type": "http", "path": path, "headers": [], "method": "POST"}, receive, send))
        status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
        body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        return status, body

    return call, seen


def test_a_connection_url_reaches_its_platform_scoped_to_that_connection(dispatch):
    call, seen = dispatch
    status, _ = call("/mcp/c/zomato-snowflake")
    assert status == 200
    ident = seen["identity"]
    assert ident.workspace_ids == frozenset({str(WS.id)}) and ident.workspace_names == frozenset({WS.name})
    assert ident.sees_entity("table:Zomato Snowflake:ZOMATO.RAW.ORDERS")
    assert not ident.sees_entity("table:ICS Sales Warehouse:c.s.t")
    assert seen["scope"]["root_path"] == "/mcp/c/zomato-snowflake"
    assert seen["scope"]["path"] == "/mcp/c/zomato-snowflake/"  # the bare URL works without a redirect


def test_unknown_connections_are_404_and_other_paths_pass_through(dispatch):
    call, seen = dispatch
    status, body = call("/mcp/c/nope/")
    assert status == 404 and b"No connection" in body
    call("/api/v1/workspaces")
    assert seen["passthrough"] == "/api/v1/workspaces"


def test_a_key_limited_to_other_connections_is_refused(dispatch):
    call, _ = dispatch
    other = access.AgentIdentity(agent_id=uuid.uuid4(), name="bi-copilot", scopes=frozenset({"read"}),
                                 workspace_ids=frozenset({"22222222-2222-2222-2222-222222222222"}),
                                 workspace_names=frozenset({"ICS Sales Warehouse"}))
    status, body = call("/mcp/c/zomato-snowflake/", identity=other)
    assert status == 403 and b"not allowed" in json.loads(body)["error"].encode()
