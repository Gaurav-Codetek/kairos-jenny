"""The living agent notices real changes, stays quiet on noise, respects seasons, and never invents numbers."""

from datetime import date

from kairos_kb.living import detect as D
from kairos_kb.living.agent import numbers_check, valence
from kairos_kb.living.watch import add_months, is_partial, parse_date


def months(values, start=date(2024, 1, 1)):
    return [(add_months(start, i), float(v)) for i, v in enumerate(values)]


def kinds(series, **kw):
    return {s.kind for s in D.detect(series, **kw)}


def test_a_flat_series_with_tiny_wiggles_raises_nothing():
    # Zomato's cancel rate: ~6%, moving in the third decimal.
    s = months([0.0594, 0.0601, 0.0598, 0.0603, 0.0596, 0.0600, 0.0599, 0.0605, 0.0597, 0.0602, 0.0601, 0.0599])
    assert D.detect(s) == []


def test_a_month_far_outside_its_normal_is_a_spike_with_its_size():
    s = months([44, 46, 45, 47, 44, 46, 45, 46, 44, 47, 45, 79])
    sig = next(x for x in D.detect(s) if x.kind == "spike")
    assert sig.direction == "up" and sig.impact_pct > 70 and sig.baseline == 45.0


def test_a_steady_climb_is_a_trend_with_its_streak():
    s = months([10, 10.2, 10.1, 10.3, 10.2, 10.4, 10.9, 11.4, 12.0, 12.7, 13.3, 14.1])
    sig = next(x for x in D.detect(s) if x.kind == "trend")
    assert sig.direction == "up" and sig.detail["streak"] >= 5 and sig.detail["p_value"] < 0.05


def test_a_move_to_a_new_level_is_a_shift_dated_from_when_it_began():
    s = months([100, 102, 99, 101, 100, 98, 101, 100, 99, 80, 81, 79, 80, 82])
    sig = next(x for x in D.detect(s) if x.kind == "shift")
    assert sig.direction == "down" and sig.detail["since"] == "2024-10-01"


def test_loss_turning_to_profit_is_a_crossing():
    s = months([-5, -4, -6, -3, -2, -1, 0.5])
    assert "crossing" in kinds(s)


def test_a_month_that_is_always_high_is_seasonal_not_news():
    year = [100, 98, 101, 99, 100, 102, 98, 101, 99, 100, 101, 140]   # December always high
    s = months(year + [v * 1.02 for v in year])
    assert not any(x.kind == "spike" for x in D.detect(s))


def test_a_person_saying_not_useful_asks_for_stronger_evidence():
    s = months([44, 46, 45, 47, 44, 46, 45, 46, 44, 47, 45, 52])   # +15%: notable at 1x
    assert "spike" in kinds(s)
    assert "spike" not in kinds(s, sensitivity=3.0)


def test_up_and_down_read_against_what_is_good_for_the_business():
    assert valence("up", "down") == "bad" and valence("down", "down") == "good" and valence("up", "neutral") == "neutral"


def test_a_month_the_data_does_not_yet_reach_is_partial():
    assert is_partial(date(2026, 6, 1), date(2026, 6, 14))
    assert not is_partial(date(2026, 6, 1), date(2026, 6, 30))
    assert parse_date("2025-11-01T00:00:00.000Z") == date(2025, 11, 1)


def test_numbers_the_llm_writes_must_be_in_the_facts():
    facts = {"signal": {"value": 719074.0, "baseline": 781438.0, "impact_pct": -7.98}}
    assert numbers_check("Claims were 719,074 in November, about 7.98% below the usual 781k.", facts)
    assert not numbers_check("Claims fell to 650,000 in November.", facts)


def test_a_negative_baseline_is_measured_against_the_series_typical_size_not_as_a_percent():
    # Average gap days: negative (overlapping fills) moving towards positive.
    s = months([-8, -7.5, -8.2, -7.9, -8.1, -7.7, -8.0, -7.8, -2, -1.5, -2.2, -1.8])
    sig = next(x for x in D.detect(s) if x.kind == "shift")
    assert sig.detail["scaled"] is True and sig.direction == "up"


def test_memory_recognises_the_same_shift_seen_from_a_later_month():
    from kairos_kb.living.agent import same_event
    from kairos_kb.models.living import AgentNote

    remembered = AgentNote(signal="shift", period=date(2025, 1, 1), facts={"signal": {"since": "2024-09-01"}})
    later = D.Signal("shift", date(2025, 4, 1), 760.0, 490.0, 55.0, 9.0, "up", {"since": "2024-10-01"})
    other = D.Signal("shift", date(2025, 4, 1), 760.0, 490.0, 55.0, 9.0, "up", {"since": "2025-03-01"})
    assert same_event(remembered, later) and not same_event(remembered, other)


def test_a_growing_series_does_not_announce_every_new_high():
    grow = months([100 + 3 * i for i in range(14)])   # a new high every month, by ~2%
    assert "record" not in kinds(grow)
    after_a_lull = months([100, 120, 101, 99, 100, 102, 98, 101, 99, 100, 101, 100, 99, 135])
    assert "record" in kinds(after_a_lull)
