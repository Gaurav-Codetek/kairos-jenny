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
