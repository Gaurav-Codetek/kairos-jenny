"""Recording Agent A's trace as a general plan — references resolved in code."""

import json

import pytest

from kairos_kb.agent import plan_recorder
from kairos_kb.agent.jev_rca import _instance_literals
from kairos_kb.agent.plan_executor import validate_plan
from kairos_kb.agent.plan_recorder import _Leftover, record_plan

RID = "f824d1ef-a2db-40d9-9b7e-dc697d248c41"
NOTEBOOK = (
    'METADATA_FILE = "/Volumes/cat/meta/vol/config/ingestion_metadata.csv"\n'
    'SCHEMA_FILE   = "/Volumes/cat/meta/vol/config/schema_mapping.csv"\n'
    "SOURCE_ORIGIN_FILTER = 'ics' #None\n"
    + "# padding so the notebook reads as long text\n" * 20
)


@pytest.fixture(autouse=True)
def describe_without_llm(monkeypatch):
    """The only LLM step in recording: naming leftover values. Deterministic here."""

    async def describe(pending):
        names = {
            "/Volumes/cat/meta/vol/config/ingestion_metadata.csv": "metadata_file",
            "/Volumes/cat/meta/vol/config/schema_mapping.csv": "schema_file",
            "ics": "source_origin_filter",
        }
        return {p["value"]: _Leftover(value=p["value"], field_name=names.get(p["value"], "value"),
                                      description=f"the {names.get(p['value'], 'value')}") for p in pending}

    monkeypatch.setattr(plan_recorder, "_describe_leftovers", describe)


def ics_trace(trace, file_columns=("A", "B", "SOLD_QTY"), mapping=("A", "B", "SALES_QTY"),
              error="ValueError: Column Order Mismatch!"):
    """Agent A's investigation of the ICS incident, as it actually ran."""
    run = {"run_id": RID, "failed_tasks": [
        {"task_key": "raw_ingestion", "taskrun_entity_id": "taskrun:ICS:216012467763449:raw_ingestion",
         "source_native_id": "117576678163792"}]}
    ctx = {"task_entity_id": "task:ICS:572339974626818:raw_ingestion",
           "notebook_path": "/Workspace/Users/someone/ics_ingestion_notebook"}
    meta_sql = ("SELECT * FROM read_files('/Volumes/cat/meta/vol/config/ingestion_metadata.csv', "
                "format => 'csv', header => true) WHERE Subject_Area = 'ics'")
    map_sql = ("SELECT source_file_column FROM read_files('/Volumes/cat/meta/vol/config/schema_mapping.csv', "
               "format => 'csv', header => true) WHERE Source_Origin = 'ics'")
    return (
        trace.call("get_failed_run_details", {"run_id": RID}, run)
        .call("get_task_context", {"entity_id": run["failed_tasks"][0]["taskrun_entity_id"]}, ctx)
        .call("get_task_error_trace", {"source_native_id": "117576678163792"}, {"error": error, "error_trace": "..."})
        # The notebook read the way Agent A does it: a paginated text chunk.
        .call("read_databricks_text_file", {"file_path": ctx["notebook_path"], "offset": 0, "length": 5000},
              "--- File Preview (Chars 0 to 900 of 900) ---\n" + NOTEBOOK)
        .call("run_select_query", {"sql": meta_sql}, {"rows": [
            {"Subject_Area": "ics", "File_Path": "/Volumes/cat/meta/vol/uploads/", "File_Name": "RAW_867.csv"}],
            "row_count": 1})
        .call("run_select_query", {"sql": map_sql},
              {"rows": [{"source_file_column": c} for c in mapping], "row_count": len(mapping)})
        .call("get_file_columns", {"file_path": "/Volumes/cat/meta/vol/uploads/RAW_867.csv", "format": "csv"},
              {"columns": list(file_columns), "count": len(file_columns)})
    )


def by_id(nodes):
    return {n["id"]: n for n in nodes}


async def test_records_a_plan_with_every_value_traced(trace):
    nodes, reason = await record_plan(ics_trace(trace).messages, RID, "COLUMN_RENAME")
    assert reason == "recorded"
    n = by_id(nodes)

    assert n["get_failed_run_details_0"]["args"] == {"run_id": "$input.run_id"}
    assert n["get_task_context_1"]["args"]["entity_id"] == "$get_failed_run_details_0.failed_tasks[0].taskrun_entity_id"
    assert n["get_task_error_trace_2"]["args"]["source_native_id"] == \
        "$get_failed_run_details_0.failed_tasks[0].source_native_id"

    # The paginated text reader is normalised to reading the whole file.
    assert n["read_code_file_3"] == {"id": "read_code_file_3", "type": "tool", "name": "read_code_file",
                                     "args": {"file_path": "$get_task_context_1.notebook_path"}}
    assert n["extract_3"]["args"]["from"] == "$read_code_file_3.text"
    assert set(n["extract_3"]["args"]["fields"]) == {"metadata_file", "schema_file", "source_origin_filter"}

    # Paths and the short filter value come from the notebook, not literals.
    assert "{{extract_3.metadata_file}}" in n["run_select_query_4"]["args"]["sql"]
    assert "'{{extract_3.source_origin_filter}}'" in n["run_select_query_4"]["args"]["sql"]
    # A later query takes the same filter from the earlier query's result.
    assert "'{{run_select_query_4.rows[0].Subject_Area}}'" in n["run_select_query_5"]["args"]["sql"]
    # A path assembled from two fields of an earlier result.
    assert n["get_file_columns_6"]["args"]["file_path"] == \
        "{{run_select_query_4.rows[0].File_Path}}{{run_select_query_4.rows[0].File_Name}}"


async def test_recorded_plan_has_no_instance_values_left(trace):
    t = ics_trace(trace)
    nodes, _ = await record_plan(t.messages, RID, "COLUMN_RENAME")
    forbidden = _instance_literals(RID, {"job_name": "ics_sales_ingestion", "task_keys": ["raw_ingestion"]}, t.messages)
    assert validate_plan(nodes, forbidden) == []
    text = json.dumps([n["args"] for n in nodes if n["type"] == "tool"])
    assert "/Volumes/" not in text and "'ics'" not in text and "117576678163792" not in text


async def test_code_appends_the_fixed_tail(trace):
    nodes, _ = await record_plan(ics_trace(trace).messages, RID, "COLUMN_RENAME")
    assert [n["id"] for n in nodes[-4:]] == ["diff", "verify_class", "verify_counts", "report"]
    diff = by_id(nodes)["diff"]["args"]
    # The incoming file is the actual side; the mapping rows are expected.
    assert diff == {"expected": "$run_select_query_5", "actual": "$get_file_columns_6",
                    "expected_field": "source_file_column"}
    assert by_id(nodes)["verify_counts"]["args"]["error"] == "$get_task_error_trace_2.error"


async def test_anchor_must_explain_the_class(trace):
    # The lists show a rename with nothing moved; an order swap must find no anchor.
    nodes, reason = await record_plan(ics_trace(trace).messages, RID, "COLUMN_ORDER_SWAP")
    assert nodes is None and reason.startswith("no pair")


async def test_anchor_must_agree_with_the_error_counts(trace):
    t = ics_trace(trace, file_columns=("A", "B", "SALES_QTY", "NEW"), error="Column Count Mismatch! Expected 78, got 79")
    nodes, reason = await record_plan(t.messages, RID, "EXTRA_COLUMN")
    assert nodes is None and reason.startswith("no pair")


async def test_no_structured_lists_means_nothing_to_record(trace):
    trace.call("get_failed_run_details", {"run_id": RID}, {"failed_tasks": []})
    trace.call("query_databricks_data_file", {"file_path": "/Volumes/x/y/z/f.csv"}, "--- Query Results ---\n[]")
    nodes, reason = await record_plan(trace.messages, RID, "EXTRA_COLUMN")
    assert nodes is None and reason.startswith("no pair")


async def test_failed_calls_are_never_used_as_sources(trace):
    trace.call("list_databricks_directory", {"path": "/Volumes/cat/meta/vol/uploads/"},
               "Error listing /Volumes/cat/meta/vol/uploads/RAW_867.csv: 404")
    t = ics_trace(trace)
    nodes, _ = await record_plan(t.messages, RID, "COLUMN_RENAME")
    assert not any(n["name"] == "list_databricks_directory" for n in nodes)
