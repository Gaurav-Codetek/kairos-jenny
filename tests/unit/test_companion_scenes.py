"""Jenny's stage: scenes are built only from a lookup's own numbers, and know how their parts are said aloud."""

from kairos_kb.companion import scenes

RATE_BY_CITY = {  # compare_to_normal(cancel_rate, dimension=city), as the tool returns it (raw rows under _where)
    "product": "Sales", "metric": "cancel_rate", "label": "Cancellation rate", "as_of": "15:18", "kind": "rate",
    "actual": 0.0648, "expected": 0.0616, "low": 0.0582, "high": 0.0652, "basis": "the last 8 Mondays",
    "actual_display": "6.5%", "expected_display": "6.2%",
    "_where": [{"dimension": "city", "top": [
        {"slice": "Chennai", "today_display": "8.5%", "usual_display": "6.8%", "change_pct": 25.5,
         "volume_display": "484 orders", "extra_display": "+8 vs its usual rate", "_today": 0.085, "_usual": 0.068,
         "_volume": 484},
        {"slice": "Noida-1", "today_display": "13.0%", "usual_display": "6.8%", "change_pct": 91.6,
         "volume_display": "54 orders", "_today": 0.13, "_usual": 0.068, "_volume": 54},
        {"slice": "Surat", "today_display": "4.2%", "usual_display": "9.9%", "change_pct": -58.0,
         "volume_display": "48 orders", "_today": 0.042, "_usual": 0.099, "_volume": 48}]}],
}
ORDERS_HOURS = {
    "product": "Sales", "metric": "orders", "label": "Orders", "kind": "additive", "actual": 5909.0,
    "by_hour": {"basis": "the last 8 Mondays", "hours": [
        {"hour": 9, "actual": 392.0, "expected": 390.5, "low": 386.0, "high": 395.0, "actual_display": "392",
         "expected_display": "390", "gap_display": "+2", "partial": False},
        {"hour": 15, "actual": 120.0, "expected": 130.0, "low": 110.0, "high": 140.0, "actual_display": "120",
         "expected_display": "130", "gap_display": "−10", "partial": True}]},
}
ORDERS_TODAY = {
    "product": "Sales", "metric": "orders", "label": "Orders", "kind": "additive", "actual": 5909.0,
    "expected": 5764.2, "low": 5643.0, "high": 5877.5, "dev_pct": 2.5, "basis": "the last 8 Mondays",
    "actual_display": "5,909", "expected_display": "5,764", "as_of": "15:18",
    "_curve": {"typical": [[0, 0, 0, 0], [1, 18, 15, 21], [2, 31, 27, 35]], "today": [[0, 0], [1, 19], [1.5, 26]]},
}


def lookup(result, tool="compare_to_normal", lid="L1"):
    return {"id": lid, "tool": tool, "args": {}, "result": result}


def test_a_breakdown_carries_the_lookups_own_numbers():
    s, err = scenes.build("breakdown", lookup(RATE_BY_CITY))
    assert err is None and s["kind"] == "breakdown" and s["title"] == "Cancellation rate by city"
    chennai = s["data"]["rows"][0]
    assert (chennai["label"], chennai["value"], chennai["usual"], chennai["display"]) == ("Chennai", 0.085, 0.068, "8.5%")
    assert [r["low_volume"] for r in s["data"]["rows"]] == [False, False, True]  # 48 orders is noise
    assert s["source"]["lookup_id"] == "L1"


def test_slices_are_known_by_how_theyre_said():
    s, _ = scenes.build("breakdown", lookup(RATE_BY_CITY))
    noida = next(e for e in s["entities"] if e["key"] == "Noida-1")
    assert "Noida" in noida["aliases"]


def test_focus_lights_up_named_slices_and_refuses_unknown_ones():
    s, _ = scenes.build("breakdown", lookup(RATE_BY_CITY))
    assert scenes.focus(s, ["chennai", "Noida"], "+8 vs usual") is None
    assert s["focus"] == ["Chennai", "Noida-1"] and s["annotations"][0] == {"key": "Chennai", "text": "+8 vs usual"}
    err = scenes.focus(s, ["Patna"], None)
    assert "isn't in that chart" in err and "Chennai" in err


def test_hours_are_known_by_how_theyre_said():
    s, err = scenes.build("hours", lookup(ORDERS_HOURS))
    assert err is None and [r["key"] for r in s["data"]["rows"]] == ["h9", "h15"]
    nine = next(e for e in s["entities"] if e["key"] == "h9")
    assert {"9 am", "nine a.m.", "09:00"} <= set(nine["aliases"])
    assert "three p.m." in next(e for e in s["entities"] if e["key"] == "h15")["aliases"]


def test_a_trend_needs_the_curve_and_a_number_needs_a_figure():
    t, err = scenes.build("trend", lookup(ORDERS_TODAY))
    assert err is None and t["data"]["cumulative"] and len(t["data"]["typical"]) == 3
    n, err = scenes.build("number", lookup(ORDERS_TODAY))
    assert err is None and n["data"]["display"] == "5,909" and n["data"]["status"] == "above"
    _, err = scenes.build("trend", lookup(RATE_BY_CITY))
    assert "curve" in err


def test_nothing_is_drawn_from_a_failed_lookup_or_the_wrong_kind():
    assert "failed" in scenes.build("breakdown", lookup({"error": "not live"}))[1]
    assert scenes.build("breakdown", lookup(ORDERS_TODAY))[1]  # no breakdown in it
    assert scenes.build("pie", lookup(ORDERS_TODAY))[1].startswith("Unknown scene")


def test_a_query_by_hour_becomes_hours_of_the_latest_day():
    q = {"columns": [{"name": "EVENT_TIME"}, {"name": "ORDERS"}],
         "rows": [["2026-10-11T09:00:00", "300"], ["2026-10-12T09:00:00", "392"], ["2026-10-12T10:00:00", "414"]]}
    s, err = scenes.build("hours", lookup(q, tool="query"))
    assert err is None and [(r["hour"], r["value"]) for r in s["data"]["rows"]] == [(9, 392.0), (10, 414.0)]


def test_two_figures_side_by_side():
    s, err = scenes.compare(lookup(ORDERS_TODAY, lid="L1"), lookup({**ORDERS_TODAY, "label": "GMV",
                                                                     "actual_display": "₹9.1L"}, lid="L2"))
    assert err is None and [i["display"] for i in s["data"]["items"]] == ["5,909", "₹9.1L"]


def test_the_model_never_sees_private_numbers():
    pub = scenes.public(RATE_BY_CITY)
    assert "_where" not in pub and pub["actual_display"] == "6.5%"
    assert scenes.public({"rows": [{"a": 1, "_b": 2}]}) == {"rows": [{"a": 1}]}


def test_a_lookup_knows_the_picture_it_makes():
    assert scenes.auto_kind("compare_to_normal", RATE_BY_CITY) == "breakdown"
    assert scenes.auto_kind("compare_to_normal", ORDERS_HOURS) == "hours"
    assert scenes.auto_kind("compare_to_normal", ORDERS_TODAY) == "trend"
    assert scenes.auto_kind("query", {"columns": [{}, {}], "rows": [["Pune", "3"], ["Delhi", "4"]]}) == "breakdown"
    assert scenes.auto_kind("pulse_now", {"vitals": []}) is None
    assert scenes.auto_kind("compare_to_normal", {"error": "x"}) is None


def test_a_note_goes_on_what_it_names():
    s, _ = scenes.build("hours", lookup(ORDERS_HOURS))
    scenes.focus(s, ["9 am", "3 pm"], "+10 short at 15:00")
    assert s["annotations"][0]["key"] == "h15"


def test_a_wider_query_bars_what_she_sorted_by():
    q = {"columns": [{"name": "RESTAURANT_NAME"}, {"name": "DELIVERED_ORDERS"}, {"name": "CANCELLATIONS"}],
         "rows": [["Cream Stone", "4", "3"], ["Oven Story", "0", "3"]]}
    lk = {"id": "L1", "tool": "query", "args": {"order": "cancellations desc"}, "result": q}
    s, err = scenes.build("breakdown", lk)
    assert err is None and s["title"] == "Cancellations by restaurant name"
    assert [(r["label"], r["value"], r["extra_display"]) for r in s["data"]["rows"]] == [
        ("Cream Stone", 3.0, "4 delivered orders"), ("Oven Story", 3.0, "0 delivered orders")]
    assert scenes.auto_kind("query", q) == "breakdown"


def test_two_slices_with_the_same_name_stay_two():
    q = {"columns": [{"name": "RESTAURANT_NAME"}, {"name": "CANCELLATIONS"}],
         "rows": [["Oven Story Pizza", "3"], ["Oven Story Pizza", "2"], ["Cream Stone", "1"]]}
    s, _ = scenes.build("breakdown", {"id": "L1", "tool": "query", "args": {}, "result": q})
    assert [r["key"] for r in s["data"]["rows"]] == ["Oven Story Pizza", "Oven Story Pizza #2", "Cream Stone"]


# ── the form follows the question ──

def q(cols, rows):
    return {"columns": [{"name": c} for c in cols], "rows": rows}


DAYS_BY_CUISINE = q(["EVENT_TIME", "CUISINE", "DELIVERED_ORDERS"], [
    ["2026-10-11T00:00:00", "North Indian", "524"], ["2026-10-11T00:00:00", "South Indian", "455"],
    ["2026-10-12T00:00:00", "North Indian", "387"], ["2026-10-12T00:00:00", "South Indian", "346"],
    ["2026-10-13T00:00:00", "North Indian", "341"], ["2026-10-13T00:00:00", "South Indian", "338"]])
HOURS_OVER_DAYS = q(["EVENT_TIME", "ORDERS"], [[f"2026-10-{d}T{h:02d}:00:00", str(10 * h + d)]
                                               for d in (10, 11) for h in range(5, 12) if not (d == 11 and h == 6)])
CITY_TWO_MEASURES = q(["CITY", "ORDERS", "CANCEL_RATE"], [["Chennai", "5500", "0.068"], ["Kochi", "384", "0.088"],
                                                         ["Delhi", "4200", "0.071"], ["Pune", "3000", "0.055"],
                                                         ["Surat", "48", "0.042"]])


def test_each_query_shape_gets_its_form():
    assert scenes.query_kind(DAYS_BY_CUISINE) == "series"
    assert scenes.query_kind(HOURS_OVER_DAYS) == "heatmap"
    assert scenes.query_kind(CITY_TWO_MEASURES) == "scatter"
    assert scenes.query_kind(q(["CITY", "ORDERS"], [["Pune", "3"], ["Delhi", "4"]])) == "breakdown"


def test_a_series_draws_a_line_per_category_and_knows_its_days():
    s, err = scenes.build("series", lookup(DAYS_BY_CUISINE, tool="query"))
    assert err is None and s["data"]["x_labels"] == ["Sun 11 Oct", "Mon 12 Oct", "Tue 13 Oct"]
    lines = s["data"]["panels"][0]["lines"]
    assert [ln["label"] for ln in lines] == ["North Indian", "South Indian"] and lines[0]["values"] == [524, 387, 341]
    sunday = next(e for e in s["entities"] if e["key"] == "x:2026-10-11")
    assert "Sunday" in sunday["aliases"]


def test_a_heatmap_shows_missing_hours_as_missing():
    s, err = scenes.build("heatmap", lookup(HOURS_OVER_DAYS, tool="query"))
    assert err is None and [r["label"] for r in s["data"]["rows"]] == ["Sat 10 Oct", "Sun 11 Oct"]
    sunday = s["data"]["cells"][1]
    assert sunday[1] is None                                   # 6 am on Sunday: nothing recorded
    assert s["data"]["cols"][0]["label"] == "5 am"


def test_a_scatter_puts_volume_across_and_the_rate_up():
    s, err = scenes.build("scatter", lookup(CITY_TWO_MEASURES, tool="query"))
    assert err is None and s["data"]["x_label"] == "orders" and s["data"]["y_label"] == "cancel rate"
    kochi = next(p for p in s["data"]["points"] if p["key"] == "Kochi")
    assert (kochi["x"], kochi["y"]) == (384, 0.088)


def test_deviation_and_share_from_a_breakdown():
    d, err = scenes.build("deviation", lookup(RATE_BY_CITY))
    assert err is None and d["data"]["rows"][0]["key"] == "Noida-1" and d["data"]["rows"][-1]["key"] == "Surat"
    _, err = scenes.build("share", lookup(RATE_BY_CITY))
    assert "rate doesn't add up" in err                        # a rate has no share of a whole
    sh, err = scenes.build("share", lookup(q(["CITY", "ORDERS"], [[c, str(v)] for c, v in
                                                                  [("Pune", 50), ("Delhi", 30), ("Goa", 10), ("Agra", 5),
                                                                   ("Kota", 3), ("Ooty", 2)]]), tool="query"))
    assert err is None and [p["key"] for p in sh["data"]["parts"]] == ["Pune", "Delhi", "Goa", "Agra", "Other"]
    assert round(sum(p["share"] for p in sh["data"]["parts"]), 6) == 1.0
