"""Agent B: references, static validation, and running a plan as a graph."""

import pytest

from kairos_kb.agent import plan_executor
from kairos_kb.agent.plan_executor import _resolve, _without_agent_hints, run_plan, validate_plan
from tests.conftest import FakeStructuredLLM

RESULTS = {
    "input": {"run_id": "r-1", "failure_class": "EXTRA_COLUMN"},
    "run": {"failed_tasks": [{"source_native_id": "123", "task_key": "raw"}]},
    "meta": {"rows": [{"File_Path": "/Volumes/c/s/v/up/", "File_Name": "o'brien.csv"}]},
}


# ── references ───────────────────────────────────────────────────────


def test_whole_reference_returns_the_value_itself():
    assert _resolve("$run.failed_tasks", RESULTS) == [{"source_native_id": "123", "task_key": "raw"}]
    assert _resolve("$run.failed_tasks[0].source_native_id", RESULTS) == "123"


def test_template_interpolates_and_escapes_quotes_for_sql():
    sql = "SELECT * FROM read_files('{{meta.rows[0].File_Path}}{{meta.rows[0].File_Name}}')"
    assert _resolve(sql, RESULTS) == "SELECT * FROM read_files('/Volumes/c/s/v/up/o''brien.csv')"


def test_nested_args_and_plain_values():
    args = {"a": ["$input.run_id", 3], "b": {"c": "no refs here"}, "d": None}
    assert _resolve(args, RESULTS) == {"a": ["r-1", 3], "b": {"c": "no refs here"}, "d": None}


@pytest.mark.parametrize("ref", ["$missing.x", "$run.nope", "$run.failed_tasks[5].task_key", "{{meta.rows[0].Nope}}"])
def test_unresolvable_references_raise(ref):
    with pytest.raises(KeyError):
        _resolve(ref, RESULTS)


# ── validation ───────────────────────────────────────────────────────


def _good_plan():
    return [
        {"id": "run", "type": "tool", "name": "get_failed_run_details", "args": {"run_id": "$input.run_id"}},
        {"id": "cols", "type": "tool", "name": "get_file_columns", "args": {"file_path": "{{run.path}}"}},
        {"id": "exp", "type": "tool", "name": "run_select_query", "args": {"sql": "SELECT c FROM read_files('{{run.map}}')"}},
        {"id": "diff", "type": "compute", "name": "column_diff", "args": {"expected": "$exp", "actual": "$cols", "expected_field": "c"}},
        {"id": "check", "type": "verify", "name": "diff_explains_class", "args": {"diff": "$diff", "failure_class": "$input.failure_class"}},
        {"id": "report", "type": "report", "name": "report", "args": {"facts": {"diff": "$diff"}}},
    ]


def test_a_well_formed_plan_validates():
    assert validate_plan(_good_plan()) == []


def test_hardcoded_paths_are_rejected():
    plan = _good_plan()
    plan[1]["args"]["file_path"] = "/Volumes/nexora/metadata/vol/file.csv"
    assert any("hardcoded path" in p for p in validate_plan(plan))


def test_instance_values_from_the_learning_run_are_rejected():
    plan = _good_plan()
    plan[2]["args"]["sql"] = "SELECT c FROM t WHERE job = 'ics_sales_ingestion'"
    assert any("hardcoded instance value" in p for p in validate_plan(plan, ["ics_sales_ingestion"]))


def test_extract_field_descriptions_are_not_checked_as_values():
    # Regression: descriptions are instructions to the extractor, not values.
    plan = _good_plan()
    plan.insert(1, {"id": "ex", "type": "extract", "name": "extract", "args": {
        "from": "$run", "fields": {"path": "the path, e.g. /Volumes/<catalog>/<schema>/<volume>/file.csv"}}})
    assert validate_plan(plan) == []


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda p: p[1].update(name="no_such_tool"), "unknown tool"),
        (lambda p: p[3].update(name="no_such_op"), "unknown compute op"),
        (lambda p: p[3]["args"].update(expected="$later"), "before it exists"),
        (lambda p: p[1].update(id="run"), "unique"),
        (lambda p: p[1].update(id="Bad-Id"), "snake_case"),
        (lambda p: p.append(p.pop(0)), "last node must be a report"),
        (lambda p: p.pop(4), "at least one verify"),
        (lambda p: p.pop(3), "at least one compute"),
    ],
)
def test_malformed_plans_are_rejected(mutate, expected):
    plan = _good_plan()
    mutate(plan)
    assert any(expected in p for p in validate_plan(plan)), validate_plan(plan)


def test_agent_hints_never_reach_report_facts():
    facts = {"run": {"next_step": "call get_task_context", "tasks": [{"next_step": "x", "k": 1}]}}
    assert _without_agent_hints(facts) == {"run": {"tasks": [{"k": 1}]}}


# ── running a plan (Agent B's graph) ─────────────────────────────────


def _install(fake_tools, file_columns=("a", "b", "c"), mapping=("a", "b")):
    fake_tools("get_failed_run_details", {"path": "/Volumes/c/s/v/f.csv", "map": "/Volumes/c/s/v/map.csv"})
    fake_tools("get_file_columns", {"columns": list(file_columns), "count": len(file_columns)})
    return fake_tools("run_select_query", {"rows": [{"c": c} for c in mapping], "row_count": len(mapping)})


async def test_plan_runs_to_a_report(fake_tools, stub_report):
    query = _install(fake_tools)
    result = await run_plan(_good_plan(), "r-1", "EXTRA_COLUMN")
    assert result["success"], result["failure"]
    assert result["report"].startswith("REPORT EXTRA_COLUMN")
    assert "FINAL_CLASSIFICATION: EXTRA_COLUMN" in result["report"]
    assert result["tool_calls"] == 3
    # The template was filled from the earlier node's output.
    assert query.calls[0]["sql"] == "SELECT c FROM read_files('/Volumes/c/s/v/map.csv')"


async def test_failed_verification_stops_the_graph(fake_tools, stub_report):
    _install(fake_tools, file_columns=("a", "b"))  # identical: nothing explains EXTRA_COLUMN
    result = await run_plan(_good_plan(), "r-1", "EXTRA_COLUMN")
    assert not result["success"]
    assert result["failure"].startswith("check: verify diff_explains_class")
    assert [s["id"] for s in result["steps"]][-1] == "check"  # report never ran


async def test_tool_error_result_fails_the_node(fake_tools, stub_report):
    _install(fake_tools)
    fake_tools("get_file_columns", {"error": "Could not read columns"})
    result = await run_plan(_good_plan(), "r-1", "EXTRA_COLUMN")
    assert not result["success"] and result["failure"].startswith("cols: tool get_file_columns")


async def test_an_error_field_next_to_data_is_data_not_failure(fake_tools, stub_report):
    # Regression: get_task_error_trace returns the task's error text under "error".
    _install(fake_tools)
    fake_tools("get_failed_run_details", {"error": "ValueError: boom", "error_trace": "...",
                                          "path": "/Volumes/c/s/v/f.csv", "map": "/Volumes/c/s/v/map.csv"})
    assert (await run_plan(_good_plan(), "r-1", "EXTRA_COLUMN"))["success"]


async def test_empty_column_source_fails_immediately(fake_tools, stub_report):
    _install(fake_tools, mapping=())
    result = await run_plan(_good_plan(), "r-1", "EXTRA_COLUMN")
    assert not result["success"] and "returned nothing" in result["failure"]


async def test_invalid_plan_never_runs(fake_tools, stub_report):
    tool = _install(fake_tools)
    plan = _good_plan()
    plan[1]["args"]["file_path"] = "/Volumes/hard/coded/path.csv"
    result = await run_plan(plan, "r-1", "EXTRA_COLUMN")
    assert not result["success"] and result["failure"].startswith("invalid plan")
    assert tool.calls == []


# ── extract nodes ────────────────────────────────────────────────────


def _extract_plan():
    return [
        {"id": "code", "type": "tool", "name": "read_code_file", "args": {"file_path": "$input.run_id"}},
        {"id": "ex", "type": "extract", "name": "extract", "args": {"from": "$code.text", "fields": {"schema_file": "the schema file"}}},
        {"id": "cols", "type": "tool", "name": "get_file_columns", "args": {"file_path": "{{ex.schema_file}}"}},
        {"id": "diff", "type": "compute", "name": "column_diff", "args": {"expected": ["a"], "actual": "$cols"}},
        {"id": "check", "type": "verify", "name": "diff_explains_class", "args": {"diff": "$diff", "failure_class": "$input.failure_class"}},
        {"id": "report", "type": "report", "name": "report", "args": {"facts": {}}},
    ]


async def test_extract_strips_quotes_the_model_copies(fake_tools, stub_report, monkeypatch):
    # Regression: the model returned the path with its surrounding quotes.
    fake_tools("read_code_file", {"text": 'SCHEMA_FILE = "/Volumes/c/s/v/map.csv"\n'})
    cols = fake_tools("get_file_columns", {"columns": ["a", "b"], "count": 2})
    monkeypatch.setattr(plan_executor, "llm", FakeStructuredLLM({"schema_file": '"/Volumes/c/s/v/map.csv"'}))
    result = await run_plan(_extract_plan(), "r-1", "EXTRA_COLUMN")
    assert result["success"], result["failure"]
    assert cols.calls[0]["file_path"] == "/Volumes/c/s/v/map.csv"


async def test_extract_rejects_values_not_in_the_source(fake_tools, stub_report, monkeypatch):
    fake_tools("read_code_file", {"text": 'SCHEMA_FILE = "/Volumes/c/s/v/map.csv"\n'})
    fake_tools("get_file_columns", {"columns": ["a", "b"], "count": 2})
    monkeypatch.setattr(plan_executor, "llm", FakeStructuredLLM({"schema_file": "/Volumes/invented/by/model.csv"}))
    result = await run_plan(_extract_plan(), "r-1", "EXTRA_COLUMN")
    assert not result["success"] and "does not appear verbatim" in result["failure"]
