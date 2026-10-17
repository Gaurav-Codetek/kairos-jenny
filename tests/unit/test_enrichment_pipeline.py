"""The staged enrichment pipeline: vocabulary, facts, templates, verification."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from kairos_kb.enrichment import pipeline


def _platform(make):
    """Stand in for the per-workspace connector lookup (no database in unit tests)."""
    async def get(_workspace_name):
        return make()
    return get
from kairos_kb.enrichment.agent import KEEP_FULL_TOOL_RESULTS, compact_history
from kairos_kb.enrichment.pipeline import (
    canonical_relation,
    facts_summary,
    normalise_shape,
    role_brief,
    verify_profile,
)

# ── vocabulary: the 33 verbs the last run invented, and where each goes ──

NOT_RECORDED = [
    # containment — the sync already knows it (134 of 174 links last run)
    "CONTAINS_TABLE", "CONTAINS_SCHEMA", "IN_SCHEMA", "BELONGS_TO_CATALOG", "IN_CATALOG", "CONTAINED_IN",
    "PART_OF_CATALOG", "BELONGS_TO_SCHEMA", "PART_OF_SCHEMA", "CONTAINED_IN_SCHEMA", "CONTAINED_BY",
    "MEMBER_OF", "MEMBER_OF_SCHEMA", "PART_OF_JOB",
    # name-based guesses
    "NAME_MATCH_POSSIBLE_LINEAGE", "NAMED_SIBLING_TABLE", "POTENTIALLY_RELATED_SIBLING", "POSSIBLE_SIBLING",
    "RELATED_BY_NAME", "POSSIBLE_SOURCE", "POSSIBLY_PRODUCED_BY_JOB", "POSSIBLE_SOURCE_TABLE",
    "NAME_BASED_POTENTIAL_DOWNSTREAM", "POTENTIAL_EQUIVALENT_OR_SOURCE", "POSSIBLE_COPY_IN_RAW_SCHEMA",
    "NAME_BASED_POTENTIAL_NEXT_STAGE", "LIKELY_VARIANT_OF", "SHARES_NOTEBOOK_WITH",
    # real but not data flow
    "LOGS_FOR_TABLE", "MENTIONS_IN_LOG", "RECORDS_LOAD_STATUS_FOR", "GATES_LAYER_FOR", "SERVES_JOB", "OWNED_BY",
    "USES_EXISTING_CLUSTER",
]


@pytest.mark.parametrize("verb", NOT_RECORDED)
def test_noise_verbs_are_not_recorded(verb):
    canonical, _, reason = canonical_relation(verb)
    assert canonical is None, f"{verb} should be declined, got {canonical}"
    assert reason


@pytest.mark.parametrize(
    "verb,canonical,flip",
    [
        ("READS_TABLE", "READS_TABLE", False),
        ("WRITES_TABLE", "WRITES_TABLE", False),
        ("READ_BY_TASK", "READS_TABLE", True),          # passive: stored the other way round
        ("WRITTEN_BY_TASK", "WRITES_TABLE", True),
        ("CREATED_BY_JOB", "WRITES_TABLE", True),
        ("WRITTEN_BY_NOTEBOOK", "WRITES_TABLE", True),
        ("CREATED_BY_TASK", "WRITES_TABLE", True),
        ("READS_VOLUME_FILE", "READS_FILE", False),
        ("READS_VOLUME_DIRECTORY", "READS_FILE", False),
        ("DERIVES_FROM", "FEEDS", True),                # A derives from B = B feeds A
        ("DERIVED_FROM_NOTEBOOK", "FEEDS", True),
        ("FEEDS_TABLE", "FEEDS", False),
        ("TRANSFORMS_TO", "FEEDS", False),
        ("EXECUTES_NOTEBOOK", "RUNS_NOTEBOOK", False),
        ("RUNS_NOTEBOOK", "RUNS_NOTEBOOK", False),
        ("DEPENDS_ON_TASK", "DEPENDS_ON", False),
        ("BLOCKS_TASK", "DEPENDS_ON", True),
        ("TRIGGERS_TASK", "TRIGGERS", False),
        ("CALLS_EXTERNAL_API", "USES_EXTERNAL", False),
        ("STORED_AT_VOLUME", "STORED_AT", False),
        ("reads table", "READS_TABLE", False),           # lower case, spaces
    ],
)
def test_flow_verbs_map_onto_the_vocabulary(verb, canonical, flip):
    assert canonical_relation(verb)[:2] == (canonical, flip)


def test_unknown_verbs_are_declined_with_the_vocabulary_listed():
    canonical, _, reason = canonical_relation("PUBLISHES_DASHBOARD_TILE")
    assert canonical is None and "READS_TABLE" in reason


# ── Stage 0: facts from Delta history ──


class _Connector:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail = rows or [], fail

    async def execute_query(self, sql):
        if self.fail:
            raise RuntimeError("DESCRIBE HISTORY is only supported for Delta tables")
        return {"sql": sql}

    @staticmethod
    def _rows_from_statement_result(result):
        return _Connector.last_rows


async def test_history_names_the_writing_job_and_ignores_maintenance(monkeypatch):
    rows = [
        {"operation": "CREATE OR REPLACE TABLE AS SELECT", "timestamp": "2026-09-25T10:00:00Z",
         "job": json.dumps({"jobId": "572339974626818", "jobName": "ics_sales_ingestion"})},
        {"operation": "COMPUTE STATS", "timestamp": "2026-09-26T10:00:00Z",
         "job": json.dumps({"jobId": "999", "jobName": "Predictive Optimization Job-abc"})},
        {"operation": "CREATE TABLE AS SELECT", "timestamp": "2026-06-01T10:00:00Z",
         "notebook": json.dumps({"notebookId": "42"}), "userName": "someone@x.com"},
    ]
    _Connector.last_rows = rows
    monkeypatch.setattr(pipeline, "DatabricksConnector", lambda: _Connector(rows))
    monkeypatch.setattr(pipeline, "_platform_connector", _platform(pipeline.DatabricksConnector))
    monkeypatch.setattr(pipeline.DatabricksConnector, "_rows_from_statement_result", staticmethod(lambda r: rows), raising=False)
    facts = await pipeline._history_facts("cat.bronze.raw_ics_867", "ICS Sales Warehouse")
    writers = {w["writer"]: w for w in facts["writers"]}
    assert "ics_sales_ingestion" in writers
    assert writers["ics_sales_ingestion"]["entity_id"] == "job:ICS Sales Warehouse:572339974626818"
    assert not any("Predictive Optimization" in w for w in writers)  # maintenance is not a writer
    session = next(w for w in facts["writers"] if w["kind"] == "notebook_session")
    assert session["linkable"] is False and "someone@x.com" in session["writer"]  # a fact, not an entity
    assert writers["ics_sales_ingestion"]["linkable"] is True
    assert facts["last_write"] == "2026-09-25T10:00:00Z"


async def test_tables_without_history_say_so(monkeypatch):
    monkeypatch.setattr(pipeline, "DatabricksConnector", lambda: _Connector(fail=True))
    monkeypatch.setattr(pipeline, "_platform_connector", _platform(pipeline.DatabricksConnector))
    facts = await pipeline._history_facts("cat.sch.a_view", "ws")
    assert facts["history_available"] is False and "Delta" in facts["history_error"]


def test_facts_summary_reads_as_one_line():
    line = facts_summary({"row_count": 110000, "column_count": 5, "writers": [{"writer": "nexora poc pipeline"}],
                          "known_relationships": [{}, {}]})
    assert line == "110,000 rows · 5 columns · written by nexora poc pipeline · 2 known links"


# ── Stage 1: templates ──


def test_a_scratch_table_gets_a_light_pass_and_no_grain_requirement():
    brief, light = role_brief("table", {"role": "SCRATCH_TEST", "layer": "OTHER", "role_confidence": 0.9}, {})
    assert light and "LIGHT PASS" in brief and "grain_key to save_profile" not in brief


def test_an_empty_table_gets_a_light_pass_whatever_its_role():
    _, light = role_brief("table", {"role": "FACT_EVENT", "layer": "BRONZE_STAGING"}, {"is_empty": True})
    assert light


def test_a_fact_template_requires_a_grain_key_and_every_column():
    brief, light = role_brief("table", {"role": "FACT_EVENT", "layer": "SILVER_CURATED", "role_confidence": 0.8}, {})
    assert not light
    assert "grain_key to save_profile" in brief and "EVERY column" in brief


def test_non_tables_get_facts_and_known_links_only():
    brief, light = role_brief("task", None, {"known_relationships": [{"source": "a", "relation": "READS_TABLE", "target": "b"}]})
    assert "KNOWN RELATIONSHIPS (1)" in brief and "TEMPLATE" not in brief and not light


# ── Stage 3: verification ──

CONTEXT = {
    "entity_id": "table:ws:cat.bronze.promo_activity", "kind": "table", "full_name": "cat.bronze.promo_activity",
    "columns": [{"name": n, "data_type": "string"} for n in ("HCO_ID", "ACTIVITY_DATE", "TOTAL_CALLS")],
}


def test_grouped_column_entries_are_split_and_text_shape_is_parsed():
    shape, notes = normalise_shape("grain: one row per call\ncolumns:\n  - name: A, B\n    meaning: ids\n")
    assert [c["name"] for c in shape["columns"]] == ["A", "B"]
    assert any("parsed" in n for n in notes) and any("split" in n for n in notes)


def _grain_result(monkeypatch, n, k):
    rows = [{"n": str(n), "k": str(k)}]

    class C:
        async def execute_query(self, sql):
            C.sql = sql
            return {}

        _rows_from_statement_result = staticmethod(lambda r: rows)

    monkeypatch.setattr(pipeline, "DatabricksConnector", C)

    monkeypatch.setattr(pipeline, "_platform_connector", _platform(pipeline.DatabricksConnector))
    return C


async def test_a_false_grain_claim_is_caught(monkeypatch):
    # The promo_activity case: "one row per HCO per ACTIVITY_DATE" did not hold.
    C = _grain_result(monkeypatch, 110000, 90431)
    fields = {"summary": "s", "grain_key": "HCO_ID, ACTIVITY_DATE",
              "shape": {"columns": [{"name": "HCO_ID"}, {"name": "ACTIVITY_DATE"}, {"name": "TOTAL_CALLS"}]}}
    fields, v = await verify_profile(fields, CONTEXT, {"row_count": 110000}, {"role": "AGGREGATE_MART"})
    grain = next(c for c in v["checks"] if c["check"] == "grain")
    assert grain["result"] == "fails" and "19,569 duplicate rows out of 110,000" in grain["detail"]
    assert "COUNT(DISTINCT struct(`HCO_ID`, `ACTIVITY_DATE`))" in C.sql
    assert v["passed"] is False
    assert any("Grain claim does not hold" in q for q in fields["open_questions"])


async def test_a_true_grain_claim_holds(monkeypatch):
    _grain_result(monkeypatch, 8000, 8000)
    _, v = await verify_profile({"summary": "s", "grain_key": "HCO_ID", "shape": {"columns": []}}, CONTEXT, {}, {"role": "DIMENSION_MASTER"})
    assert next(c for c in v["checks"] if c["check"] == "grain")["result"] == "holds"


async def test_a_grain_key_naming_a_missing_column_fails_without_querying(monkeypatch):
    C = _grain_result(monkeypatch, 1, 1)
    C.sql = None
    _, v = await verify_profile({"summary": "s", "grain_key": "NOPE", "shape": {}}, CONTEXT, {}, {"role": "FACT_EVENT"})
    assert next(c for c in v["checks"] if c["check"] == "grain")["result"] == "fails" and C.sql is None


async def test_a_required_grain_key_that_is_missing_is_reported():
    _, v = await verify_profile({"summary": "s", "shape": {}}, CONTEXT, {}, {"role": "FACT_EVENT"})
    assert next(c for c in v["checks"] if c["check"] == "grain")["result"] == "missing"


async def test_every_column_ends_up_in_the_profile():
    fields = {"summary": "s", "shape": {"columns": [{"name": "HCO_ID", "meaning": "org id"}]}}
    fields, v = await verify_profile(fields, CONTEXT, {}, {"role": "OTHER"})
    names = [c["name"] for c in fields["shape"]["columns"]]
    assert names == ["HCO_ID", "ACTIVITY_DATE", "TOTAL_CALLS"]
    assert fields["shape"]["columns"][1]["undocumented"] is True
    assert next(c for c in v["checks"] if c["check"] == "column_coverage")["detail"].startswith("1 of 3")


async def test_writer_unknown_is_corrected_from_delta_history():
    # The raw_ics_867 case: the prose said no writer was found.
    fields = {"summary": "s", "shape": {}, "creation": "created_by: unknown (no job or notebook discovered in workspace)"}
    facts = {"writers": [{"writer": "ics_sales_ingestion"}]}
    fields, v = await verify_profile(fields, CONTEXT, facts, {"role": "RAW_FILE_INGEST"})
    assert fields["creation"]["writers_from_delta_history"] == ["ics_sales_ingestion"]
    check = next(c for c in v["checks"] if c["check"] == "writer_consistency")
    assert check["result"] == "corrected"


# ── Stage 2: trimming what the agent re-reads ──


def test_old_tool_results_are_trimmed_recent_ones_kept():
    big = "x" * 20000
    msgs = [HumanMessage(content="profile this")]
    for i in range(KEEP_FULL_TOOL_RESULTS + 2):
        msgs.append(AIMessage(content="", tool_calls=[{"name": "read", "args": {}, "id": str(i)}]))
        msgs.append(ToolMessage(content=big, tool_call_id=str(i)))
    compact_history(msgs)
    tools = [m for m in msgs if isinstance(m, ToolMessage)]
    assert all(t.content.startswith("[trimmed") for t in tools[:2])
    assert all(t.content == big for t in tools[-KEEP_FULL_TOOL_RESULTS:])
    compact_history(msgs)  # idempotent
    assert tools[0].content.count("[trimmed") == 1
