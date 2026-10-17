"""Deterministic parts of the Jev RCA path: evidence shaping, guards, parsing."""

import pytest
from langchain_core.messages import AIMessage

from kairos_kb.agent.jev_rca import _FINAL, _instance_literals, compare_columns_in_error, is_transient

ORDER_MISMATCH = (
    "ValueError: Column Order Mismatch!\n"
    "  Expected: ['transaction_qualifier', 'sales_qty', 'remsite_id']\n"
    "  Actual  : ['transaction_qualifier', 'sold_qty', 'remsite_id']"
)


def test_rename_hidden_behind_an_order_mismatch_message():
    # Regression: the notebook calls any same-length difference an "order
    # mismatch"; the computed comparison must say what really happened.
    c = compare_columns_in_error(ORDER_MISMATCH)
    assert c["column_count"] == "same number of columns in expected and actual"
    assert c["names_replaced_in_place"] == ["sales_qty → sold_qty (position 2)"]
    assert c["same_names_in_different_order"] == "no"
    assert c["columns_that_changed_position"] == "none"
    assert c["names_only_in_actual"] == "none"


def test_extra_column_in_printed_lists():
    c = compare_columns_in_error("Expected: ['a', 'b']\nActual: ['a', 'b', 'c']")
    assert c["column_count"] == "actual has 1 more column(s) than expected"
    assert c["names_only_in_actual"] == ["c"]


def test_true_order_swap_in_printed_lists():
    c = compare_columns_in_error("Expected: ['a', 'b', 'c']\nActual: ['b', 'a', 'c']")
    assert c["same_names_in_different_order"] == "yes"
    assert set(c["columns_that_changed_position"]) == {"a", "b"}


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "ValueError: Column Count Mismatch! Expected 78, got 79",  # counts, no lists
        "Expected: ['a', 'b']",                                     # only one list
        "Expected: [a, b]\nActual: [a, c]",                         # not literal lists
        "Expected: []\nActual: []",
    ],
)
def test_no_comparison_without_two_lists(text):
    assert compare_columns_in_error(text) is None


def test_instance_literals_catch_what_a_general_plan_must_not_hardcode():
    messages = [AIMessage(content="", tool_calls=[
        {"name": "get_task_error_trace", "args": {"source_native_id": "117576678163792"}, "id": "1"},
        {"name": "get_file_columns", "args": {"file_path": "/Volumes/c/s/v/f.csv", "format": "csv"}, "id": "2"},
        {"name": "get_table_columns", "args": {"table": "cat.sch.tbl_name"}, "id": "3"},
        {"name": "get_task_context", "args": {"entity_id": "taskrun:ws:1:raw"}, "id": "4"},
    ])]
    lits = _instance_literals("run-uuid-1234", {"job_name": "ics_sales_ingestion", "task_keys": ["raw_ingestion"]}, messages)
    for expected in ("run-uuid-1234", "ics_sales_ingestion", "raw_ingestion", "117576678163792",
                     "/Volumes/c/s/v/f.csv", "cat.sch.tbl_name", "taskrun:ws:1:raw"):
        assert expected in lits
    assert "csv" not in lits


@pytest.mark.parametrize(
    "failure,transient",
    [
        ("task_trace: tool get_task_error_trace: [Databricks] Connection error: [Errno -3] Temporary failure in name resolution", True),
        ("Request timed out", True),
        ("HTTP 429 Too Many Requests", True),
        ("verify diff_explains_class: EXTRA_COLUMN is NOT shown by the diff", False),
        ("extract: 'schema_file' not found in the source", False),
        (None, False),
    ],
)
def test_transient_failures_do_not_count_against_a_variant(failure, transient):
    assert is_transient(failure) is transient


@pytest.mark.parametrize(
    "report,label",
    [
        ("...\n### 🏷️ Schema Classification\nFINAL_CLASSIFICATION: EXTRA_COLUMN", "EXTRA_COLUMN"),
        ("FINAL_CLASSIFICATION: **COLUMN_RENAME**", "COLUMN_RENAME"),
        ("FINAL_CLASSIFICATION:   NOT_SCHEMA_RELATED\nPLAYBOOK_OUTCOME: CONFIRMED", "NOT_SCHEMA_RELATED"),
    ],
)
def test_final_classification_is_parsed_from_the_report(report, label):
    assert _FINAL.search(report).group(1) == label
