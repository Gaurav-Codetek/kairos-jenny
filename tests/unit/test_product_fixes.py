"""The report loop's own logic: merging an addition, reaching it, describing it, taking it back, triage fallbacks."""

import pytest

from kairos_kb.models.context import ContextFeedback
from kairos_kb.models.data_product import DataProduct
from kairos_kb.products import fixes

SALES = {
    "dimensions": [
        {"name": "city", "type": "categorical", "table": "Z.MARTS.FCT_ORDERS", "column": "CITY", "joins": []},
        {"name": "restaurant", "type": "categorical", "table": "Z.MARTS.DIM_RESTAURANTS", "column": "RESTAURANT_ID",
         "joins": [{"from_table": "Z.MARTS.FCT_ORDERS", "from_column": "RESTAURANT_ID", "to_column": "RESTAURANT_ID"}]},
    ],
    "metrics": [{"name": "gmv", "base_table": "Z.MARTS.FCT_ORDERS", "expression": "SUM(f.SALES_AMOUNT)", "additive": True}],
}
NAME = {"name": "restaurant_name", "label": "Restaurant name", "type": "categorical", "table": "Z.MARTS.DIM_RESTAURANTS",
        "column": "RESTAURANT_NAME", "entity_id": "table:Z:Z.MARTS.DIM_RESTAURANTS",
        "joins": [{"from_table": "Z.MARTS.FCT_ORDERS", "from_column": "RESTAURANT_ID", "to_column": "RESTAURANT_ID"}]}
UNREACHABLE = {"name": "cuisine", "label": "Cuisine", "type": "categorical", "table": "Z.MARTS.DIM_MENU",
               "column": "CUISINE", "joins": []}


def product():
    return DataProduct(name="Sales", slug="sales", spec={"model": SALES, "inputs": []}, seeds=[])


def test_an_addition_joins_the_model_without_touching_what_is_there():
    merged = fixes.merge(SALES, [NAME], [])
    assert [d["name"] for d in merged["dimensions"]] == ["city", "restaurant", "restaurant_name"]
    assert len(SALES["dimensions"]) == 2  # the original is untouched


def test_a_new_dimension_must_be_reachable_by_a_metric():
    merged = fixes.merge(SALES, [NAME, UNREACHABLE], [])
    assert fixes.reaching_metric(merged, "restaurant_name") == "gmv"
    assert fixes.reaching_metric(merged, "cuisine") is None  # no join from the orders table


def test_a_proposal_is_described_in_words_a_person_can_check():
    adds = fixes.describe({"dimensions": [NAME], "metrics": []})
    assert adds == [{"kind": "dimension", "name": "restaurant_name", "label": "Restaurant name",
                     "definition": "Z.MARTS.DIM_RESTAURANTS.RESTAURANT_NAME (joined on FCT_ORDERS.RESTAURANT_ID = RESTAURANT_ID)"}]


def test_applying_records_a_revision_and_taking_back_removes_only_the_addition():
    p = product()
    f = ContextFeedback(entity_id="product:Z:sales", kind="missing", message="no restaurant names", reporter="Jenny")
    fixes.apply(p, {"dimensions": [NAME], "metrics": [], "new_inputs": []}, f)
    assert "restaurant_name" in [d["name"] for d in p.spec["model"]["dimensions"]]
    assert p.spec["revisions"][-1]["added"] == ["restaurant_name"]
    fixes.take_back(p, ["restaurant_name"])
    assert [d["name"] for d in p.spec["model"]["dimensions"]] == ["city", "restaurant"]


@pytest.mark.parametrize("kind,category", [("missing", "product_change"), ("stale", "data_issue"),
                                           ("incorrect", "description"), ("confusing", "description")])
async def test_without_a_read_the_kind_of_report_decides(monkeypatch, kind, category):
    async def no_jev(state, questions):
        return None

    monkeypatch.setattr(fixes, "_jev", no_jev)
    f = ContextFeedback(entity_id="product:Z:sales", kind=kind, message="something", reporter="Jenny")
    assert (await fixes.triage(f, product()))["category"] == category


async def test_jev_reads_what_would_fix_a_report(monkeypatch):
    async def jev(state, questions):
        assert state["report"] == "zero orders between 5 and 6 a.m."
        return {"category": {"choice": "data_issue", "confidence": 0.93}}

    monkeypatch.setattr(fixes, "_jev", jev)
    f = ContextFeedback(entity_id="product:Z:sales", kind="missing", message="zero orders between 5 and 6 a.m.",
                        reporter="Jenny")
    assert (await fixes.triage(f, product()))["category"] == "data_issue"


def test_a_failed_lookup_with_numbers_back_counts_as_data_arriving():
    assert fixes._numbers([["Pune", "0"], ["Delhi", "12"]]) == [0.0, 12.0]


async def test_an_addition_that_does_not_answer_the_report_waits_for_a_person(monkeypatch):
    async def jev(state, questions):
        assert "proposed_additions" in state
        return {"answers": 0.2}

    monkeypatch.setattr(fixes, "_jev", jev)
    f = ContextFeedback(entity_id="product:Z:sales", kind="missing", message="need units_cancelled", reporter="Jenny")
    assert await fixes.answers(f, [{"kind": "dimension", "name": "event_time", "definition": "ORDER_TS"}]) == 0.2


def test_guidance_is_added_and_taken_back_like_any_addition():
    p = product()
    f = ContextFeedback(entity_id="product:Z:sales", kind="confusing", message="GMV meaning unclear", reporter="Jenny")
    fix = {"caveats": ["GMV counts delivered orders only."], "agent_guidance": [], "glossary": [{"term": "GMV", "meaning": "delivered sales"}]}
    fixes.apply(p, fix, f)
    assert p.spec["model"]["caveats"] == ["GMV counts delivered orders only."]
    assert [x["kind"] for x in fixes.describe(fix)] == ["caveat", "term"]
    fixes.take_back(p, ["GMV counts delivered orders only.", "GMV"])
    assert p.spec["model"]["caveats"] == [] and p.spec["model"]["glossary"] == []
