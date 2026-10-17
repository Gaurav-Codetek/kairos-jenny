"""Data products: lanes come from the classification and the flow; the semantic model is kept only
where the map supports it; the query port picks a mart when it can and the base table otherwise."""

import pytest

from kairos_kb.products.bundle import assign_lanes, lane_from_classification
from kairos_kb.products.contracts import health
from kairos_kb.products.designer import Dimension, Join, Location, Metric, SemanticModel, Shortcut, Tool, validate_model
from kairos_kb.products.semantic import QueryError, columns_used, compile_query
from kairos_kb.products.service import slugify

RAW, STG, FCT, MART = "table:Z:DB.RAW.ORDERS", "table:Z:DB.STG.STG_ORDERS", "table:Z:DB.MARTS.FCT_ORDERS", \
    "table:Z:DB.MARTS.MART_CITY"


def test_the_layer_decides_the_lane_and_the_role_only_splits_marts_from_core():
    assert lane_from_classification("FACT_EVENT", "RAW_LANDING") == "raw"
    assert lane_from_classification("FACT_EVENT", "BRONZE_STAGING") == "staging"
    assert lane_from_classification("FACT_EVENT", "GOLD_SERVING") == "core"
    assert lane_from_classification("AGGREGATE_MART", "GOLD_SERVING") == "mart"
    assert lane_from_classification("FACT_EVENT", "OTHER") is None
    assert lane_from_classification("FACT_EVENT", "OTHER", by_role=True) == "core"


def test_an_unplaced_table_is_placed_by_the_flow():
    upstream = {RAW: set(), STG: {RAW}, FCT: {STG}, MART: {FCT}}
    lanes = assign_lanes([RAW, STG, FCT, MART], {}, upstream, {MART: "AGGREGATE_MART"})
    assert lanes == {RAW: "raw", STG: "staging", FCT: "core", MART: "mart"}


# ── the query port ──

MODEL = {
    "metrics": [
        {"name": "gmv", "base_table": "DB.MARTS.FCT_ORDERS", "expression": "SUM(IFF(f.is_delivered, f.amount, 0))",
         "additive": True, "shortcuts": [{"table": "DB.MARTS.MART_CITY", "column": "GMV", "rollup": "sum"}]},
        {"name": "aov", "base_table": "DB.MARTS.FCT_ORDERS",
         "expression": "SUM(f.amount) / NULLIF(COUNT(*), 0)", "additive": False,
         "shortcuts": [{"table": "DB.MARTS.MART_CITY", "column": "AOV", "rollup": "none"}]},
        {"name": "rating", "base_table": "DB.MARTS.FCT_RATINGS", "expression": "AVG(f.stars)", "additive": False,
         "shortcuts": []},
    ],
    "dimensions": [
        {"name": "city", "type": "categorical", "table": "DB.MARTS.FCT_ORDERS", "column": "CITY",
         "also_in": [{"table": "DB.MARTS.MART_CITY", "column": "CITY"}], "joins": []},
        {"name": "order_date", "type": "time", "table": "DB.MARTS.FCT_ORDERS", "column": "ORDER_DATE",
         "also_in": [{"table": "DB.MARTS.MART_CITY", "column": "ORDER_DATE"}], "joins": []},
        {"name": "cuisine", "type": "categorical", "table": "DB.MARTS.DIM_REST", "column": "CUISINE",
         "also_in": [], "joins": [{"from_table": "DB.MARTS.FCT_ORDERS", "from_column": "REST_ID", "to_column": "ID"}]},
    ],
}


def test_an_additive_metric_rolls_up_from_the_mart_even_to_a_coarser_time_grain():
    q = compile_query(MODEL, ["gmv"], ["city", "order_date:month"], [{"dimension": "city", "op": "=", "value": "Delhi"}])
    assert q["source"] == "shortcut" and q["table"] == "DB.MARTS.MART_CITY"
    assert "SUM(t.GMV) AS gmv" in q["sql"] and "DATE_TRUNC('MONTH', t.ORDER_DATE)" in q["sql"]
    assert "WHERE t.CITY = 'Delhi'" in q["sql"]


def test_a_ratio_is_read_from_the_mart_only_at_its_own_grain_and_recomputed_otherwise():
    own = compile_query(MODEL, ["aov"], ["city", "order_date"])
    assert own["source"] == "shortcut" and "GROUP BY" not in own["sql"] and "t.AOV AS aov" in own["sql"]
    coarse = compile_query(MODEL, ["aov"], ["city"])
    assert coarse["source"] == "base" and "SUM(f.amount) / NULLIF(COUNT(*), 0) AS aov" in coarse["sql"]


def test_a_dimension_off_the_mart_forces_the_base_table_with_its_join():
    q = compile_query(MODEL, ["gmv"], ["cuisine"], order="gmv desc")
    assert q["source"] == "base"
    assert "LEFT JOIN DB.MARTS.DIM_REST d1 ON f.REST_ID = d1.ID" in q["sql"]
    assert q["sql"].endswith("ORDER BY gmv DESC")


def test_requests_the_model_cannot_answer_say_why():
    with pytest.raises(QueryError, match="No metric 'margin'"):
        compile_query(MODEL, ["margin"])
    with pytest.raises(QueryError, match="different base tables"):
        compile_query(MODEL, ["gmv", "rating"], ["city"])
    with pytest.raises(QueryError, match="not a time dimension"):
        compile_query(MODEL, ["gmv"], ["city:month"])
    with pytest.raises(QueryError, match="cannot be reached"):
        compile_query(MODEL, ["rating"], ["cuisine"])


def test_filter_values_are_quoted_safely():
    q = compile_query(MODEL, ["gmv"], ["city"], [{"dimension": "city", "op": "in", "value": ["O'Hare", "Pune"]}])
    assert "IN ('O''Hare', 'Pune')" in q["sql"]


def test_the_schema_contract_lists_every_column_the_model_depends_on():
    used = columns_used(MODEL)
    assert used["DB.MARTS.FCT_ORDERS"] >= {"IS_DELIVERED", "AMOUNT", "CITY", "ORDER_DATE", "REST_ID"}
    assert used["DB.MARTS.MART_CITY"] >= {"GMV", "AOV", "CITY"}
    assert used["DB.MARTS.DIM_REST"] == {"CUISINE", "ID"}


# ── the model, checked against the map ──

def _input(eid, full_name, cols):
    return {"entity_id": eid, "full_name": full_name, "name": full_name.split(".")[-1],
            "columns": [{"name": c, "type": "NUMBER", "tags": t} for c, t in cols]}


INPUTS = [
    _input(FCT, "DB.MARTS.FCT_ORDERS", [("ORDER_ID", []), ("CITY", []), ("AMOUNT", []), ("IS_DELIVERED", []),
                                        ("CUSTOMER_EMAIL", ["personal_data"])]),
    _input(MART, "DB.MARTS.MART_CITY", [("CITY", []), ("GMV", [])]),
]


def test_the_model_keeps_only_what_the_map_supports():
    model = SemanticModel(
        description="d", purpose="p",
        dimensions=[
            Dimension(name="City", label="City", description="c", type="categorical", table="DB.MARTS.FCT_ORDERS",
                      column="city", also_in=[Location(table="MART_CITY", column="CITY")]),
            Dimension(name="email", label="Email", description="e", type="categorical", table="DB.MARTS.FCT_ORDERS",
                      column="CUSTOMER_EMAIL"),
            Dimension(name="region", label="Region", description="r", type="categorical", table="DB.MARTS.DIM_GEO",
                      column="REGION", joins=[Join(from_table="DB.MARTS.FCT_ORDERS", from_column="GEO_ID",
                                                   to_column="ID")]),
        ],
        metrics=[
            Metric(name="GMV", label="GMV", description="g", base_table="DB.MARTS.FCT_ORDERS",
                   expression="SUM(IFF(f.IS_DELIVERED, f.AMOUNT, 0))", additive=True,
                   shortcuts=[Shortcut(table="DB.MARTS.MART_CITY", column="GMV", rollup="sum")]),
            Metric(name="margin", label="Margin", description="m", base_table="DB.MARTS.FCT_ORDERS",
                   expression="SUM(f.MARGIN)", additive=True),
            Metric(name="sneaky", label="x", description="x", base_table="DB.MARTS.FCT_ORDERS",
                   expression="SUM(f.AMOUNT); DROP TABLE x", additive=True),
        ],
        tools=[Tool(name="GMV by city", description="t", metrics=["gmv"], by=["city"]),
               Tool(name="margin by city", description="t", metrics=["margin"], by=["city"])],
    )
    out, dropped = validate_model(model, INPUTS)
    assert [d["name"] for d in out["dimensions"]] == ["city"]
    assert out["dimensions"][0]["column"] == "CITY" and out["dimensions"][0]["also_in"][0]["table"] == "DB.MARTS.MART_CITY"
    assert [m["name"] for m in out["metrics"]] == ["gmv"]
    assert [t["name"] for t in out["tools"]] == ["gmv_by_city"]
    reasons = {d["item"]: d["reason"] for d in dropped}
    assert "personal data" in reasons["email"]
    assert "not a column of an input table" in reasons["region"]
    assert "no column MARGIN" in reasons["margin"]
    assert "read-only" in reasons["sneaky"]
    assert "No metric 'margin'" in reasons["margin by city"]


def test_health_is_broken_only_by_schema_or_metric_contracts():
    assert health([{"contract": "schema", "status": "ok"}])["status"] == "healthy"
    assert health([{"contract": "freshness", "status": "breached"}])["status"] == "degraded"
    assert health([{"contract": "schema", "status": "broken"}])["status"] == "broken"
    assert health([{"contract": "freshness", "status": "info"}])["status"] == "healthy"


def test_slugs():
    assert slugify("Delivery Performance / SLA") == "delivery-performance-sla"
    assert slugify("  ") == "product"


# ── the engine ──

from kairos_kb.products.engine import _measures, plan_brief, resolve_tables  # noqa: E402


def test_proposed_table_names_resolve_to_entities_by_full_or_unambiguous_short_name():
    tables = {"table:Z:DB.MARTS.FCT_ORDERS": {"full_name": "DB.MARTS.FCT_ORDERS"},
              "table:Z:DB.RAW.ORDERS": {"full_name": "DB.RAW.ORDERS"},
              "table:Z:DB.MARTS.ORDERS": {"full_name": "DB.MARTS.ORDERS"}}
    assert resolve_tables(["db.marts.fct_orders", "FCT_ORDERS", "ORDERS", "NOPE"], tables) == \
        ["table:Z:DB.MARTS.FCT_ORDERS"]


def test_measures_are_numeric_or_aggregated_columns_never_keys():
    t = {"columns": [{"name": "ORDER_ID", "type": "NUMBER"}, {"name": "CITY", "type": "VARCHAR"},
                     {"name": "GMV", "type": "NUMBER(38,0)", "meaning": "delivered sales"},
                     {"name": "CANCEL_RATE", "type": "VARCHAR", "aggregation": "ratio"}]}
    assert _measures(t) == "GMV — delivered sales; CANCEL_RATE"


def test_the_plan_brief_shows_the_flow_and_the_products_that_exist():
    flow = {"tables": {"f": {"full_name": "DB.M.FCT", "grain": "order", "columns": []},
                       "m": {"full_name": "DB.M.MART", "grain": "city-day", "columns": []},
                       "d": {"full_name": "DB.M.DIM", "columns": []}},
            "facts": [{"table": "f", "feeds": ["m"], "dimensions": ["d"]}],
            "marts": [{"table": "m", "built_from": ["f"], "dimensions": []}],
            "dimensions": ["d"], "operational": [], "other": []}
    brief = plan_brief(flow, ["Sales"])
    assert "feeds marts: MART" in brief and "joins dimensions: DIM" in brief and "built from: FCT" in brief
    assert "ALREADY EXIST" in brief and "Sales" in brief


# ── products in the map ──

from kairos_kb.context.documents import compose  # noqa: E402
from kairos_kb.warehouse.mesh import _flow  # noqa: E402


def test_a_product_reads_its_tables_so_the_mesh_draws_table_to_product():
    # product —READS_TABLE→ table: reversed into data-flow direction (table → product).
    assert _flow("READS_TABLE", "product", "table") == (True, "flow")


def test_a_product_document_is_searchable_by_its_metrics_and_trusted_once_confirmed():
    doc = {"entity_id": "product:Z:sales", "kind": "product", "name": "Sales", "full_name": "sales",
           "origin": "product",
           "attributes": {"status": "confirmed", "domain": "Commercial", "comment": "Orders and revenue by city.",
                          "metrics": [{"name": "gmv", "label": "GMV", "description": "delivered sales value"}],
                          "dimensions": [{"name": "city", "label": "City"}],
                          "glossary": [{"term": "AOV", "meaning": "average order value"}], "tools": ["gmv_by_city"]},
           "links": [{"direction": "out", "relation": "READS_TABLE", "entity_id": "table:Z:DB.M.FCT_ORDERS"}]}
    out = compose(doc, None)
    assert out["trust_level"] == "verified" and out["headline"] == "Orders and revenue by city."
    for expected in ("metric gmv: GMV — delivered sales value", "sliced by: City", "term AOV", "built from: DB.M.FCT_ORDERS"):
        assert expected in out["text"]
    doc["attributes"]["status"] = "draft"
    assert compose(doc, None)["trust_level"] == "profiled"
