"""The fixed node library compiled RCA plans are built from.

Agent A (the learning agent) may only compose plans out of what is defined
here; Agent B (the plan executor) only knows how to run these. Keeping the
library small and hand-written is what makes a compiled plan safe to run
without an LLM choosing tools:

- structured tools: return column lists and rows as data, not prose, so the
  comparison can be done in code
- compute ops: pure Python over earlier results
- verify ops: deterministic checks that decide whether a diagnosis holds

Every SQL statement is read-only by construction (see ``_assert_read_only``).
Kairos explains; it never writes to the platform.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from langchain_core.tools import tool

from kairos_kb.agent.scope import rca_connector
from kairos_kb.connectors.databricks import DatabricksConnector
from kairos_kb.context.privacy import mask_rows

# Columns Databricks adds itself when reading files; never part of a schema.
SYSTEM_COLUMNS = {"_rescued_data", "_metadata"}

_READ_ONLY_START = re.compile(r"^\s*(SELECT|WITH|DESCRIBE|SHOW)\b", re.IGNORECASE)
_WRITE_WORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|REPLACE|COPY|OPTIMIZE|VACUUM|RESTORE)\b",
    re.IGNORECASE,
)
_IDENT = re.compile(r"^[A-Za-z0-9_\-]+$")


def _assert_read_only(sql: str) -> None:
    if ";" in sql.strip().rstrip(";"):
        raise ValueError("Only a single statement is allowed.")
    if not _READ_ONLY_START.match(sql) or _WRITE_WORDS.search(sql):
        raise ValueError("Only read-only SELECT / WITH / DESCRIBE / SHOW statements are allowed.")


def _sql_str(value: str) -> str:
    return value.replace("'", "''")


def _quote_table(name: str) -> str:
    full = name.rsplit(":", 1)[-1] if name.startswith("table:") else name
    parts = full.strip("`").split(".")
    if len(parts) != 3 or not all(_IDENT.match(p) for p in parts):
        raise ValueError(f"Expected 'catalog.schema.table', got {name!r}.")
    return ".".join(f"`{p}`" for p in parts)


async def _columns_of(sql: str) -> List[str]:
    result = await rca_connector().execute_query(sql)
    cols = result.get("manifest", {}).get("schema", {}).get("columns", [])
    return [c["name"] for c in cols if c["name"] not in SYSTEM_COLUMNS]


# ── Structured tools (usable by Agent A as tools, by Agent B as nodes) ──


@tool
async def get_file_columns(file_path: str, format: str = "csv") -> Dict[str, Any]:
    """Get the ordered column names of a data file in a Volume, as a list (CSV read WITH its header row).

    Prefer this over query_databricks_data_file whenever you need a file's actual columns:
    it returns them as data you can compare, in file order.

    Args:
        file_path: Absolute path, e.g. /Volumes/<catalog>/<schema>/<volume>/<file>.csv
        format: csv, parquet or json.
    """
    if format not in ("csv", "parquet", "json"):
        return {"error": f"Unsupported format {format!r}."}
    header = ", header => true" if format == "csv" else ""
    try:
        cols = await _columns_of(
            f"SELECT * FROM read_files('{_sql_str(file_path)}', format => '{format}'{header}) LIMIT 0"
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not read columns of {file_path}: {exc}"}
    return {"file_path": file_path, "columns": cols, "count": len(cols)}


@tool
async def get_table_columns(table: str) -> Dict[str, Any]:
    """Get the ordered column names of a table as it exists right now, as a list.

    Args:
        table: Full name 'catalog.schema.table', or a table entity_id.
    """
    try:
        cols = await _columns_of(f"SELECT * FROM {_quote_table(table)} LIMIT 0")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not read columns of {table}: {exc}"}
    return {"table": table, "columns": cols, "count": len(cols)}


@tool
async def run_select_query(sql: str, max_rows: int = 500) -> Dict[str, Any]:
    """Run a read-only SQL query and return its rows as a list of objects.

    Use read_files('<path>', format => 'csv', header => true) to query a CSV in a Volume with its
    real column names, e.g. a mapping or config file. Only SELECT / WITH / DESCRIBE / SHOW are allowed.

    Args:
        sql: A single read-only statement.
        max_rows: Maximum rows to return.
    """
    try:
        _assert_read_only(sql)
        result = await rca_connector().execute_query(sql)
        rows = DatabricksConnector._rows_from_statement_result(result)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Query failed: {exc}"}
    rows = mask_rows([{k: v for k, v in r.items() if k not in SYSTEM_COLUMNS} for r in rows])
    return {"rows": rows[: max(1, min(int(max_rows), 5000))], "row_count": len(rows)}


@tool
async def read_code_file(file_path: str) -> Dict[str, Any]:
    """Read a whole notebook or code file from the Workspace or a Volume.

    Args:
        file_path: Absolute path starting with /Workspace, /Users, /Repos, /Shared or /Volumes.
    """
    try:
        text = await rca_connector().read_workspace_file(file_path)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not read {file_path}: {exc}"}
    return {"file_path": file_path, "text": text, "chars": len(text)}


STRUCTURED_TOOLS = [get_file_columns, get_table_columns, run_select_query, read_code_file]


# ── Compute ops (pure Python) ────────────────────────────────────────


def _as_names(value: Any, field: Optional[str]) -> List[str]:
    """Accept a list of names, a {columns: [...]} result, or rows with a field to pluck."""
    if isinstance(value, dict):
        if "columns" in value:
            value = value["columns"]
        elif "rows" in value:
            value = value["rows"]
    if not isinstance(value, list):
        raise ValueError(f"Expected a list of column names or rows, got {type(value).__name__}.")
    if value and isinstance(value[0], dict):
        if not field:
            raise ValueError("Rows were given without 'field' naming which value is the column name.")
        value = [row.get(field) for row in value]
    return [str(v) for v in value if v is not None and str(v) not in SYSTEM_COLUMNS]


def column_diff(expected: Any, actual: Any, expected_field: str = "", actual_field: str = "",
                case_sensitive: bool = False) -> Dict[str, Any]:
    """Compare an expected column list with an actual one: extra, missing, reordered, rename candidates."""
    exp = _as_names(expected, expected_field or None)
    act = _as_names(actual, actual_field or None)
    norm = (lambda s: s.strip()) if case_sensitive else (lambda s: s.strip().lower())
    exp_n, act_n = [norm(c) for c in exp], [norm(c) for c in act]
    exp_set, act_set = set(exp_n), set(act_n)

    extra = [c for c, n in zip(act, act_n) if n not in exp_set]
    missing = [c for c, n in zip(exp, exp_n) if n not in act_set]

    # A missing and an extra column at the same position are a rename candidate.
    extra_pos = {i: c for i, (c, n) in enumerate(zip(act, act_n)) if n not in exp_set}
    rename_candidates = [
        {"expected": c, "actual": extra_pos[i], "position": i + 1}
        for i, (c, n) in enumerate(zip(exp, exp_n))
        if n not in act_set and i in extra_pos
    ]

    common_exp = [n for n in exp_n if n in act_set]
    common_act = [n for n in act_n if n in exp_set]
    moved = [
        {"column": exp[exp_n.index(n)], "expected_position": exp_n.index(n) + 1, "actual_position": act_n.index(n) + 1}
        for i, n in enumerate(common_exp)
        if i < len(common_act) and common_act[i] != n
    ]

    return {
        "expected_count": len(exp),
        "actual_count": len(act),
        "extra": extra,
        "missing": missing,
        "rename_candidates": rename_candidates,
        "order_changed": common_exp != common_act,
        "moved": moved,
        "identical": exp_n == act_n,
    }


COMPUTE_OPS: Dict[str, Callable[..., Any]] = {"column_diff": column_diff}


# ── Verify ops (deterministic acceptance checks) ─────────────────────

_COUNTS = re.compile(r"expected\D{0,30}?(\d+)\D{1,40}?(?:got|actual|found|received)\D{0,10}?(\d+)", re.IGNORECASE)


def diff_explains_class(diff: Dict[str, Any], failure_class: str) -> Dict[str, Any]:
    """Does the computed diff show the kind of change the class claims?"""
    checks = {
        "EXTRA_COLUMN": bool(diff.get("extra")),
        "COLUMN_RENAME": bool(diff.get("rename_candidates") or diff.get("missing")),
        "COLUMN_ORDER_SWAP": bool(diff.get("order_changed") or diff.get("moved")),
    }
    ok = checks.get(failure_class, False)
    return {"ok": ok, "detail": f"{failure_class} {'is' if ok else 'is NOT'} shown by the diff"}


def counts_match_error(diff: Dict[str, Any], error: Any) -> Dict[str, Any]:
    """If the error states expected/actual counts, they must equal the diff's counts."""
    match = _COUNTS.search(str(error or ""))
    if not match:
        return {"ok": True, "detail": "error states no column counts; check not applicable"}
    exp, act = int(match.group(1)), int(match.group(2))
    ok = exp == diff.get("expected_count") and act == diff.get("actual_count")
    return {
        "ok": ok,
        "detail": f"error says expected {exp}, got {act}; diff has {diff.get('expected_count')} vs {diff.get('actual_count')}",
    }


VERIFY_OPS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "diff_explains_class": diff_explains_class,
    "counts_match_error": counts_match_error,
}


LIBRARY_DOC = """\
NODE LIBRARY — a plan is an ordered list of nodes; each node's output is stored under its id.

References in args:
  "$id.path"            the whole value, e.g. "$run.failed_tasks[0].source_native_id"
  "text {{id.path}} x"  interpolated into a string (single quotes are escaped for SQL)
  "$input.run_id" and "$input.failure_class" are always available.

type=tool  (name = tool name, args = its arguments)
  get_failed_run_details(run_id)            -> {failed_tasks:[{task_key, taskrun_entity_id, source_native_id, error_message}], ...}
  get_task_context(entity_id)               -> {task_entity_id, notebook_path, sql_query, parameters, ...}
  get_task_error_trace(source_native_id)    -> {error, error_trace}
  read_code_file(file_path)                 -> {text}
  get_file_columns(file_path, format)       -> {columns:[...], count}
  get_table_columns(table)                  -> {columns:[...], count}
  run_select_query(sql, max_rows)           -> {rows:[{...}], row_count}   (read-only; use read_files(...) for Volume files)
  get_data_dependencies(entity_id)          -> reads / writes of a task
  get_delta_table_history(table, limit)     -> {history:[...]}
  (any other agent tool by name is also allowed)

type=extract  (name = "extract")
  args: {"from": "$id" or ["$id", ...], "fields": {"<field>": "<what to find>", ...}}
  One LLM call pulls each field VERBATIM out of the given text (e.g. a file path or a
  subject area written in the code). Every value must appear literally in the source.

type=compute  (name = op)
  column_diff(expected, actual, expected_field="", actual_field="", case_sensitive=false)
     expected/actual: a {columns} result, a list, or {rows} with *_field naming the column-name field
     -> {expected_count, actual_count, extra, missing, rename_candidates, order_changed, moved, identical}

type=verify  (name = op)   — the plan FAILS if a verify returns ok=false
  diff_explains_class(diff, failure_class)
  counts_match_error(diff, error)          error = the error text (e.g. "$trace.error")

type=report  (name = "report")   — must be the last node
  args: {"facts": {"<label>": "$id", ...}}   the report is written ONLY from these facts
"""
