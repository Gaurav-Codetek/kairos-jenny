"""Each Databricks connection can hold its own token and SQL warehouse: sealed, never shown, used by its connector."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from kairos_kb.connectors import credentials, factory
from kairos_kb.exceptions import KairosException
from kairos_kb.schemas.workspace import WorkspaceResponse


def ws(host, config, platform="databricks"):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(id=uuid.uuid4(), workspace_id="abcd1234", name=host, platform=platform, host=host,
                           connection_config=config, cloud="aws", region="", status="registered",
                           last_synced_at=None, description=None, created_at=now, updated_at=now)


def test_two_workspaces_each_use_their_own_token_and_warehouse():
    a = ws("https://a.cloud.databricks.com", credentials.seal({"warehouse_id": "wh-a"}, "dapi-AAA"))
    b = ws("https://b.cloud.databricks.com", credentials.seal({"warehouse_id": "wh-b"}, "dapi-BBB"))
    ca, cb = factory.connector_for(a), factory.connector_for(b)
    assert (ca._host, ca._token, ca._warehouse_id) == ("https://a.cloud.databricks.com", "dapi-AAA", "wh-a")
    assert (cb._host, cb._token, cb._warehouse_id) == ("https://b.cloud.databricks.com", "dapi-BBB", "wh-b")


def test_a_connection_without_its_own_token_uses_the_server_settings(monkeypatch):
    s = factory_settings = SimpleNamespace(**vars(credentials.get_settings()))
    s.databricks_token, s.databricks_sql_warehouse_id = "dapi-ENV", "wh-env"
    monkeypatch.setattr("kairos_kb.connectors.databricks.get_settings", lambda: factory_settings)
    c = factory.connector_for(ws("https://c.cloud.databricks.com", None))
    assert (c._token, c._warehouse_id) == ("dapi-ENV", "wh-env")


def test_the_token_is_sealed_and_never_shown():
    config = credentials.seal({"warehouse_id": "wh-a"}, "dapi-SECRET")
    assert "dapi-SECRET" not in str(config)
    shown = WorkspaceResponse.model_validate(ws("https://a", config)).model_dump()
    assert shown["connection_config"] == {"warehouse_id": "wh-a", "has_token": True}
    assert "dapi-SECRET" not in str(shown) and credentials.SEALED not in str(shown)


def test_a_token_sealed_under_another_secret_key_reads_as_none(monkeypatch):
    config = credentials.seal({}, "dapi-OLD")
    other = SimpleNamespace(**vars(credentials.get_settings()))
    other.secret_key = "a-different-key"
    monkeypatch.setattr(credentials, "get_settings", lambda: other)
    assert credentials.token_of(config) is None


def test_blank_token_keeps_config_and_production_needs_a_real_secret_key(monkeypatch):
    assert credentials.seal({"warehouse_id": "w"}, "  ") == {"warehouse_id": "w"}
    prod = SimpleNamespace(**vars(credentials.get_settings()))
    prod.secret_key, prod.app_env = credentials.DEFAULT_SECRET, "production"
    monkeypatch.setattr(credentials, "get_settings", lambda: prod)
    with pytest.raises(KairosException):
        credentials.seal({}, "dapi-X")


# ── Two Databricks workspaces side by side ──────────────────────────


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


class _DB:
    def __init__(self, *results):
        self._results = list(results)

    async def execute(self, _stmt):
        return _Rows(self._results.pop(0))


def test_a_table_name_in_two_workspaces_is_not_guessed():
    import asyncio

    from kairos_kb.context.access import AgentIdentity
    from kairos_kb.context.query import run_sql

    a, b = uuid.uuid4(), uuid.uuid4()
    db = _DB([("table:Sales A:main.sales.orders", "main.sales.orders", a),
              ("table:Sales B:main.sales.orders", "main.sales.orders", b)])
    agent = AgentIdentity(agent_id=uuid.uuid4(), name="q", scopes=frozenset({"read", "query"}))
    out = asyncio.run(run_sql(db, agent, "SELECT count(*) FROM main.sales.orders"))
    assert "more than one connection (Sales A, Sales B)" in out["error"]


def test_one_query_runs_on_one_connection():
    import asyncio

    two = [ws("https://a", None), ws("https://b", None)]
    two[0].name, two[1].name = "Sales A", "Sales B"
    connector, why = asyncio.run(factory.connector_for_tables(_DB(two), ["a.s.t", "b.s.u"],
                                                              workspace_ids=[w.id for w in two]))
    assert connector is None and "different connections (Sales A, Sales B)" in why
    one, _ = asyncio.run(factory.connector_for_tables(_DB(two[:1]), ["a.s.t"], workspace_ids=[two[0].id]))
    assert one._host == "https://a"


def test_a_connection_can_be_pointed_at_another_warehouse():
    import asyncio

    from kairos_kb.api.v1.workspaces import set_workspace_warehouse
    from kairos_kb.schemas.workspace import WorkspaceWarehouse

    w = ws("https://a", credentials.seal({"warehouse_id": "wrong"}, "dapi-A"))

    class DB:
        async def get(self, _model, _id):
            return w

        async def flush(self):
            pass

        async def refresh(self, _obj):
            pass

    asyncio.run(set_workspace_warehouse(w.id, WorkspaceWarehouse(warehouse_id=" 1a2b3c "), DB()))
    c = factory.connector_for(w)
    assert (c._warehouse_id, c._token) == ("1a2b3c", "dapi-A")  # the token is kept
