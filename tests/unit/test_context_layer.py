"""The context layer: what any agent connected to Kairos reads.

Pure logic only — documents, search fusion, join ranking, trust, caveats,
access rules, feedback briefs and the cold-agent scoring. The database and
LLM paths are exercised end to end against the running stack.
"""

import asyncio
import uuid

import pytest

from kairos_kb.context import access
from kairos_kb.context.access import AgentIdentity, audited, key_from_headers
from kairos_kb.context.cards import caveats, example_sql, key_columns
from kairos_kb.context.documents import compose, first_sentence, name_words, trust_level
from kairos_kb.context.feedback import feedback_brief
from kairos_kb.context.joins import is_key_like, score_shared, type_family
from kairos_kb.context.search import _name_query, rrf_merge
from kairos_kb.enrichment.pipeline import PIPELINE_VERSION, check_link_kinds, profile_digest
from kairos_kb.evals.cold_agent import mention_score

TABLE = "table:ICS Sales Warehouse:nexora.silver.fct_ics_867"

PROFILE = {
    "summary": "Silver ICS sales fact at invoice line level. Feeds the gold aggregate.",
    "purpose": "Curated fact for analytics.",
    "data_product": "Nexora PoC / ICS Sales",
    "semantic_tags": ["fact_event", "role:fact_event", "layer:silver_curated"],
    "classification": {"status": "ok", "role": "FACT_EVENT", "layer": "SILVER_CURATED", "scratch_or_test": 0.1},
    "shape": {"grain": "One row per invoice line item.",
              "columns": [{"name": "INVOICE_ID", "meaning": "Invoice identifier", "tags": "id,invoice"},
                          {"name": "CUST_NAME", "meaning": "Customer name", "tags": "pii,customer"},
                          {"name": "QUANTITY", "meaning": "Units sold", "tags": "measure,quantity"}]},
    "grain_key": "INVOICE_ID,INVOICE_ITEM",
    "facts": {"writers": [{"writer": "ics_sales_ingestion", "linkable": True, "entity_id": "job:ICS Sales Warehouse:1"}]},
    "verification": {"passed": False, "checks": [
        {"check": "column_coverage", "result": "ok"},
        {"check": "grain", "result": "fails", "detail": "51 duplicate rows"},
    ]},
}
CONTEXT = {
    "entity_id": TABLE, "kind": "table", "name": "fct_ics_867", "full_name": "nexora.silver.fct_ics_867",
    "attributes": {"comment": None},
    "columns": [{"name": "INVOICE_ID", "data_type": "STRING"}, {"name": "INVOICE_ITEM", "data_type": "STRING"},
                {"name": "CUST_NAME", "data_type": "STRING"}, {"name": "QUANTITY", "data_type": "DECIMAL"}],
    "known_lineage": [{"direction": "upstream", "other": "table:ICS Sales Warehouse:nexora.bronze.stg_ics_867",
                       "level": "TABLE"}],
}


# ── documents ──

def test_a_document_carries_meaning_columns_writers_and_lineage():
    doc = compose(CONTEXT, PROFILE)
    assert doc["trust_level"] == "profiled"          # a check failed
    assert doc["headline"] == "Silver ICS sales fact at invoice line level."
    text = doc["text"]
    for expected in ("fct ics 867", "Nexora PoC / ICS Sales", "grain: One row per invoice line item.",
                     "- INVOICE_ID (STRING): Invoice identifier", "- INVOICE_ITEM (STRING)",
                     "written by: ics_sales_ingestion", "lineage neighbours: nexora.bronze.stg_ics_867"):
        assert expected in text, expected
    assert doc["name"] == "nexora.silver.fct_ics_867"


def test_an_unprofiled_entity_is_still_indexed_from_platform_metadata():
    doc = compose({**CONTEXT, "attributes": {"comment": "Line level sales."}}, None)
    assert doc["trust_level"] == "synced"
    assert doc["headline"] == "Line level sales."
    assert "- QUANTITY (DECIMAL)" in doc["text"]


def test_the_document_hash_changes_only_with_content():
    assert compose(CONTEXT, PROFILE)["content_hash"] == compose(CONTEXT, PROFILE)["content_hash"]
    changed = {**PROFILE, "summary": "Something else."}
    assert compose(CONTEXT, changed)["content_hash"] != compose(CONTEXT, PROFILE)["content_hash"]


def test_trust_levels():
    assert trust_level(None) == "synced"
    assert trust_level({"verification": {"passed": True}}) == "verified"
    assert trust_level({"verification": {"passed": False}}) == "profiled"
    assert trust_level({}) == "profiled"


def test_text_helpers():
    assert name_words("nexora_poc.silver.fct_ics_867") == "nexora poc silver fct ics 867"
    assert first_sentence("One. Two.") == "One."
    assert first_sentence("") == ""
    assert first_sentence("x" * 500, limit=50).endswith("…")


# ── search ──

def test_rank_fusion_rewards_agreement_between_retrievers():
    merged = rrf_merge({"meaning": ["a", "b", "c"], "keywords": ["b", "d"], "names": ["b"]})
    assert merged[0]["entity_id"] == "b"
    assert merged[0]["matched_by"] == ["meaning", "keywords", "names"]
    assert {m["entity_id"] for m in merged} == {"a", "b", "c", "d"}


def test_rank_fusion_weights():
    merged = rrf_merge({"x": ["a"], "y": ["b"]}, {"x": 1.0, "y": 0.5})
    assert [m["entity_id"] for m in merged] == ["a", "b"]


def test_the_name_part_of_a_question():
    assert _name_query("what feeds fct_ics_867 in silver?") == "fct_ics_867"
    assert _name_query("account level sales") == "account level sales"


# ── joins ──

def test_join_keys_prefer_grain_keys_and_identifiers_and_warn_on_types():
    shared = [("ORG_VID", "STRING", "STRING"), ("INVOICE_ID", "STRING", "BIGINT"),
              ("created_at", "TIMESTAMP", "TIMESTAMP"), ("PRODUCT", "STRING", "STRING")]
    keys = score_shared(shared, grain_a={"org_vid"}, grain_b=set())
    assert [k["column"] for k in keys] == ["ORG_VID", "INVOICE_ID"]   # generic and non-key columns dropped
    assert "grain key" in keys[0]["why"]
    assert "cast before joining" in keys[1]["why"]


def test_key_like_names_and_type_families():
    assert is_key_like("HCO_ID") and is_key_like("ndc_code") and is_key_like("ORG_VID")
    assert not is_key_like("QUANTITY") and not is_key_like("created_at")
    assert type_family("VARCHAR(20)") == type_family("STRING") == "string"
    assert type_family("BIGINT") == type_family("INT") == "integer"


# ── cards ──

def test_key_columns_use_the_stated_grain_key_first():
    cols = [{"name": "INVOICE_ID", "tags": "id"}, {"name": "HCO_ID", "tags": ""}]
    assert key_columns(PROFILE, cols) == ["INVOICE_ID", "INVOICE_ITEM"]
    assert key_columns({}, cols) == ["INVOICE_ID", "HCO_ID"]


def test_example_sql_leads_with_keys_and_measures():
    cols = [{"name": "CUST_NAME", "tags": "pii"}, {"name": "QUANTITY", "tags": "measure"},
            {"name": "INVOICE_ID", "tags": "id"}]
    sql = example_sql("cat.silver.fct", cols, ["INVOICE_ID"])
    assert sql.startswith("SELECT INVOICE_ID, QUANTITY, CUST_NAME")
    assert "FROM `cat`.`silver`.`fct`" in sql


def test_caveats_surface_failed_checks_pii_staleness_and_reports():
    cols = [{"name": "CUST_NAME", "tags": "pii,customer"}, {"name": "QUANTITY", "tags": "measure"}]
    out = caveats(PROFILE, cols, stale=True,
                  feedback=[{"reporter": "bi-agent", "kind": "incorrect", "message": "grain is per invoice"}])
    joined = "\n".join(out)
    assert "Check 'grain' fails: 51 duplicate rows" in joined
    assert "personal data in 1 column(s): CUST_NAME" in joined
    assert "Re-profiling is due" in joined
    assert "Reported by bi-agent (incorrect): grain is per invoice" in joined
    assert caveats(None, [], False, [])[0].startswith("Not profiled yet")


# ── enrichment: versioned digest and link kinds ──

def test_the_profile_digest_ignores_volatile_context_and_tracks_the_pipeline_version(monkeypatch):
    base = {"entity_id": TABLE, "columns": [{"name": "A"}]}
    noisy = {**base, "parent_context": {"summary": "x"}, "recent_runs": [1], "change_events": [2]}
    assert profile_digest(base) == profile_digest(noisy)
    assert profile_digest(base) != profile_digest({**base, "columns": [{"name": "B"}]})
    from kairos_kb.enrichment import pipeline

    before = profile_digest(base)
    monkeypatch.setattr(pipeline, "PIPELINE_VERSION", PIPELINE_VERSION + "-next")
    assert profile_digest(base) != before


def test_link_kinds_are_checked_for_known_kinds_only():
    assert check_link_kinds("READS_TABLE", "task", "table") is None
    assert "cannot have a schema as its source" in check_link_kinds("READS_TABLE", "schema", "table")
    assert "cannot have a job as its target" in check_link_kinds("WRITES_TABLE", "task", "job")
    assert check_link_kinds("TRIGGERS", "table", "job") is not None
    assert check_link_kinds("READS_TABLE", "genie_space", "table") is None      # open vocabulary passes
    assert check_link_kinds("USES_EXTERNAL", "task", "external_connection") is None
    assert check_link_kinds("USES_EXTERNAL", "task", "table") is not None


# ── access ──

def test_keys_are_read_from_either_header():
    assert key_from_headers({"authorization": "Bearer kai_abc"}) == "kai_abc"
    assert key_from_headers({"x-kairos-key": "kai_def"}) == "kai_def"
    assert key_from_headers({}) is None


def test_workspace_scoping():
    scoped = AgentIdentity(agent_id=uuid.uuid4(), name="a", workspace_ids=frozenset({"x"}),
                           workspace_names=frozenset({"ICS Sales Warehouse"}))
    assert scoped.sees_entity(TABLE)
    assert not scoped.sees_entity("table:Other WS:c.s.t")
    assert AgentIdentity(agent_id=None, name="b").sees_entity("table:Other WS:c.s.t")


@pytest.fixture
def recorded(monkeypatch):
    calls = []

    async def fake_record(identity, tool, arguments, result, ok, error, duration_ms):
        calls.append({"agent": identity.name, "tool": tool, "ok": ok, "error": error})

    monkeypatch.setattr(access, "record_activity", fake_record)
    return calls


def test_audited_tools_enforce_scope_and_workspace_and_record_every_call(recorded):
    @audited()
    async def get_context(entity_id: str):
        return {"entity_id": entity_id}

    @audited("act")
    async def generate_rca(run_id: str):
        return {"ok": True}

    reader = AgentIdentity(agent_id=uuid.uuid4(), name="reader", scopes=frozenset({"read"}),
                           workspace_ids=frozenset({"x"}), workspace_names=frozenset({"ICS Sales Warehouse"}))
    token = access.set_current_agent(reader)
    try:
        assert asyncio.run(get_context(entity_id=TABLE)) == {"entity_id": TABLE}
        denied = asyncio.run(get_context(entity_id="table:Other WS:c.s.t"))
        assert "No such entity" in denied["error"]
        refused = asyncio.run(generate_rca(run_id="r"))
        assert "'act' scope" in refused["error"]
    finally:
        access._current.reset(token)
    assert [(c["tool"], c["ok"]) for c in recorded] == [
        ("get_context", True), ("get_context", False), ("generate_rca", False)]
    assert all(c["agent"] == "reader" for c in recorded)


# ── feedback ──

def test_feedback_brief_for_the_enrichment_agent():
    class F:
        def __init__(self, kind, message, field=None, suggestion=None):
            self.kind, self.message, self.field, self.suggestion = kind, message, field, suggestion

    brief = feedback_brief([F("incorrect", "grain is per invoice, not line", "grain", "one row per invoice")])
    assert "AGENT FEEDBACK" in brief
    assert "[incorrect] grain is per invoice, not line (field: grain). Suggested: one row per invoice" in brief
    assert feedback_brief([]) == ""


# ── cold-agent scoring ──

def test_mention_scoring_needs_one_phrase_per_group():
    groups = [["fct_ics_867"], ["invoice line", "line item"]]
    assert mention_score("Use fct_ics_867: one row per line item.", groups)["score"] == 1.0
    partial = mention_score("Use FCT_ICS_867.", groups)
    assert partial["score"] == 0.5 and partial["missing"] == ["invoice line | line item"]
    assert mention_score("anything", [])["score"] == 1.0


# ── key checks and passing results ──

def test_key_columns_parse_from_commas_or_plus():
    from kairos_kb.context.quality import parse_columns

    assert parse_columns("ORG_VID, INVOICE_ID + `INVOICE_ITEM`") == ["ORG_VID", "INVOICE_ID", "INVOICE_ITEM"]
    assert parse_columns("  ") == []


def test_a_grain_that_holds_is_not_a_caveat():
    profile = {"verification": {"passed": True, "checks": [
        {"check": "grain", "result": "holds", "detail": "unique across 10 rows"},
        {"check": "column_coverage", "result": "ok"},
    ]}}
    assert not [c for c in caveats(profile, [], False, []) if c.startswith("Check")]
