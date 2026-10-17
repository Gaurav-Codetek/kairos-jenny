"""The exact error behind a failed task run, parsed from Databricks run output."""

from kairos_kb.context.documents import failure_line
from kairos_kb.ingestion.run_errors import (
    error_detail,
    error_line,
    locate,
    notebook_cells,
    parse_traceback,
    redact,
    strip_ansi,
)

# Shaped like a real Databricks notebook traceback, colour codes and all.
TRACE = (
    "\x1b[0;31m---------------------------------------------------------------------------\x1b[0m\n"
    "\x1b[0;31mValueError\x1b[0m                                Traceback (most recent call last)\n"
    "File \x1b[0;32m<command-8959532166638294>, line 259\x1b[0m\n"
    "\x1b[1;32m    258\x1b[0m           f\"{metadata_row['Target_Schema']}\")\n"
    "\x1b[0;32m--> 259\x1b[0m     process_single_table(metadata_row, SCHEMA_FILE)\n"
    "\x1b[1;32m    260\x1b[0m     print(\"Ingestion complete.\")\n"
    "\n"
    "File \x1b[0;32m<command-8959532166638294>, line 6\x1b[0m, in \x1b[0;36mprocess_single_table\x1b[0;34m(metadata_row, schema_file)\x1b[0m\n"
    "\x1b[1;32m      5\x1b[0m     if actual != expected:\n"
    "\x1b[0;32m----> 6\x1b[0m         raise ValueError(f\"Column Order Mismatch! owner: ana@example.com\")\n"
    "\n"
    "\x1b[0;31mValueError\x1b[0m: Column Order Mismatch! owner: ana@example.com\n"
)

SOURCE = (
    "# Databricks notebook source\n"
    "import json\n"
    "\n"
    "def process_single_table(metadata_row, schema_file):\n"
    "    actual = read(schema_file)\n"
    "    if actual != expected:\n"
    "        raise ValueError(f\"Column Order Mismatch! owner: ana@example.com\")\n"
    "\n"
    "# COMMAND ----------\n"
    "\n"
    "for idx, metadata_row in enumerate(rows):\n"
    "    process_single_table(metadata_row, SCHEMA_FILE)\n"
)


def test_colour_codes_are_removed():
    assert strip_ansi("\x1b[0;31mValueError\x1b[0m: x") == "ValueError: x"
    assert strip_ansi(None) == ""


def test_frames_name_the_cell_line_function_and_code():
    frames = parse_traceback(TRACE)
    assert [(f["cell_ref"], f["line"], f["function"]) for f in frames] == [
        ("8959532166638294", 259, None),
        ("8959532166638294", 6, "process_single_table"),
    ]
    assert frames[0]["code"] == "process_single_table(metadata_row, SCHEMA_FILE)"
    assert frames[1]["code"].startswith("raise ValueError")


def test_the_newer_ipython_cell_spelling_is_understood():
    frames = parse_traceback("Cell In[12], line 4, in load\n----> 4 df = spark.table(t)\n")
    assert frames == [{"cell_ref": "12", "line": 4, "function": "load", "code": "df = spark.table(t)"}]


def test_the_error_line_comes_from_the_error_field_or_the_trace():
    assert error_line("KeyError: 'x'", "") == "KeyError: 'x'"
    assert error_line("", TRACE).startswith("ValueError: Column Order Mismatch!")
    assert error_line(None, "nothing useful") is None


def test_notebook_export_splits_into_cells_without_the_header():
    cells = notebook_cells(SOURCE)
    assert len(cells) == 2
    assert cells[0][0] == "import json"
    assert cells[1][1].strip() == "process_single_table(metadata_row, SCHEMA_FILE)"


def test_a_frame_is_located_in_its_cell_by_line_and_code():
    cells = notebook_cells(SOURCE)
    raising = {"line": 6, "code": 'raise ValueError(f"Column Order Mismatch! owner: ana@example.com")'}
    assert locate(raising, cells) == {"cell": 1, "cells": 2, "line_in_cell": 6}
    # The cell's line numbers moved (code edited since the run): found by code, marked approximate.
    moved = {"line": 40, "code": "process_single_table(metadata_row, SCHEMA_FILE)"}
    assert locate(moved, cells) == {"cell": 2, "cells": 2, "line_in_cell": 2, "approximate": True}
    assert locate({"line": 1, "code": "not in the notebook"}, cells) is None


def test_error_detail_is_structured_located_and_redacted():
    detail = error_detail({"error": "", "error_trace": TRACE}, SOURCE, "/Workspace/x/ingest")
    assert detail["error"] == "ValueError: Column Order Mismatch! owner: <email>"
    assert detail["location"] == {
        "cell": 1, "cells": 2, "line": 6, "function": "process_single_table",
        "code": 'raise ValueError(f"Column Order Mismatch! owner: <email>")',
        "cell_ref": "8959532166638294", "notebook": "/Workspace/x/ingest",
    }
    assert "\x1b[" not in detail["trace"] and "ana@example.com" not in detail["trace"]
    assert len(detail["frames"]) == 2


def test_a_long_trace_keeps_its_end():
    detail = error_detail({"error": "E: x", "error_trace": "line\n" * 5000 + "E: the end"})
    assert detail["trace"].startswith("…") and detail["trace"].endswith("E: the end")


def test_without_a_notebook_the_location_still_names_cell_and_line():
    detail = error_detail({"error_trace": TRACE})
    assert detail["location"]["line"] == 6 and "cell" not in detail["location"]
    assert detail["location"]["cell_ref"] == "8959532166638294"


def test_redaction_masks_emails():
    assert redact("by a.b@c.io at 3") == "by <email> at 3"


def test_a_failure_line_for_search():
    from datetime import datetime, timezone

    line = failure_line("raw_ingestion", datetime(2026, 9, 30, tzinfo=timezone.utc),
                        {"error": "ValueError: Column Order Mismatch!\nExpected: [...]",
                         "location": {"cell": 1, "line": 172, "function": "process_single_table"}}, None)
    assert line == ("failure (2026-09-30): task raw_ingestion run failed: ValueError: Column Order Mismatch! "
                    "[cell 1, line 172, process_single_table]")
    assert "Workload failed" in failure_line("t", None, None, "Workload failed, see run output")
