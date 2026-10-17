"""The companion's pacing math and clock: pure functions, no database or LLM."""

from datetime import date, datetime, timedelta

from kairos_kb.companion import pace as P
from kairos_kb.companion.pulse import infer_offset, moment_plain, plain_headline, show

# A Friday; history holds eight earlier Fridays with 100 orders an hour from 08:00 to 22:00.
TODAY = date(2026, 10, 9)


def history(rate=100.0, today_rate=None, until_hour=15, today=TODAY, weeks=8):
    h = {}
    for k in range(1, weeks + 1):
        d = today - timedelta(days=7 * k)
        for hr in range(8, 22):
            h[datetime(d.year, d.month, d.day, hr)] = rate * (1 + 0.01 * (k % 3))  # a little day-to-day noise
    if today_rate is not None:
        for hr in range(8, until_hour + 1):
            h[datetime(today.year, today.month, today.day, hr)] = today_rate * (0.5 if hr == until_hour else 1)
    return h


def test_baseline_days_prefers_same_weekday():
    have = [TODAY - timedelta(days=k) for k in range(1, 60)]
    days, basis = P.baseline_days(TODAY, have)
    assert all(d.weekday() == TODAY.weekday() for d in days) and len(days) == 8
    assert "Fridays" in basis


def test_baseline_days_falls_back_to_recent_days():
    days, basis = P.baseline_days(TODAY, [TODAY - timedelta(days=k) for k in range(1, 6)])
    assert len(days) == 5 and "days" in basis


def test_normal_day_is_normal():
    cut = datetime(2026, 10, 9, 15, 30)
    p = P.pace_additive(history(today_rate=101), TODAY, cut)
    assert abs(p["dev_pct"]) < 3
    assert P.judge(p, "up")["status"] == "normal"
    # Half of the 15:00 hour is done; the normal day is compared at the same minute.
    assert 700 < p["expected"] < 780


def test_a_slow_day_reads_below_and_bad():
    cut = datetime(2026, 10, 9, 15, 30)
    p = P.pace_additive(history(today_rate=70), TODAY, cut)
    v = P.judge(p, "up")
    assert v["status"] == "below" and v["valence"] == "bad" and p["dev_pct"] < -25
    # The projection scales today by the share of a normal day done by now.
    assert p["projection"] < p["expected_full"]


def test_a_rate_going_up_is_bad_when_lower_is_better():
    base = {TODAY - timedelta(days=7 * k): 0.08 + 0.001 * (k % 3) for k in range(1, 9)}
    p = P.pace_rate(0.14, base, {}, TODAY, datetime(2026, 10, 9, 15))
    v = P.judge(p, "down")
    assert v["status"] == "above" and v["valence"] == "bad"


def test_early_in_the_day_needs_more_evidence():
    cut = datetime(2026, 10, 9, 8, 20)  # under 8% of a normal day done
    p = P.pace_additive(history(today_rate=75, until_hour=8), TODAY, cut)
    assert p["share_done"] < 0.08
    assert P.judge(p, "up")["status"] in ("early", "below")


def test_not_enough_history_says_nothing():
    assert P.pace_additive(history(weeks=1), TODAY, datetime(2026, 10, 9, 12)) is None


def test_last_full_hour_is_measured():
    cut = datetime(2026, 10, 9, 15, 30)
    h = history(today_rate=100)
    h[datetime(2026, 10, 9, 14)] = 20.0  # a sharp break at 14:00
    p = P.pace_additive(h, TODAY, cut)
    assert p["hour"]["hour"] == 14 and p["hour"]["dev_pct"] < -70


def test_close_of_a_finished_day():
    h = history()
    for hr in range(8, 22):
        h[datetime(2026, 10, 9, hr)] = 120.0
    c = P.close_additive(h, TODAY)
    assert c["dev_pct"] > 15


def test_offset_inferred_from_a_live_stream():
    utc = datetime(2026, 10, 10, 7, 58, 40)
    assert infer_offset(datetime(2026, 10, 10, 13, 27, 1), utc) == 330    # IST, a few minutes behind
    assert infer_offset(datetime(2026, 10, 10, 7, 55, 0), utc) == 0       # UTC
    assert infer_offset(datetime(2020, 8, 1), utc) is None                # history, not a stream


def test_show_reads_units():
    assert show(0.0834, "ratio", "cancel_rate") == "8.3%"
    assert show(31.24, "", "avg_delivery_time_min") == "31.2 min"
    assert show(15520, "count", "orders") == "15.5k"


def test_plain_words_for_a_moment_and_the_headline():
    v = {"label": "Orders", "metric": "orders", "unit": "count"}
    f = {"signal": "pace_below", "direction": "down", "valence": "bad", "local_time": "15:30", "where": [
        {"dimension": "city", "top": [{"slice": "Bangalore", "delta_display": "−310", "share_of_gap_pct": 55.0}]}],
        "pace": {"actual_display": "5.2k", "expected_display": "6.9k", "low_display": "6.7k", "high_display": "7.1k",
                 "basis": "the last 8 Fridays", "dev_pct": -24.6, "projection_display": "11.7k", "expected_full_display": "15.5k"}}
    title, body = moment_plain(v, f, "Friday")
    assert "24.6% below a normal Friday" in title and "Bangalore" in body and "wrong direction" in body
    snap = {"local_time": "15:30", "vitals": [{"label": "Orders", "status": "below", "valence": "bad", "dev_pct": -24.6,
                                               "additive": True, "actual_display": "5.2k"}]}
    assert plain_headline(snap, "Friday").startswith("Orders is 24.6% below a normal Friday")


def test_fragments_never_reach_the_screen():
    from kairos_kb.companion.pulse import sane

    assert not sane(":{")
    assert not sane("{}")
    assert not sane("")
    assert not sane('{"headline": ')
    assert sane("A normal Saturday so far: 7,017 delivered orders by 14:09, on pace for 19.3k.")


def test_a_repeated_question_is_recognised_but_a_different_one_is_not():
    from kairos_kb.companion.chat import same_question

    assert same_question("How are delivered orders doing today?", "how are delivered orders going today")
    assert same_question("Hey Jenny, how is GMV doing today?", "what about GMV today?")
    assert not same_question("How are delivered orders doing today?", "How are delivered orders doing yesterday?")
    assert not same_question("cancellations in Patna today", "cancellations in Pune today")
    assert not same_question("How is GMV doing today?", "How are delivered orders doing today?")


def test_the_first_minutes_after_midnight_are_never_judged():
    p = {"kind": "additive", "share_done": 0.003, "z": 9.0, "dev_pct": 47.0}
    assert P.judge(p, "up")["status"] == "early"


def test_any_hour_of_today_against_the_same_hour_on_normal_days():
    today = date(2026, 10, 11)  # a Sunday
    hourly = {}
    for k in range(1, 9):  # the last eight Sundays: 100 orders at 5 a.m., 300 at noon
        d = datetime(2026, 10, 11) - timedelta(days=7 * k)
        hourly[d.replace(hour=5)] = 100.0
        hourly[d.replace(hour=12)] = 300.0
    hourly[datetime(2026, 10, 11, 5)] = 18.0  # the outage
    hourly[datetime(2026, 10, 11, 12)] = 150.0  # noon, half an hour in
    hv = P.hours_vs_normal(hourly, today, datetime(2026, 10, 11, 12, 30), [5, 12, 18])
    five, noon = hv["hours"]
    assert five["hour"] == 5 and five["actual"] == 18 and five["expected"] == 100 and five["gap"] == -82
    assert noon["partial"] and noon["expected"] == 150  # compared with the same half of a usual noon hour
    assert "18" in hv["not_yet"]


async def test_a_line_is_said_once_without_a_read(monkeypatch):
    from kairos_kb.companion import brain

    async def no_jev(state, qs):
        return None

    monkeypatch.setattr(brain, "_one", no_jev)
    assert (await brain.narrate("q", [], "Let me pull it.", ""))["say"]  # the first plan
    assert not (await brain.narrate("q", ["Let me pull it."], "I'll fetch it.", "worked: query"))["say"]
    assert (await brain.narrate("q", ["Let me pull it."], "That didn't work — trying by hour.", "failed: no such"))["say"]


async def test_jev_drops_a_restated_plan(monkeypatch):
    from kairos_kb.companion import brain

    async def jev(state, qs):
        return {"line_kind": {"choice": "restating", "confidence": 0.9}, "new_to_owner": 0.2}

    monkeypatch.setattr(brain, "_one", jev)
    assert not (await brain.narrate("q", ["Let me pull the five a.m. GMV."], "I'll fetch GMV for five a.m.", "worked: q"))["say"]


async def test_a_slip_she_is_fixing_is_not_said(monkeypatch):
    from kairos_kb.companion import brain

    async def jev(state, qs):
        return {"line_kind": {"choice": "change_of_route", "confidence": 0.9}, "new_to_owner": 0.7, "owner_cares": 0.2}

    monkeypatch.setattr(brain, "_one", jev)
    assert not (await brain.narrate("q", ["Let me pull it."], "The metric label failed; retrying.", "failed: no metric"))["say"]
