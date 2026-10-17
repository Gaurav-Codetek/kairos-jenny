"""run_sql guardrails: read-only, no side doors, tables in the map, personal data masked.

Several cases reproduce what a connected agent actually did: reading a raw
upload with read_files(), selecting state from a raw feed under another
column name, and querying a table Kairos had not profiled.
"""

import asyncio
import uuid

import pytest

from kairos_kb.context.access import AgentIdentity
from kairos_kb.context.query import (
    MASK,
    check_read_only,
    check_side_doors,
    is_personal,
    referenced_tables,
    run_sql,
    shape_result,
    tainted_outputs,
    unqualified_tables,
)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM cat.sch.t LIMIT 10",
    "select count(*) from cat.sch.t where status = 'DELETE'",
    "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
    "SHOW TABLES IN cat.sch",
    "DESCRIBE TABLE cat.sch.t",
    "EXPLAIN SELECT 1",
    "SELECT 1;",
    "-- a comment saying DROP TABLE\nSELECT created_at, updated_by FROM cat.sch.t",
    "SELECT \"insert\" AS note /* update later */ FROM cat.sch.t",
    # Columns and functions that share a name with a write keyword (a real agent query refused before).
    "SELECT COMMENT, COUNT(*) AS n FROM db.s.reviews GROUP BY COMMENT ORDER BY n DESC",
    "SELECT r.COMMENT FROM db.s.reviews r WHERE r.COMMENT <> ''",
    "SELECT REPLACE(city, '_', ' ') AS city FROM db.s.t",
    "SELECT t.LOAD, t.USE AS usage FROM db.s.t ORDER BY LOAD DESC",
    "SELECT status FROM db.s.t WHERE status = 'UPDATED' OR last_update IS NULL",
])
def test_read_only_statements_are_allowed(sql):
    assert check_read_only(sql) is None


@pytest.mark.parametrize("sql, reason", [
    ("DELETE FROM cat.sch.t", "Only read-only"),
    ("DROP TABLE cat.sch.t", "Only read-only"),
    ("SELECT 1; DROP TABLE cat.sch.t", "One statement"),
    ("WITH x AS (SELECT 1) INSERT INTO cat.sch.t SELECT * FROM x", "INSERT"),
    ("CREATE TABLE cat.sch.t AS SELECT 1", "Only read-only"),
    ("EXPLAIN DELETE FROM cat.sch.t", "DELETE"),
    ("SET spark.sql.ansi.enabled = false", "Only read-only"),
    ("WITH x AS (SELECT 1) UPDATE cat.sch.t SET a = 1", "UPDATE"),
    ("WITH d AS (DELETE FROM cat.sch.t RETURNING *) SELECT * FROM d", "DELETE"),
    ("WITH x AS (SELECT 1) MERGE INTO cat.sch.t USING x ON 1 = 1", "MERGE"),
    ("EXPLAIN COMMENT ON TABLE cat.sch.t IS 'x'", "COMMENT"),
    ("EXPLAIN DROP TABLE cat.sch.t", "DROP"),
    ("SELECT 1 FROM cat.sch.t; CALL proc()", "One statement"),
    ("", "No SQL"),
])
def test_writes_and_multiple_statements_are_refused(sql, reason):
    assert reason in (check_read_only(sql) or "")


# ── side doors ──

@pytest.mark.parametrize("sql", [
    # What the agent did: read a raw upload directly.
    "SELECT * FROM read_files('/Volumes/c/s/v/RAW_867_DLY.csv', format => 'csv') LIMIT 1",
    "SELECT * FROM csv.`/Volumes/c/s/v/file.csv`",
    "SELECT * FROM delta.`abfss://x@y.dfs.core.windows.net/tables/t`",
    "SELECT secret('scope', 'key')",
    "SELECT http_request('https://example.com')",
    "SELECT ai_query('model', 'prompt')",
])
def test_reads_outside_the_maps_tables_are_refused(sql):
    assert check_side_doors(sql) is not None


def test_file_reads_can_be_allowed_explicitly_but_secrets_never():
    assert check_side_doors("SELECT * FROM read_files('/Volumes/a.csv')", allow_files=True) is None
    assert check_side_doors("SELECT secret('s', 'k')", allow_files=True) is not None


def test_a_function_named_in_a_string_is_not_a_call():
    assert check_side_doors("SELECT 'read_files(x)' AS note FROM c.s.t") is None


# ── tables must be fully qualified ──

@pytest.mark.parametrize("sql, loose", [
    ("SELECT * FROM t", ["t"]),
    ("SELECT * FROM sch.t JOIN c.s.u ON 1=1", ["sch.t"]),
    ("WITH x AS (SELECT * FROM c.s.t) SELECT * FROM x", []),
    ("SELECT EXTRACT(YEAR FROM invoice_date) y FROM c.s.t", []),
    ("SELECT TRIM(BOTH ' ' FROM name) FROM c.s.t", []),
    ("SHOW TABLES IN c.s", []),
    ("SELECT * FROM c.s.t WHERE id IN (SELECT id FROM c.s.u)", []),
    ("SELECT * FROM (SELECT 1 AS a) sub", []),
])
def test_unqualified_tables(sql, loose):
    assert unqualified_tables(sql) == loose


def test_referenced_tables_ignore_strings_and_comments():
    sql = "SELECT * FROM `Cat`.sch.t1 JOIN cat.sch.t2 USING (k) WHERE s = 'a.b.c' -- x.y.z"
    assert referenced_tables(sql) == {"cat.sch.t1", "cat.sch.t2"}


# ── personal data ──

@pytest.mark.parametrize("column, personal", [
    ("CUST_NAME", True), ("CUST_ADDRESS_LINE_1", True), ("CUST_ZIP", True), ("CUST_DEA", True),
    ("CUST_HIN", True), ("DETAIL_REPORT_GROUP_NM", True), ("DETAIL_REPORT_GROUP_ADDR_INFO_1_TXT", True),
    ("DETAIL_REPORT_GROUP_POSTAL_CD", True), ("PRIM_REPORT_GROUP_DEA_NBR", True), ("patient_first_name", True),
    ("email", True), ("ORG_POSTAL_CODE", True),
    # Not personal: organisations, contracts, products, amounts, identifiers of records.
    ("ORG_NAME", False), ("SYSTEM_NAME", False), ("CONTRACT_NAME", False), ("PRODUCT", False),
    ("INVOICE_ID", False), ("AMOUNT", False), ("NDC_CODE", False),
])
def test_identifying_columns_are_recognised_by_name(column, personal):
    assert is_personal(column, geography=False) is personal


def test_geography_is_personal_only_when_configured():
    for column in ("CUST_STATE", "DETAIL_REPORT_GROUP_STATE_NM", "CUST_CITY"):
        assert is_personal(column, geography=False) is False


def test_aliases_and_expressions_carry_personal_data_through():
    personal = {"cust_name", "cust_zip"}
    sql = """
        WITH c AS (SELECT CUST_NAME AS who, CUST_ZIP, AMOUNT FROM cat.s.t)
        SELECT upper(who) AS customer, COUNT(DISTINCT who) AS customers, SUM(AMOUNT) amt, CUST_ZIP z FROM c
    """
    tainted = tainted_outputs(sql, personal)
    assert {"who", "customer", "z"} <= tainted
    assert "customers" not in tainted and "amt" not in tainted


def test_results_mask_personal_values_and_cut_long_ones():
    result = {
        "status": {"state": "SUCCEEDED"},
        "manifest": {"schema": {"columns": [{"name": "customer", "type_name": "STRING"},
                                            {"name": "upper(cust_name)", "type_name": "STRING"},
                                            {"name": "customers", "type_name": "BIGINT"},
                                            {"name": "note", "type_name": "STRING"}]},
                     "total_row_count": 5},
        "result": {"data_array": [["Ana", "ANA", 3, "x" * 900], [None, None, 1, "ok"]]},
    }
    shaped = shape_result(result, tainted={"customer"}, personal={"cust_name"})
    assert shaped["rows"][0][:3] == [MASK, MASK, 3]
    assert shaped["rows"][1][0] is None                       # NULL stays NULL
    assert shaped["rows"][0][3].endswith("…") and len(shaped["rows"][0][3]) == 501
    assert shaped["masked_columns"] == ["customer", "upper(cust_name)"]
    assert shaped["truncated"] is True


def test_run_sql_checks_permission_and_safety_before_touching_anything():
    reader = AgentIdentity(agent_id=uuid.uuid4(), name="reader", scopes=frozenset({"read"}))
    assert "query" in asyncio.run(run_sql(None, reader, "SELECT 1"))["error"]
    querier = AgentIdentity(agent_id=uuid.uuid4(), name="q", scopes=frozenset({"read", "query"}))
    assert "read-only" in asyncio.run(run_sql(None, querier, "DROP TABLE cat.sch.t"))["error"]
    assert "read_files" in asyncio.run(run_sql(None, querier, "SELECT * FROM read_files('/Volumes/x.csv')"))["error"]
    assert "fully qualified" in asyncio.run(run_sql(None, querier, "SELECT * FROM t"))["error"]


def test_distinct_and_subqueries_are_tracked_too():
    personal = {"cust_name"}
    assert "cust_name" in tainted_outputs("SELECT DISTINCT CUST_NAME FROM c.s.t", personal)
    sub = "SELECT x FROM (SELECT CUST_NAME AS x FROM c.s.t) q"
    assert "x" in tainted_outputs(sub, personal)
