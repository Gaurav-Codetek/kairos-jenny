"""The rough edges, fixed: code scan, blended templates, people as facts,
the batched column pass, coverage refresh and reconciliation."""

import pytest
from langchain_core.messages import AIMessage

import kairos_kb.enrichment.agent as agent_module
from kairos_kb.enrichment import pipeline
from kairos_kb.enrichment.pipeline import (
    describe_missing_columns,
    effective_template,
    is_person_reference,
    reconcile_with_verification,
    refresh_column_coverage,
    role_brief,
    scan_code,
)

KNOWN = {
    "nexora_poc_catalog.bronze.raw_ics_867": "table:ws:nexora_poc_catalog.bronze.raw_ics_867",
    "nexora_poc_catalog.bronze.stg_ics_867": "table:ws:nexora_poc_catalog.bronze.stg_ics_867",
    "nexora_poc_catalog.logs.bronze_layer_logs": "table:ws:nexora_poc_catalog.logs.bronze_layer_logs",
}

# Shaped like raw_to_stage_ics: names assigned to variables, used later.
CODE = '''
RAW_TABLE_NAME = "nexora_poc_catalog.bronze.raw_ics_867"
df = spark.sql("SELECT * FROM nexora_poc_catalog.bronze.raw_ics_867 WHERE x = 1")
df.write.mode("overwrite").saveAsTable("nexora_poc_catalog.bronze.stg_ics_867")
spark.sql("INSERT INTO nexora_poc_catalog.logs.bronze_layer_logs VALUES (1)")
cfg = spark.read.csv("/Volumes/nexora_poc_catalog/metadata/nexora_volume/config/schema_mapping.csv")
other = "some.unknown.table"
'''


def test_code_scan_finds_known_tables_and_how_they_are_used():
    scan = scan_code(CODE, KNOWN)
    by = {t["table"]: t for t in scan["tables_in_code"]}
    assert set(by) == set(KNOWN)  # unknown three-part names are ignored
    assert by["nexora_poc_catalog.bronze.raw_ics_867"]["modes"] == ["read"]  # "named" drops once a use is seen
    assert by["nexora_poc_catalog.bronze.stg_ics_867"]["modes"] == ["write"]
    assert by["nexora_poc_catalog.logs.bronze_layer_logs"]["modes"] == ["write"]
    assert scan["volume_paths_in_code"] == ["/Volumes/nexora_poc_catalog/metadata/nexora_volume/config/schema_mapping.csv"]
    assert by["nexora_poc_catalog.bronze.raw_ics_867"]["lines"] == [2, 3]


def test_a_task_brief_carries_its_code_and_the_scan():
    facts = {"code_available": True, "_code": CODE, **scan_code(CODE, KNOWN)}
    brief, _ = role_brief("task", None, facts)
    assert "THE TASK'S CODE" in brief and "saveAsTable" in brief and "tables_in_code" in brief
    assert '"_code"' not in brief  # the raw code is not duplicated inside the facts JSON


@pytest.mark.parametrize(
    "target,person",
    [
        ("yuvraj.brar@procdnaanalytics.onmicrosoft.com", True),
        ("interactive notebook session by a@b.com", True),
        ("interactive notebook (aakash.lal@procdnaanalytics.onmicrosoft.com)", True),
        ("/Workspace/Users/gaurav.patel@procdnaanalytics.onmicrosoft.com/ics_ingestion_notebook", False),
        ("nexora_poc_catalog.bronze.stg_ics_867", False),
        ("job:ws:572339974626818", False),
    ],
)
def test_people_and_sessions_are_facts_but_notebook_paths_are_entities(target, person):
    assert is_person_reference(target) is person


def test_two_close_roles_blend_their_templates():
    # gold_sales_data: FACT_EVENT 0.52, AGGREGATE_MART close behind.
    c = {"role": "OTHER", "role_top": [["FACT_EVENT", 0.52], ["AGGREGATE_MART", 0.41], ["OTHER", 0.04]]}
    label, template = effective_template(c)
    assert label == "FACT_EVENT or AGGREGATE_MART"
    assert template["grain_key"] == "required" and not template["light"]
    assert "decide which from the evidence" in template["must"][0]


def test_a_spread_out_classification_stays_generic():
    c = {"role": "OTHER", "role_top": [["FACT_EVENT", 0.40], ["LOG_AUDIT", 0.20], ["OTHER", 0.20]]}
    assert effective_template(c)[0] == "OTHER"


def test_a_confident_role_is_used_as_is():
    assert effective_template({"role": "DIMENSION_MASTER"})[0] == "DIMENSION_MASTER"


class _FakeStructured:
    """llm.with_structured_output(Model, include_raw=True).ainvoke → {raw, parsed}."""

    def __init__(self, make):
        self.make = make
        self.calls = 0

    def with_structured_output(self, model, include_raw=False):
        outer = self

        class Bound:
            async def ainvoke(self, messages):
                outer.calls += 1
                raw = AIMessage(content="", usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
                return {"raw": raw, "parsed": outer.make(model, messages)}

        return Bound()


async def test_the_column_pass_describes_every_undocumented_column_in_batches(monkeypatch):
    cols = [{"name": f"C{i}", "type": "string", "undocumented": True} for i in range(85)]
    fields = {"summary": "wide table", "shape": {"grain": "one row per x", "columns": [{"name": "ID", "meaning": "id"}, *cols]}}
    context = {"full_name": "cat.sch.wide", "columns": [{"name": c["name"]} for c in cols]}

    def make(model, messages):
        names = [line[2:].split(" ")[0] for line in messages[-1][1].splitlines() if line.startswith("- ")]
        return model(columns=[{"name": n, "meaning": f"meaning of {n}"} for n in names if n != "C3"] + [{"name": "C3", "meaning": "unclear"}])

    fake = _FakeStructured(make)
    monkeypatch.setattr(agent_module, "_build_llm", lambda: fake)

    class NoSamples:
        async def execute_query(self, sql):
            raise RuntimeError("no warehouse in tests")

    monkeypatch.setattr(pipeline, "DatabricksConnector", NoSamples)
    usage = []

    async def telemetry(**kw):
        usage.append(kw)

    filled = await describe_missing_columns(fields, context, telemetry)
    assert fake.calls == 3  # 85 columns in batches of 40
    assert filled == 84  # "unclear" is not accepted as a description
    c3 = next(c for c in fields["shape"]["columns"] if c["name"] == "C3")
    assert c3.get("undocumented") is True
    assert sum(u.get("input_tokens", 0) for u in usage) == 300  # tokens reach the live counter


def test_coverage_is_recomputed_after_completion():
    fields = {"shape": {"columns": [{"name": "A", "meaning": "a"}, {"name": "B", "propagated_from": "x.B"}, {"name": "C", "undocumented": True}]}}
    verification = {"passed": False, "checks": [{"check": "column_coverage", "result": "incomplete", "detail": ""},
                                                {"check": "grain", "result": "holds"}]}
    refresh_column_coverage(fields, verification, propagated=1, described=0)
    cov = verification["checks"][0]
    assert cov["result"] == "incomplete"
    assert cov["detail"] == "2 of 3 columns described; 1 propagated from upstream columns; 1 still undocumented"
    fields["shape"]["columns"][2].pop("undocumented")
    refresh_column_coverage(fields, verification, 1, 1)
    assert verification["checks"][0]["result"] == "ok" and verification["passed"] is True


async def test_reconcile_drops_questions_the_checks_answered(monkeypatch):
    def make(model, messages):
        return model(grain="Not unique on HCO_ID + ACTIVITY_DATE: 19,569 duplicate rows",
                     open_questions=["Why do duplicate HCO_ID + ACTIVITY_DATE rows exist?"])

    monkeypatch.setattr(agent_module, "_build_llm", lambda: _FakeStructured(make))
    fields = {"shape": {"grain": "one row per HCO per date"},
              "open_questions": ["Please confirm by checking the distinct count of (HCO_ID, ACTIVITY_DATE)."]}
    verification = {"checks": [{"check": "grain", "result": "fails", "detail": "19,569 duplicate rows"}]}
    assert await reconcile_with_verification(fields, verification) is True
    assert "19,569" in fields["shape"]["grain"]
    assert fields["open_questions"] == ["Why do duplicate HCO_ID + ACTIVITY_DATE rows exist?"]


async def test_reconcile_is_skipped_when_nothing_definite_was_checked(monkeypatch):
    fake = _FakeStructured(lambda m, msgs: None)
    monkeypatch.setattr(agent_module, "_build_llm", lambda: fake)
    assert await reconcile_with_verification({}, {"checks": [{"check": "grain", "result": "skipped"}]}) is False
    assert fake.calls == 0


# ── Stage 4: propagation along 1:1 column lineage ──


class _Edge:
    def __init__(self, source, target):
        self.source_entity_id, self.target_entity_id = source, target


class _Result:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class _Session:
    def __init__(self, edges):
        self.edges, self.calls = edges, 0

    async def execute(self, stmt):
        self.calls += 1
        # First query: lineage edges. Later ones: "is the upstream profiled?"
        return _Result(self.edges if self.calls == 1 else [object()])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


async def test_propagation_copies_only_pass_through_columns(monkeypatch):
    ws = "ws"
    up = f"column:{ws}:cat.sch.profile_metrics"
    dn = f"column:{ws}:cat.sch.drift_metrics"
    edges = [
        _Edge(f"{up}.window", f"{dn}.window"),                  # pass-through: same name, one source
        _Edge(f"{up}.count", f"{dn}.l_infinity_distance"),      # derived: different name
        _Edge(f"{up}.data_type", f"{dn}.data_type"),            # two sources for one target
        _Edge(f"{up}.column_type", f"{dn}.data_type"),
    ]
    monkeypatch.setattr(pipeline, "async_session_factory", lambda: _Session(edges))

    async def upstream(db, table_id):
        assert table_id == f"table:{ws}:cat.sch.profile_metrics"
        return {"shape": {"columns": [
            {"name": "window", "meaning": "the time window the metrics cover", "tags": ["time"]},
            {"name": "count", "meaning": "row count"},
            {"name": "data_type", "meaning": "the column's type"},
        ]}}

    monkeypatch.setattr(pipeline, "load_upstream_profile", upstream)
    fields = {"shape": {"columns": [
        {"name": "window", "undocumented": True},
        {"name": "l_infinity_distance", "undocumented": True},
        {"name": "data_type", "undocumented": True},
    ]}}
    context = {"entity_id": f"table:{ws}:cat.sch.drift_metrics"}
    assert await pipeline.propagate_column_docs(fields, context) == 1
    cols = {c["name"]: c for c in fields["shape"]["columns"]}
    assert cols["window"]["meaning"] == "the time window the metrics cover"
    assert cols["window"]["propagated_from"] == "cat.sch.profile_metrics.window"
    assert cols["l_infinity_distance"].get("undocumented") is True   # derived: no inherited meaning
    assert cols["data_type"].get("undocumented") is True             # ambiguous: two sources


# Exactly how raw_to_stage_ics builds its table names.
FSTRING_CODE = '''
CATALOG              = "nexora_poc_catalog"
BRONZE_SCHEMA        = "bronze"
RAW_TABLE_NAME       = f"{CATALOG}.{BRONZE_SCHEMA}.raw_ics_867"
STAGE_TABLE_NAME     = f"{CATALOG}.{BRONZE_SCHEMA}.stg_ics_867"
STAGE_LOG_TABLE      = "nexora_poc_catalog.logs.bronze_layer_logs"
print(f"Reading from: {RAW_TABLE_NAME}")
raw_cast_sql = f"""
SELECT {type_cast_sql}
FROM {RAW_TABLE_NAME}
"""
spark.sql(f"""
INSERT INTO {STAGE_TABLE_NAME}
SELECT * FROM staged
""")
log_df.write.mode("append").saveAsTable(STAGE_LOG_TABLE)
'''


def test_code_scan_resolves_table_names_built_from_variables():
    by = {t["table"]: t for t in scan_code(FSTRING_CODE, KNOWN)["tables_in_code"]}
    assert set(by) == set(KNOWN)
    assert "read" in by["nexora_poc_catalog.bronze.raw_ics_867"]["modes"]
    assert by["nexora_poc_catalog.bronze.raw_ics_867"]["via_variables"] == ["RAW_TABLE_NAME"]
    assert by["nexora_poc_catalog.bronze.stg_ics_867"]["modes"] == ["write"]
    assert by["nexora_poc_catalog.logs.bronze_layer_logs"]["modes"] == ["write"]


def test_duplicate_column_entries_are_merged_keeping_the_described_one():
    from kairos_kb.enrichment.pipeline import normalise_shape

    shape, notes = normalise_shape({"columns": [
        {"name": "invoice_item"}, {"name": "INVOICE_ITEM", "meaning": "line item id"}, {"name": "qty", "meaning": "q"},
    ]})
    assert [c["name"] for c in shape["columns"]] == ["INVOICE_ITEM", "qty"]
    assert shape["columns"][0]["meaning"] == "line item id"
    assert any("merged 1 duplicate" in n for n in notes)


def test_annotated_and_invented_column_names_are_aligned_to_the_real_columns():
    from kairos_kb.enrichment.pipeline import _align_to_real_columns

    listed = [
        {"name": "INVOICE_ITEM", "meaning": "line index"},
        {"name": "INVOICE_ITEM (as bigint if normalized)", "note": "stored as DOUBLE"},  # the real case
        {"name": "qty: units", "meaning": "quantity"},
        {"name": "made_up_column", "meaning": "?"},
    ]
    cols, detail = _align_to_real_columns(listed, ["INVOICE_ITEM", "QTY"])
    assert [c["name"] for c in cols] == ["INVOICE_ITEM", "QTY"]
    assert cols[0]["meaning"] == "line index" and "stored as DOUBLE" in cols[0]["note"]
    assert "folded 2 annotated" in detail and "removed 1 listed column" in detail
