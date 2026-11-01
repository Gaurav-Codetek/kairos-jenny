"""A profile a model wrote loosely (grain as an object, a meaning as a list) still reads as text in the engine.

On the hosted app, a connection enriched with Nemotron had a grain stored as an object; the engine's brief sliced it
and every run failed with "unhashable type: 'slice'".
"""

from kairos_kb.products.bundle import _text
from kairos_kb.products.engine import plan_brief


def test_loose_values_read_as_text():
    assert _text(None) is None and _text("one row per order") == "one row per order"
    assert _text({"description": "one row per order", "keys": ["order_id"]}) == "one row per order"
    assert _text({"keys": ["order_id", "line"], "unit": "line"}) == "keys: order_id, line; unit: line"
    assert _text(["a", None, "b"]) == "a, b" and _text(3) == "3"


def test_the_brief_builds_from_text_fields():
    t = {"f": {"full_name": "c.s.fct_orders", "grain": _text({"description": "one row per order"}), "columns": []},
         "m": {"full_name": "c.s.mart_daily", "grain": None, "columns": []}}
    flow = {"tables": t, "facts": [{"table": "f", "feeds": ["m"], "dimensions": []}],
            "marts": [{"table": "m", "built_from": ["f"], "dimensions": []}], "dimensions": [], "other": [],
            "operational": []}
    assert "grain: one row per order" in plan_brief(flow, [])
