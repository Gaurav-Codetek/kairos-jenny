"""Snowflake connector: naming, metadata shapes, task graphs, runs, lineage, SQL guards — no live account."""

import asyncio
import datetime as dt

import pytest

from kairos_kb.connectors import factory
from kairos_kb.connectors.snowflake import SnowflakeConnector, quote_ident, quote_name, split_name
from kairos_kb.context.query import check_side_doors


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def sf(monkeypatch):
    """A connector whose SQL is answered by a dict of {fragment: rows}."""
    c = SnowflakeConnector(config={"account": "acme-test"})
    answers = {}

    async def fake_query(sql, params=None, **kw):
        for frag, rows in answers.items():
            if frag in sql:
                return rows(params) if callable(rows) else rows
        return []

    async def fake_try(label, sql, params=None):
        return await fake_query(sql, params)

    monkeypatch.setattr(c, "_query", fake_query)
    monkeypatch.setattr(c, "_try", fake_try)
    c.answers = answers
    return c


def test_names_are_quoted_only_when_needed():
    assert quote_ident("SALES") == "SALES"
    assert quote_ident("Sales") == '"Sales"'
    assert quote_ident('we"ird') == '"we""ird"'
    assert quote_name("DB.SCH.My Table") == 'DB.SCH."My Table"'
    assert split_name('DB."a.b".T') == ["DB", "a.b", "T"]


def test_procedure_signatures_become_get_ddl_argument_types():
    assert SnowflakeConnector._arg_types("(START_DATE DATE, N NUMBER)") == "(DATE, NUMBER)"
    assert SnowflakeConnector._arg_types("()") == "()"
    assert SnowflakeConnector._arg_types(None) == "()"


def test_columns_keep_precision_in_their_type_text():
    col = SnowflakeConnector._column({"COLUMN_NAME": "AMT", "DATA_TYPE": "NUMBER", "NUMERIC_PRECISION": 38,
                                      "NUMERIC_SCALE": 2, "IS_NULLABLE": "NO", "ORDINAL_POSITION": 3})
    assert col["type_name"] == "NUMBER" and col["type_text"] == "NUMBER(38,2)" and col["nullable"] is False
    text = SnowflakeConnector._column({"COLUMN_NAME": "N", "DATA_TYPE": "TEXT", "CHARACTER_MAXIMUM_LENGTH": 255})
    assert text["type_name"] == "VARCHAR" and text["type_text"] == "VARCHAR(255)"


def test_excluded_databases_are_not_synced(sf):
    sf.answers["SHOW DATABASES"] = [{"NAME": "SALES", "KIND": "STANDARD"}, {"NAME": "SNOWFLAKE"},
                                    {"NAME": "SNOWFLAKE_SAMPLE_DATA"}]
    assert [c["name"] for c in run(sf.list_catalogs())] == ["SALES"]


def test_tables_views_dynamic_tables_and_streams_are_read_with_their_details(sf):
    sf.answers.update({
        "SCHEMATA": [{"SCHEMA_NAME": "CORE", "SCHEMA_OWNER": "SYSADMIN"}],
        ".TABLES": [
            {"TABLE_SCHEMA": "CORE", "TABLE_NAME": "FCT_SALES", "TABLE_TYPE": "BASE TABLE", "ROW_COUNT": 281,
             "BYTES": 9000, "CLUSTERING_KEY": "LINEAR(SALE_DATE)", "IS_TRANSIENT": "NO"},
            {"TABLE_SCHEMA": "CORE", "TABLE_NAME": "V_SALES", "TABLE_TYPE": "VIEW"},
            {"TABLE_SCHEMA": "CORE", "TABLE_NAME": "DT_DAILY", "TABLE_TYPE": "BASE TABLE"},
        ],
        ".COLUMNS": [{"TABLE_SCHEMA": "CORE", "TABLE_NAME": "FCT_SALES", "COLUMN_NAME": "INVOICE_ID",
                      "DATA_TYPE": "TEXT", "IS_NULLABLE": "YES", "ORDINAL_POSITION": 1}],
        ".VIEWS": [{"TABLE_SCHEMA": "CORE", "TABLE_NAME": "V_SALES", "VIEW_DEFINITION": "select * from fct_sales"}],
        "SHOW DYNAMIC TABLES": [{"NAME": "DT_DAILY", "SCHEMA_NAME": "CORE", "TARGET_LAG": "1 hour",
                                 "TEXT": "select 1", "REFRESH_MODE": "INCREMENTAL"}],
        "SHOW STREAMS": [{"NAME": "S_SALES", "SCHEMA_NAME": "CORE", "TABLE_NAME": "SALES.CORE.FCT_SALES",
                          "MODE": "DEFAULT", "STALE": "false"}],
        "TAG_REFERENCES": [{"OBJECT_DATABASE": "SALES", "OBJECT_SCHEMA": "CORE", "OBJECT_NAME": "FCT_SALES",
                            "COLUMN_NAME": "INVOICE_ID", "TAG_NAME": "PII", "TAG_VALUE": "none"}],
        "POLICY_REFERENCES": [{"REF_DATABASE_NAME": "SALES", "REF_SCHEMA_NAME": "CORE", "REF_ENTITY_NAME": "FCT_SALES",
                               "REF_COLUMN_NAME": "INVOICE_ID", "POLICY_KIND": "MASKING_POLICY", "POLICY_NAME": "M1"}],
    })
    tables = {t["name"]: t for t in run(sf.list_tables("SALES", "CORE"))}
    fct = tables["FCT_SALES"]
    assert fct["full_name"] == "SALES.CORE.FCT_SALES" and fct["row_count"] == 281 and fct["size_bytes"] == 9000
    assert fct["properties"]["clustering_key"] == "LINEAR(SALE_DATE)"
    assert fct["properties"]["column_tags"] == {"INVOICE_ID": ["PII=none"]}
    assert fct["properties"]["policies"][0]["kind"] == "MASKING_POLICY"
    assert fct["columns"][0]["name"] == "INVOICE_ID"
    assert tables["V_SALES"]["table_type"] == "VIEW" and "select" in tables["V_SALES"]["properties"]["definition"]
    assert tables["DT_DAILY"]["table_type"] == "DYNAMIC_TABLE"
    assert tables["DT_DAILY"]["properties"]["dynamic"]["target_lag"] == "1 hour"
    assert tables["S_SALES"]["table_type"] == "STREAM" and tables["S_SALES"]["properties"]["source"].endswith("FCT_SALES")


def _tasks():
    return [
        {"NAME": "ROOT", "DATABASE_NAME": "SALES", "SCHEMA_NAME": "CORE", "ID": "1", "OWNER": "SYSADMIN",
         "SCHEDULE": "USING CRON 0 6 * * * UTC", "STATE": "started", "PREDECESSORS": "[]",
         "DEFINITION": "CALL load_raw()"},
        {"NAME": "BUILD_FACT", "DATABASE_NAME": "SALES", "SCHEMA_NAME": "CORE", "ID": "2",
         "PREDECESSORS": '["\\"SALES\\".\\"CORE\\".\\"ROOT\\""]', "DEFINITION": "INSERT INTO fct SELECT * FROM stg"},
        {"NAME": "PUBLISH", "DATABASE_NAME": "SALES", "SCHEMA_NAME": "CORE", "ID": "3",
         "PREDECESSORS": '["SALES.CORE.BUILD_FACT"]', "DEFINITION": "CALL SALES.CORE.publish(1)"},
        {"NAME": "OTHER", "DATABASE_NAME": "SNOWFLAKE", "SCHEMA_NAME": "X", "ID": "9", "PREDECESSORS": "[]",
         "DEFINITION": "select 1"},
    ]


def test_task_graphs_become_pipelines_with_ordered_tasks_and_code(sf):
    sf.answers["SHOW TASKS"] = _tasks()
    sf.answers["SHOW DATABASES"] = []
    jobs = run(sf.list_jobs())
    assert [j["job_id"] for j in jobs] == ["SALES.CORE.ROOT"]  # the SNOWFLAKE database is excluded
    job = jobs[0]
    assert ":" not in job["job_id"]  # entity ids are colon-separated; job ids must not add colons
    tasks = {t["task_key"]: t for t in job["settings"]["tasks"]}
    assert set(tasks) == {"ROOT", "BUILD_FACT", "PUBLISH"}
    assert tasks["BUILD_FACT"]["depends_on"] == [{"task_key": "ROOT"}]
    assert tasks["PUBLISH"]["depends_on"] == [{"task_key": "BUILD_FACT"}]
    assert tasks["ROOT"]["notebook_task"]["notebook_path"] == "snowflake://procedure/SALES.CORE.load_raw"
    assert tasks["BUILD_FACT"]["sql_task"]["query"]["query_text"].startswith("INSERT")
    assert job["settings"]["schedule"]["snowflake_schedule"].startswith("USING CRON")


def test_task_history_groups_into_runs_with_task_failures(sf):
    sf.answers["SHOW TASKS"] = _tasks()
    sf.answers["SHOW DATABASES"] = []
    t0 = dt.datetime(2026, 10, 1, 6, 0, tzinfo=dt.timezone.utc)
    sf.answers["TASK_HISTORY"] = [
        {"NAME": "ROOT", "DATABASE_NAME": "SALES", "SCHEMA_NAME": "CORE", "STATE": "SUCCEEDED", "QUERY_ID": "q1",
         "GRAPH_RUN_GROUP_ID": "g1", "ATTEMPT_NUMBER": 1, "QUERY_START_TIME": t0, "COMPLETED_TIME": t0,
         "SCHEDULED_FROM": "SCHEDULE"},
        {"NAME": "BUILD_FACT", "DATABASE_NAME": "SALES", "SCHEMA_NAME": "CORE", "STATE": "FAILED", "QUERY_ID": "q2",
         "GRAPH_RUN_GROUP_ID": "g1", "ATTEMPT_NUMBER": 2, "ERROR_CODE": "100038",
         "ERROR_MESSAGE": "Numeric value 'abc' is not recognized", "QUERY_START_TIME": t0, "COMPLETED_TIME": t0},
    ]
    runs = run(sf.list_job_runs("SALES.CORE.ROOT"))
    assert len(runs) == 1
    r = runs[0]
    assert r["run_id"] == "g1" and r["state"]["result_state"] == "FAILED"
    assert "not recognized" in r["state"]["state_message"]
    failed = next(t for t in r["tasks"] if t["task_key"] == "BUILD_FACT")
    assert failed["attempt_number"] == 1 and failed["state"]["result_state"] == "FAILED"
    out = run(sf.get_run_output("q2"))
    assert out["error"].startswith("100038") and run(sf.get_run("g1")) is r


def test_lineage_merges_dependencies_and_observed_writes(sf):
    sf.answers["OBJECT_DEPENDENCIES"] = [{
        "REFERENCED_DATABASE": "SALES", "REFERENCED_SCHEMA": "CORE", "REFERENCED_OBJECT_NAME": "FCT_SALES",
        "REFERENCING_DATABASE": "SALES", "REFERENCING_SCHEMA": "CORE", "REFERENCING_OBJECT_NAME": "V_SALES",
        "REFERENCING_OBJECT_DOMAIN": "VIEW"}]
    sf.answers["base_objects_accessed"] = [{"SRC": "SALES.CORE.STG", "TGT": "SALES.CORE.FCT_SALES"},
                                           {"SRC": "SNOWFLAKE.X.Y", "TGT": "SALES.CORE.FCT_SALES"},
                                           {"SRC": "SALES.CORE.FCT_SALES", "TGT": "SALES.CORE.FCT_SALES"}]
    edges = run(sf.get_table_lineage())
    pairs = {(e["source_table_name"], e["target_table_name"]) for e in edges}
    assert pairs == {("FCT_SALES", "V_SALES"), ("STG", "FCT_SALES")}  # excluded db and self-loops dropped


def test_query_results_come_back_in_the_statement_shape(monkeypatch):
    c = SnowflakeConnector(config={"account": "a"})

    def fake_run(sql, params=None, *, limit=None, timeout=None):
        return ([{"name": "N", "type_name": "0"}], [(281,), (None,)], True)

    monkeypatch.setattr(c, "_run", fake_run)
    res = run(c.execute_query("select 1", row_limit=2))
    assert res["status"]["state"] == "SUCCEEDED" and res["manifest"]["truncated"] is True
    assert res["result"]["data_array"] == [["281"], [None]]
    assert SnowflakeConnector._rows_from_statement_result(res) == [{"N": "281"}, {"N": None}]


@pytest.mark.parametrize("sql", [
    "SELECT $1 FROM @my_stage/file.csv",
    "SELECT * FROM @~/x",
    "select * from table(result_scan(last_query_id()))",
    "select system$get_privatelink_config()",
    "select * from table(infer_schema(location=>'@s', file_format=>'f'))",
])
def test_snowflake_side_doors_are_refused(sql):
    assert check_side_doors(sql) is not None


@pytest.mark.parametrize("sql", [
    "SELECT email FROM SALES.CORE.USERS WHERE email LIKE '%@acme.com'",
    "SELECT * FROM SALES.CORE.FCT_SALES",
])
def test_ordinary_snowflake_queries_pass(sql):
    assert check_side_doors(sql) is None


def test_factory_picks_and_quotes_by_platform():
    class WS:
        platform, host, connection_config = "snowflake", "https://x.snowflakecomputing.com", {"account": "x"}

    sf = factory.connector_for(WS())
    assert factory.sql_dialect(sf) == "snowflake"
    assert factory.quote_table(sf, "DB.SCH.My Table") == 'DB.SCH."My Table"'
    db = factory.connector_for(None)
    assert factory.sql_dialect(db) == "databricks"
    assert factory.quote_table(db, "c.s.t") == "`c`.`s`.`t`"
    assert factory.workspace_name_of("table:My WS:DB.SCH.T") == "My WS"


# ── Build statements and code ────────────────────────────────────────

from kairos_kb.connectors.snowflake import dbt_node, statement_target  # noqa: E402
from kairos_kb.enrichment.pipeline import table_code  # noqa: E402

DBT_CTAS = ('/* {"app": "dbt", "dbt_version": "1.9.0", "node_id": "model.zomato.fct_orders"} */\n'
            "create or replace transient table ZOMATO.marts.fct_orders as (select * from ZOMATO.staging.stg_orders)")


@pytest.mark.parametrize("sql, db, schema, target", [
    (DBT_CTAS, "ZOMATO", "MARTS", "ZOMATO.MARTS.FCT_ORDERS"),
    ("insert into orders select 1", "ZOMATO", "RAW", "ZOMATO.RAW.ORDERS"),
    ("INSERT OVERWRITE INTO raw.orders SELECT 1", "ZOMATO", "PUBLIC", "ZOMATO.RAW.ORDERS"),
    ("merge into ZOMATO.marts.fct_orders t using x on t.id = x.id", None, None, "ZOMATO.MARTS.FCT_ORDERS"),
    ("COPY INTO ZOMATO.RAW.ORDERS FROM @ZOMATO.RAW.LANDING/orders/", None, None, "ZOMATO.RAW.ORDERS"),
    ("create table if not exists t2 (a int)", "D", "S", "D.S.T2"),
    ("select * from x", "D", "S", None),
    ("insert into orders select 1", None, None, None),  # unqualified with no session context
])
def test_statement_targets(sql, db, schema, target):
    assert statement_target(sql, db, schema) == target


def test_dbt_model_is_read_from_the_statement_comment():
    assert dbt_node(DBT_CTAS) == "model.zomato.fct_orders"
    assert dbt_node("create table x as select 1") is None


def test_build_history_prefers_ctas_and_keeps_loads_separately():
    props = {}
    SnowflakeConnector._attach_build(props, {
        "latest": {
            "CREATE_TABLE_AS_SELECT": {"statement_type": "CREATE_TABLE_AS_SELECT", "at": "t1", "by": "u",
                                       "dbt_model": "model.z.fct", "sql": "create … as select"},
            "MERGE": {"statement_type": "MERGE", "at": "t2", "by": "u", "sql": "merge …"},
            "COPY": {"statement_type": "COPY", "at": "t0", "sql": "copy into …"},
        },
        "counts": {"CREATE_TABLE_AS_SELECT": 1, "MERGE": 2, "COPY": 5}, "last_write": "t2"})
    assert props["build_sql"] == "create … as select" and props["build"]["dbt_model"] == "model.z.fct"
    assert props["load_sql"] == "copy into …"
    assert props["writes"]["by_statement"]["MERGE"] == 2 and "MERGE" in props["writes"]["others"]


def test_table_code_picks_the_right_sql_and_says_where_it_came_from():
    view = table_code({"definition": "create view v as select * from a"}, "VIEW")
    assert view["kind"] == "view definition" and "select" in view["sql"]
    dyn = table_code({"definition": "select 1"}, "DYNAMIC_TABLE")
    assert dyn["kind"] == "dynamic table definition"
    built = table_code({"build_sql": "create table t as select 1",
                        "build": {"statement_type": "CREATE_TABLE_AS_SELECT", "dbt_model": "model.z.t", "at": "x"}},
                       "TRANSIENT")
    assert built["kind"].startswith("build statement") and built["dbt_model"] == "model.z.t"
    loaded = table_code({"load_sql": "copy into t from @s"}, "MANAGED")
    assert loaded["kind"].startswith("load statement")
    assert table_code({}, "MANAGED") is None


def test_an_expired_session_signs_in_again_once(monkeypatch):
    from snowflake.connector.errors import ProgrammingError

    from kairos_kb.connectors import snowflake as sfmod

    calls = {"connect": 0, "execute": 0}

    class Cur:
        description = [("N", 0)]

        def execute(self, sql, params=None, timeout=None):
            calls["execute"] += 1
            if calls["execute"] == 1:
                raise ProgrammingError(msg="Authentication token has expired.  The user must authenticate again.",
                                       errno=390114)

        def fetchmany(self, n):
            return [(1,)]

        def close(self):
            pass

    class Conn:
        def cursor(self):
            return Cur()

        def is_closed(self):
            return False

        def close(self):
            pass

    def fake_connect(self):
        calls["connect"] += 1
        return Conn()

    monkeypatch.setattr(sfmod.SnowflakeConnector, "_connect", fake_connect)
    sfmod._CONNECTIONS.clear()
    c = sfmod.SnowflakeConnector(config={"account": "a", "user": "u"})
    cols, rows, _ = c._run("select 1", limit=5)
    assert rows == [(1,)] and calls == {"connect": 2, "execute": 2}  # dropped, signed in again, retried once


def test_statement_errors_are_not_retried():
    from snowflake.connector.errors import ProgrammingError

    from kairos_kb.connectors.snowflake import _session_lost

    assert _session_lost(ProgrammingError(msg="Authentication token has expired.", errno=390114))
    assert not _session_lost(ProgrammingError(msg="SQL compilation error: invalid identifier 'X'", errno=904))
