"""The map in words: evidence, changes and links said as what they are, and the map MCP endpoint."""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from kairos_kb.context.access import AgentIdentity
from kairos_kb.warehouse.entity_graph import _entity_payload
from kairos_kb.warehouse.evidence_text import change_label, change_summary, evidence_digest
from kairos_kb.warehouse.map_view import visible

WHEN = datetime(2026, 10, 10, 7, 55, tzinfo=timezone.utc)


def _evidence(content, source_type="API_RESPONSE", source_id=None):
    return SimpleNamespace(id=uuid.uuid4(), content=content, source_type=source_type, source_id=source_id,
                           entity_id="table:Zomato Snowflake:ZOMATO.RAW.ORDERS", observed_at=WHEN,
                           metadata_extra=None, content_hash="ab" * 32)


def test_table_metadata_reads_as_the_table_not_an_id():
    row = _evidence(json.dumps({"name": "ORDERS", "full_name": "ZOMATO.RAW.ORDERS", "table_type": "MANAGED",
                                "data_source_format": "SNOWFLAKE", "columns": [{"name": "A"}, {"name": "B"}]}))
    d = evidence_digest(row)
    assert d["title"] == "Table metadata: ZOMATO.RAW.ORDERS"
    assert d["summary"] == "MANAGED · SNOWFLAKE · 2 columns"
    assert d["source_label"] == "Platform metadata"
    assert "excerpt" not in d


def test_job_definition_and_emails_are_masked_in_the_excerpt():
    row = _evidence(json.dumps({"job_id": 7, "creator_user_name": "someone@example.com",
                                "settings": {"name": "ingest", "tasks": [{}, {}],
                                             "schedule": {"quartz_cron_expression": "0 0 6 * * ?"}}}))
    d = evidence_digest(row, excerpt_chars=2000)
    assert d["title"] == "Job definition: ingest"
    assert "2 tasks" in d["summary"] and "0 0 6 * * ?" in d["summary"]
    assert "someone@example.com" not in d["excerpt"] and "<email>" in d["excerpt"]
    assert d["truncated"] is False


def test_file_evidence_names_the_file():
    d = evidence_digest(_evidence("SELECT *\nFROM orders", "FILE_CONTENT", "/Workspace/etl/load.sql"))
    assert d["title"] == "File read: /Workspace/etl/load.sql"
    assert d["summary"] == "SELECT *"


def test_long_evidence_is_cut_and_says_so():
    d = evidence_digest(_evidence("x" * 9000, "FILE_CONTENT", "big.txt"), excerpt_chars=100)
    assert len(d["excerpt"]) == 100 and d["truncated"] is True and d["size_chars"] == 9000


def test_whole_evidence_text_when_asked_for_everything():
    from kairos_kb.warehouse.map_view import WHOLE_TEXT

    d = evidence_digest(_evidence("x" * 90000, "FILE_CONTENT", "big.txt"), excerpt_chars=WHOLE_TEXT)
    assert len(d["excerpt"]) == 90000 and d["truncated"] is False


def test_graph_card_for_evidence_shows_what_it_is():
    row = _evidence(json.dumps({"name": "ORDERS", "full_name": "ZOMATO.RAW.ORDERS", "columns": []}))
    p = _entity_payload("evidence", f"evidence:{row.id}", row)
    assert p["label"] == "Table metadata: ZOMATO.RAW.ORDERS"
    assert str(row.id) not in p["label"] + p["sublabel"]


def test_change_in_words():
    row = SimpleNamespace(change_type="MODIFIED", entity_type="TABLE", field_name="table_type",
                          entity_id="table:Zomato Snowflake:ZOMATO.MARTS.FCT", old_value="TRANSIENT",
                          new_value="MANAGED", detected_at=WHEN)
    assert change_label(row) == "Modified table (table_type)"
    assert change_summary(row) == "Modified table (table_type) ZOMATO.MARTS.FCT · TRANSIENT → MANAGED · 2026-10-10"
    p = _entity_payload("change", "change:x", row)
    assert p["label"] == "Modified table (table_type)" and p["sublabel"] == "ZOMATO.MARTS.FCT"


def test_items_outside_the_keys_connections_are_hidden():
    scoped = AgentIdentity(agent_id=None, name="a", workspace_ids=frozenset({"1"}),
                           workspace_names=frozenset({"Zomato Snowflake"}))
    assert visible(None, {"connection": "ICS"})
    assert visible(scoped, {"connection": "Zomato Snowflake"})
    assert not visible(scoped, {"connection": "ICS Sales Warehouse"})
    assert not visible(scoped, {"connection": None})


def test_map_endpoint_serves_its_tools_read_only():
    from kairos_kb.mcp_server import map_server

    tools = asyncio.run(map_server.server.list_tools())
    assert sorted(t.name for t in tools) == sorted(map_server.TOOL_NAMES)
    assert all(t.annotations.read_only_hint for t in tools)
    # node_id, not entity_id: evidence:<uuid> carries no connection name, so the map checks access itself.
    assert "node_id" in next(t for t in tools if t.name == "get_map_entity").input_schema["properties"]
    # Nothing is capped: no knob that limits how much comes back.
    knobs = {p for t in tools for p in t.input_schema["properties"]}
    assert not knobs & {"limit", "per_relation", "limit_per_relation"}
