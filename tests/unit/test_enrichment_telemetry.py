"""Live enrichment telemetry: activity lines, and telemetry never breaking a run."""

import uuid

import pytest

from kairos_kb.enrichment.agent import _telemetry, describe_tool_call
from kairos_kb.enrichment.tools import ToolContext


@pytest.mark.parametrize(
    "name,args,expected",
    [
        ("read_databricks_file", {"path": "/Workspace/Users/x/nb"}, "Reading /Workspace/Users/x/nb"),
        ("list_databricks_directory", {"path": "/Volumes/c/s/v"}, "Listing /Volumes/c/s/v"),
        ("query_data_file", {"path": "/Volumes/c/s/v/f.csv"}, "Sampling data in /Volumes/c/s/v/f.csv"),
        ("find_entity", {"keyword": "867"}, "Searching the warehouse for '867'"),
        ("link_entities", {"relation_type": "READS_TABLE", "target": "cat.sch.t"}, "Linking READS_TABLE → cat.sch.t"),
        ("save_profile", {}, "Writing the profile"),
        ("something_new", {}, "Calling something_new"),
    ],
)
def test_every_tool_call_reads_as_one_plain_line(name, args, expected):
    assert describe_tool_call(name, args) == expected


def test_long_paths_keep_their_informative_end():
    line = describe_tool_call("read_databricks_file", {"path": "/Workspace/" + "deep/" * 40 + "ics_ingestion_notebook"})
    assert line.endswith("ics_ingestion_notebook") and len(line) < 110


def _ctx(telemetry):
    async def emit(*_a, **_k):
        return None

    return ToolContext(workspace_id=uuid.uuid4(), workspace_name="ws", run_id=uuid.uuid4(),
                       entity_id="table:ws:a.b.c", kind="table", emit=emit, telemetry=telemetry)


async def test_telemetry_is_forwarded():
    seen = []

    async def record(**kwargs):
        seen.append(kwargs)

    await _telemetry(_ctx(record), input_tokens=120, output_tokens=30, llm_calls=1)
    assert seen == [{"input_tokens": 120, "output_tokens": 30, "llm_calls": 1}]


async def test_a_failing_telemetry_write_never_breaks_profiling():
    async def broken(**_kwargs):
        raise RuntimeError("database unavailable")

    await _telemetry(_ctx(broken), activity="Thinking")  # must not raise


async def test_no_telemetry_configured_is_fine():
    await _telemetry(_ctx(None), activity="Thinking")
