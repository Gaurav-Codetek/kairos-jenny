"""Row values that leave the platform are masked, agent-written file SQL is read-only,
and the RCA tools act on the incident's own connection."""

import asyncio
from types import SimpleNamespace

import pytest

from kairos_kb.agent import scope
from kairos_kb.agent.tools import query_databricks_data_file
from kairos_kb.context.privacy import is_masked, mask_rows, tagged_personal
from kairos_kb.context.query import MASK
from kairos_kb.enrichment import pipeline


def test_personal_columns_are_masked_by_name_and_by_profile_tag():
    rows = [{"customer_name": "Jane Doe", "acct_ref": "A-17", "units": 4, "note": "mail jane@x.com"}]
    out = mask_rows(rows, tagged={"acct_ref"})
    assert out[0]["customer_name"] == MASK          # name says personal
    assert out[0]["acct_ref"] == MASK               # the profile tagged it
    assert out[0]["units"] == 4                     # numbers pass through
    assert "jane@x.com" not in out[0]["note"]       # e-mails redacted from free text
    assert rows[0]["customer_name"] == "Jane Doe"   # the input is not modified


def test_tagged_personal_reads_profile_shape_tags():
    shape = [{"name": "PATIENT_KEY", "tags": ["identifier", "personal_data"]},
             {"name": "NDC", "tags": "identifier"}, {"name": "X", "tags": "pii"}, "bad"]
    assert tagged_personal(shape) == {"patient_key", "x"}
    assert is_masked("PATIENT_KEY", {"patient_key"})
    assert not is_masked("NDC", set())


def test_rca_file_query_refuses_writes_before_touching_the_platform():
    out = asyncio.run(query_databricks_data_file.ainvoke(
        {"file_path": "/Volumes/c/s/v/f.csv", "sql_query": "DROP TABLE c.s.t"}))
    assert out.startswith("Error:") and "read-only" in out


def test_rca_connector_follows_the_bound_incident():
    token = scope._WORKSPACE.set(SimpleNamespace(name="B", platform="databricks", host="https://adb-b.net",
                                                 connection_config=None))
    try:
        assert scope.rca_connector()._host == "https://adb-b.net"
    finally:
        scope._WORKSPACE.reset(token)
    token = scope._WORKSPACE.set(SimpleNamespace(name="Snow", platform="snowflake", host="", connection_config={}))
    try:
        with pytest.raises(RuntimeError, match="Databricks connections only"):
            scope.rca_connector()
    finally:
        scope._WORKSPACE.reset(token)


class _Connector:
    async def execute_query(self, sql):
        return {"manifest": {"schema": {"columns": [{"name": n} for n in ("CUSTOMER_NAME", "PRESCRIBER_KEY", "UNITS")]}},
                "result": {"data_array": [["Jane Doe", "P-991", "4"], ["John Roe", "P-992", "7"]]}}


class _Structured:
    def __init__(self, seen):
        self.seen = seen

    async def ainvoke(self, messages):
        self.seen.append(messages[-1][1])
        return {"parsed": None, "raw": None}


class _Llm:
    def __init__(self, seen):
        self.seen = seen

    def with_structured_output(self, *_a, **_k):
        return _Structured(self.seen)


def test_column_descriptions_never_send_personal_values_to_the_model(monkeypatch):
    seen = []
    monkeypatch.setattr("kairos_kb.enrichment.agent._build_llm", lambda: _Llm(seen))

    async def connector(_name):
        return _Connector()

    monkeypatch.setattr(pipeline, "_platform_connector", connector)
    fields = {"summary": "s", "shape": {"grain": "g", "columns": [
        {"name": "CUSTOMER_NAME", "type": "string", "undocumented": True},
        {"name": "PRESCRIBER_KEY", "type": "string", "undocumented": True, "tags": ["personal_data"]},
        {"name": "UNITS", "type": "int", "undocumented": True},
    ]}}
    context_doc = {"entity_id": "table:WS:db.s.t", "full_name": "db.s.t", "columns": []}
    asyncio.run(pipeline.describe_missing_columns(fields, context_doc))
    prompt = "\n".join(seen)
    assert "Jane Doe" not in prompt and "John Roe" not in prompt   # personal by name
    assert "P-991" not in prompt                                    # personal by tag
    assert "samples: ['4', '7']" in prompt                          # other columns keep their samples
