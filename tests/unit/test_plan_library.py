"""The node library: the column comparison, the verify checks, and the SQL guard."""

import pytest

from kairos_kb.agent.plan_library import (
    _assert_read_only,
    _quote_table,
    column_diff,
    counts_match_error,
    diff_explains_class,
)


# ── column_diff ──────────────────────────────────────────────────────


def test_identical_lists():
    d = column_diff(["a", "b"], ["a", "b"])
    assert d["identical"] and not d["extra"] and not d["missing"] and not d["moved"]


def test_extra_column_appended():
    d = column_diff(["a", "b"], ["a", "b", "c"])
    assert d["extra"] == ["c"]
    assert d["missing"] == []
    assert (d["expected_count"], d["actual_count"]) == (2, 3)
    assert d["order_changed"] is False


def test_rename_in_place_is_a_rename_candidate():
    d = column_diff(["a", "sales_qty", "c"], ["a", "sold_qty", "c"])
    assert d["rename_candidates"] == [{"expected": "sales_qty", "actual": "sold_qty", "position": 2}]
    assert d["extra"] == ["sold_qty"] and d["missing"] == ["sales_qty"]


def test_rename_plus_extra_column_reports_both():
    # The ICS incident: one column renamed in place and one appended.
    d = column_diff(["A", "B", "SALES_QTY", "D"], ["A", "B", "SOLD_QTY", "D", "NEW_COL"])
    assert d["rename_candidates"] == [{"expected": "SALES_QTY", "actual": "SOLD_QTY", "position": 3}]
    assert set(d["extra"]) == {"SOLD_QTY", "NEW_COL"}
    assert (d["expected_count"], d["actual_count"]) == (4, 5)


def test_order_swap_lists_moved_columns():
    d = column_diff(["a", "b", "c"], ["b", "a", "c"])
    assert d["order_changed"] is True
    assert {m["column"] for m in d["moved"]} == {"a", "b"}
    assert not d["extra"] and not d["missing"]


def test_comparison_is_case_insensitive_by_default():
    assert column_diff(["Sales_Qty"], ["sales_qty"])["identical"]
    assert not column_diff(["Sales_Qty"], ["sales_qty"], case_sensitive=True)["identical"]


def test_accepts_rows_with_a_field_and_column_results():
    expected = {"rows": [{"col": "a", "seq": 1}, {"col": "b", "seq": 2}], "row_count": 2}
    actual = {"columns": ["a", "b", "c"], "count": 3}
    assert column_diff(expected, actual, expected_field="col")["extra"] == ["c"]


def test_rows_without_field_is_an_error():
    with pytest.raises(ValueError):
        column_diff({"rows": [{"col": "a"}]}, ["a"])


def test_databricks_system_columns_are_ignored():
    assert column_diff(["a"], ["a", "_rescued_data"])["identical"]


# ── verify checks ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expected,actual,cls,ok",
    [
        (["a"], ["a", "b"], "EXTRA_COLUMN", True),
        (["a", "b"], ["a", "c"], "COLUMN_RENAME", True),
        (["a", "b"], ["b", "a"], "COLUMN_ORDER_SWAP", True),
        (["a", "b"], ["b", "a"], "EXTRA_COLUMN", False),
        (["a", "b"], ["a", "b"], "COLUMN_RENAME", False),
        (["a"], ["a", "b"], "NOT_SCHEMA_RELATED", False),
    ],
)
def test_diff_explains_class(expected, actual, cls, ok):
    assert diff_explains_class(column_diff(expected, actual), cls)["ok"] is ok


def test_counts_match_error():
    d = column_diff(["a", "b"], ["a", "b", "c"])
    assert counts_match_error(d, "ValueError: Column Count Mismatch! Expected 2, got 3")["ok"]
    assert not counts_match_error(d, "Column Count Mismatch! Expected 78, got 79")["ok"]


def test_counts_check_is_not_applicable_without_counts():
    d = column_diff(["a", "b"], ["a", "c"])
    result = counts_match_error(d, "ValueError: Column Order Mismatch!")
    assert result["ok"] and "not applicable" in result["detail"]


# ── read-only SQL guard (security-critical) ──────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "  select * from t",
        "SELECT 1;",
        "WITH x AS (SELECT 1 AS a) SELECT * FROM x",
        "DESCRIBE HISTORY `a`.`b`.`c`",
        "SHOW TABLES IN a.b",
        # Keywords inside identifiers are not statements.
        "SELECT update_ts, created_by, dropped_flag FROM t",
    ],
)
def test_read_only_statements_pass(sql):
    _assert_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE t",
        "delete from t",
        "INSERT INTO t SELECT 1",
        "UPDATE t SET a = 1",
        "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN DELETE",
        "CREATE TABLE t AS SELECT 1",
        "ALTER TABLE t ADD COLUMN c INT",
        "TRUNCATE TABLE t",
        "OPTIMIZE t",
        "VACUUM t",
        "GRANT SELECT ON t TO x",
        "SELECT 1; DELETE FROM t",
        "WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x",
        # Conservative on purpose: a write keyword anywhere is refused.
        "SELECT 'drop' AS x",
    ],
)
def test_writes_are_refused(sql):
    with pytest.raises(ValueError):
        _assert_read_only(sql)


def test_quote_table():
    assert _quote_table("a.b.c") == "`a`.`b`.`c`"
    assert _quote_table("table:ws:a.b.c") == "`a`.`b`.`c`"
    for bad in ("a.b", "a.b.c; drop table x", "a.b.c d", "a.b`.c"):
        with pytest.raises(ValueError):
            _quote_table(bad)
