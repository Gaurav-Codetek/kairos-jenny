"""The exact error behind a failed task run — a fact for the map.

Databricks reports a failed task with a one-line status ("Workload failed,
see run output for details"). The real error sits in the run's output: the
exception, and an IPython traceback that names the notebook cell
(``<command-…>``), the line, the function and the code around it.

This module turns that output into structured evidence:

  error      the exception line, e.g. "ValueError: Column Order Mismatch!"
  frames     every notebook frame: cell command id, line, function, the code
             on that line — outermost first, the raising frame last
  location   where it failed, linked to the notebook source: cell N of M,
             line, function, code
  trace      the traceback without terminal colour codes, capped

It records what happened. Why it happened is for the agent reading the map.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

TRACE_CHARS = 6000
ERROR_CHARS = 2000

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# File <command-8959532166638294>, line 172, in process_single_table(metadata_row, schema_file)
_FRAME = re.compile(r"File\s+<command-(\d+)>,\s+line\s+(\d+)(?:,\s+in\s+([A-Za-z_][\w.]*))?")
# Cell In[12], line 4   (newer IPython spelling)
_CELL_FRAME = re.compile(r"Cell\s+In\s*\[(\d+)\],\s+line\s+(\d+)(?:,\s+in\s+([A-Za-z_][\w.]*))?")
# --> 259     process_single_table(metadata_row, SCHEMA_FILE)
_ARROW = re.compile(r"^\s*-+>\s*(\d+)\s?(.*)$")
_SOURCE_HEADER = "# Databricks notebook source"
_CELL_SPLIT = re.compile(r"\n# COMMAND -{5,}\n")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def strip_ansi(text: Optional[str]) -> str:
    return _ANSI.sub("", text or "")


def redact(text: str) -> str:
    """Errors can quote data. Mask e-mail addresses, the commonest personal value in them."""
    return _EMAIL.sub("<email>", text)


def parse_traceback(trace: Optional[str]) -> List[Dict[str, Any]]:
    """Notebook frames, outermost first, each with the code on its failing line."""
    lines = strip_ansi(trace).splitlines()
    frames: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in lines:
        m = _FRAME.search(line) or _CELL_FRAME.search(line)
        if m:
            current = {
                "cell_ref": m.group(1),
                "line": int(m.group(2)),
                "function": m.group(3),
                "code": None,
            }
            frames.append(current)
            continue
        if current is not None and current["code"] is None:
            a = _ARROW.match(line)
            if a and int(a.group(1)) == current["line"]:
                current["code"] = a.group(2).strip() or None
    return frames


def error_line(error: Optional[str], trace: Optional[str]) -> Optional[str]:
    """The exception line: Databricks' `error` field, else the last 'Name: message' line of the trace."""
    first = strip_ansi(error).strip()
    if first:
        return first[:ERROR_CHARS]
    for line in reversed(strip_ansi(trace).splitlines()):
        if re.match(r"^\s*[A-Z][\w.]*(Error|Exception|Exit|Interrupt)\b", line):
            return line.strip()[:ERROR_CHARS]
    return None


def notebook_cells(source: Optional[str]) -> List[List[str]]:
    """A notebook export split into cells (lines each), the export header removed."""
    if not source:
        return []
    cells = _CELL_SPLIT.split(source.replace("\r\n", "\n"))
    out = []
    for i, cell in enumerate(cells):
        lines = cell.split("\n")
        if i == 0 and lines and lines[0].strip() == _SOURCE_HEADER:
            lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
        out.append(lines)
    return out


def locate(frame: Dict[str, Any], cells: List[List[str]]) -> Optional[Dict[str, Any]]:
    """Which cell a frame's line is in: matching code at that line wins; matching code anywhere next."""
    # The trace was redacted before parsing; compare the source the same way.
    code = redact((frame.get("code") or "").strip())
    if not cells or not code:
        return None
    anywhere = None
    for n, cell in enumerate(cells, 1):
        idx = frame["line"] - 1
        if 0 <= idx < len(cell) and redact(cell[idx].strip()) == code:
            return {"cell": n, "cells": len(cells), "line_in_cell": frame["line"]}
        if anywhere is None:
            for j, line in enumerate(cell, 1):
                if redact(line.strip()) == code:
                    anywhere = {"cell": n, "cells": len(cells), "line_in_cell": j, "approximate": True}
                    break
    return anywhere


def error_detail(output: Dict[str, Any], notebook_source: Optional[str] = None,
                 notebook_path: Optional[str] = None) -> Dict[str, Any]:
    """Structured evidence for one failed task run, from Databricks' run output."""
    trace = redact(strip_ansi(output.get("error_trace")))
    frames = parse_traceback(trace)
    cells = notebook_cells(notebook_source)
    for f in frames:
        loc = locate(f, cells)
        if loc:
            f.update(loc)
    raising = frames[-1] if frames else None
    location = None
    if raising:
        location = {k: raising.get(k) for k in ("cell", "cells", "line", "function", "code", "cell_ref")
                    if raising.get(k) is not None}
        if notebook_path:
            location["notebook"] = notebook_path
    # Keep the end of a long trace: the raising frame and the exception are there.
    if len(trace) > TRACE_CHARS:
        trace = "…\n" + trace[-TRACE_CHARS:]
    return {
        "error": redact(error_line(output.get("error"), trace) or "") or None,
        "location": location,
        "frames": frames[:12],
        "trace": trace or None,
    }
