"""An enrichment run works on the connection its entities belong to, never a guessed one."""

import asyncio

import pytest

from kairos_kb.api.v1.enrichment import connection_names, resolve_workspace
from kairos_kb.exceptions import KairosException


def test_connection_names_come_from_entity_ids():
    ids = ["table:ICS Sales Warehouse:cat.sch.t", "task:ICS Sales Warehouse:123:raw_to_stg", "bad-id"]
    assert connection_names(ids) == {"ICS Sales Warehouse"}
    assert connection_names(None) == set()


def test_a_run_mixing_connections_is_refused_before_anything_runs():
    ids = ["table:ICS Sales Warehouse:cat.sch.t", "table:Zomato Snowflake:ZOMATO.RAW.ORDERS"]
    with pytest.raises(KairosException, match="one connection"):
        asyncio.run(resolve_workspace(None, None, ids))
