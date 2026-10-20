"""Jenny's sense of the conversation, her desk, and the claim gate."""

import asyncio

from kairos_kb.companion import brain, claims, desk


def read(kind, mood="neutral", move=None, settled=0.0, said=0.0):
    r = {"turn_kind": {"choice": kind, "confidence": 0.9}, "emotion": {"choice": mood, "confidence": 0.9},
         "thread_settled": settled, "jenny_already_said": said}
    if move:
        r["move"] = {"choice": move, "confidence": 0.9}
    return r


def test_a_thank_you_once_its_agreed_gets_a_few_words_not_the_plan_again():
    assert brain.decide(read("small_talk", "impatient", "raise_something", settled=0.8))["move"] == "acknowledge"


def test_nothing_is_raised_in_reply_to_thanks():
    assert brain.decide(read("small_talk", move="raise_something"))["move"] == "acknowledge"


def test_an_open_question_still_gets_its_answer():
    assert brain.decide(read("question", move="answer_deep", settled=0.1))["move"] == "answer_deep"


def test_she_notices_opening_the_same_way():
    replies = ["[warm] Understood — I'll watch it.", "Understood — alerts are set.", "Understood — on it."]
    assert brain.openers(replies) == ["Understood", "Understood", "Understood"]
    note = brain.inner_note(read("small_talk", "pleased", settled=0.9, said=0.9), replies, ["watching cancellations above 8%"])
    assert "settled" in note and "repeating myself" in note and '"Understood"' in note
    assert "Already on my desk: watching cancellations above 8%" in note


def test_no_note_without_a_read():
    assert brain.inner_note(None, [], []) == ""


def test_sentences_are_cut_after_each_end():
    assert claims.sentences("Cancellations are up. I'll watch it. And") == ["Cancellations are up.", " I'll watch it.", " And"]
    assert claims.sentences("About 7.5 percent.") == ["About 7.5 percent."]


def test_backing_holds_duties_desk_and_lookups():
    b = claims.backing(["watching cancellations above 8%"], [{"tool": "compare_to_normal", "args": {"dimension": "zone"}}])
    assert any(x.startswith("standing duty:") for x in b)
    assert "on the desk: watching cancellations above 8%" in b
    assert "looked up this turn: compare_to_normal(dimension=zone)" in b


async def test_the_gate_holds_an_unbacked_promise_and_releases_in_order(monkeypatch):
    async def check(sentence, backing, context="", earlier=None, owner_said=""):
        await asyncio.sleep(0.01 if "email" in sentence else 0.03)  # checks finish out of order
        return {"ok": "email" not in sentence, "claim": "later" if "email" in sentence else None}

    async def repair(ws, sentence, check, said_before, backed_by, voice, origin=None):
        return " I can't email, but I'll raise it here when it trips."

    monkeypatch.setattr(brain, "check_claim", check)
    monkeypatch.setattr(claims, "repair", repair)
    seen = []

    async def released(text):
        seen.append(text)

    g = claims.Gate("ws", lambda: [], released, voice=True)
    g.feed("Cancellations are up. ")
    g.feed("Cancellations are up. I'll email you tonight. ")
    out = await g.finish("Cancellations are up. I'll email you tonight. Most is in two zones.")
    assert out == "Cancellations are up. I can't email, but I'll raise it here when it trips. Most is in two zones."
    assert all(out.startswith(x) for x in seen)  # what was released is always the start of what's said
    assert not any("email you" in x for x in seen)  # the promise never reached the owner


def test_a_watch_trips_on_the_right_side():
    spec = {"condition": "above", "threshold": 0.08}
    assert desk.crossed(spec, 0.081) and not desk.crossed(spec, 0.08) and not desk.crossed(spec, None)
    assert desk.crossed({"condition": "below", "threshold": -15}, -16.0)


def test_her_desk_tools_are_hers():
    assert desk.NAMES == {"keep_watch", "check_later", "desk", "drop_watch"}


# ── a watch is a running monitor ──

from datetime import datetime, timedelta, timezone  # noqa: E402


def watch_day(condition="above", threshold=0.08):
    return {"spec": {"condition": condition, "threshold": threshold}, **desk.new_day("2026-10-12")}


def feed(f, readings, start=datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc), gap_min=5):
    """readings: [(clock, value)] → the events of each, in order."""
    out = []
    for i, (clock, v) in enumerate(readings):
        out.append(desk.step(f, v, f"{v * 100:.1f}%", clock, start + timedelta(minutes=gap_min * i)))
    return out


def test_it_crosses_once_held_tells_and_keeps_watching_until_it_comes_back():
    f = watch_day()
    ev = feed(f, [("09:00", 0.07), ("09:05", 0.085), ("09:10", 0.09), ("09:15", 0.094), ("09:20", 0.07), ("09:25", 0.071)])
    assert ev == [[], [], ["cross"], [], [], ["back"]]
    assert f["state"] == "clear"
    ep = f["episodes"][0]
    assert (ep["from"], ep["to"], ep["peak_d"], ep["peak_at"], ep["told"]) == ("09:05", "09:20", "9.4%", "09:15", True)


def test_one_noisy_reading_isnt_a_crossing():
    f = watch_day()
    assert feed(f, [("09:00", 0.09), ("09:05", 0.07), ("09:10", 0.09), ("09:15", 0.07)]) == [[], [], [], []]
    assert f["episodes"] == []


def test_crossing_again_within_the_hour_is_noted_not_raised():
    f = watch_day()
    ev = feed(f, [("09:00", 0.09), ("09:05", 0.09), ("09:10", 0.07), ("09:15", 0.07), ("09:20", 0.09), ("09:25", 0.09)])
    assert ev[1] == ["cross"] and ev[3] == ["back"] and ev[5] == ["cross_quiet"]
    assert [e["told"] for e in f["episodes"]] == [True, False]


def test_a_below_watch_tracks_its_lowest():
    f = watch_day("below", -15)
    feed(f, [("10:00", -16), ("10:05", -20), ("10:10", -18)])
    assert f["episodes"][0]["peak"] == -20


def test_the_day_is_summed_up():
    f = watch_day()
    feed(f, [("09:00", 0.07), ("09:05", 0.085), ("09:10", 0.09), ("10:20", 0.07), ("10:25", 0.071), ("23:55", 0.069)])
    text = desk.summarize(f, "cancellations above 8%", "Mon 12 Oct")
    assert text.startswith("cancellations above 8% — Mon 12 Oct: crossed 1 time (09:05–10:20)")
    assert "for about 1 h 15 min in all" in text and "peak 9.0% at 09:10" in text and text.endswith("closed at 6.9%.")
    quiet = watch_day()
    feed(quiet, [("09:00", 0.07), ("12:00", 0.079), ("18:00", 0.06)])
    assert "never crossed; closest was 7.9% at 12:00" in desk.summarize(quiet, "x", "Mon")


def test_over_the_line_at_midnight_carries_into_the_new_day():
    f = watch_day()
    feed(f, [("23:50", 0.09), ("23:55", 0.09)])
    nxt = desk.new_day("2026-10-13", f)
    assert nxt["state"] == "crossed" and nxt["episodes"][0]["from"] == "00:00" and nxt["episodes"][0]["told"]


def feed_n(f, readings, start=datetime(2026, 10, 17, 20, 0, tzinfo=timezone.utc), gap_min=5):
    """readings: [(clock, value, n)] — a rate with the orders it's taken over."""
    return [desk.step(f, v, f"{v * 100:.1f}%", clock, start + timedelta(minutes=gap_min * i), n)
            for i, (clock, v, n) in enumerate(readings)]


def test_a_rate_hovering_at_the_line_neither_crosses_nor_comes_back():
    # 17–18 Oct: "below 6.5%" alerted at 6.7% / 6.4% on ~125 orders, and Chennai "above 9%" at 9.2% then 9.0%.
    f = watch_day("below", 0.065)
    assert feed_n(f, [("03:00", 0.064, 125), ("03:05", 0.064, 130), ("03:10", 0.067, 140), ("03:15", 0.063, 2600),
                      ("03:20", 0.064, 2600)]) == [[], [], [], [], []]
    chennai = watch_day("above", 0.09)
    assert feed_n(chennai, [("10:58", 0.092, 189), ("11:03", 0.092, 190), ("11:13", 0.090, 192)]) == [[], [], []]
    assert f["episodes"] == [] and chennai["episodes"] == []


def test_a_real_excursion_on_a_rate_still_crosses_and_comes_back():
    f = watch_day("above", 0.09)
    ev = feed_n(f, [("12:00", 0.108, 600), ("12:05", 0.110, 620), ("13:00", 0.095, 700), ("15:00", 0.07, 900),
                    ("15:05", 0.068, 920)])
    assert ev == [[], ["cross"], [], [], ["back"]]


def test_a_rate_on_a_handful_of_orders_doesnt_move_the_watch_or_the_summary():
    f = watch_day("below", 0.065)
    assert feed_n(f, [("00:06", 0.0, 4), ("00:08", 0.0, 6), ("00:12", 0.182, 11)]) == [[], [], []]
    assert f["state"] == "clear" and all(r["thin"] for r in f["history"])
    feed_n(f, [("09:00", 0.07, 900), ("12:00", 0.068, 2000)])
    assert "closest was 6.8% at 12:00" in desk.summarize(f, "x", "Sat")


def test_the_count_behind_a_rate_is_its_denominator():
    model = {"metrics": [
        {"name": "orders", "additive": True, "unit": "count", "base_table": "T", "expression": "COUNT(f.order_id)"},
        {"name": "cancellations", "additive": True, "unit": "count", "base_table": "T",
         "expression": "COUNT_IF(f.order_status = 'Cancelled')"},
        {"name": "cancel_rate", "additive": False, "unit": "ratio", "base_table": "T",
         "expression": "DIV0(COUNT_IF(f.order_status = 'Cancelled'), COUNT(f.order_id))"},
        {"name": "aov", "additive": False, "unit": "currency", "base_table": "T",
         "expression": "DIV0(SUM(f.amount), COUNT_IF(f.is_delivered))"}]}
    by = {m["name"]: m for m in model["metrics"]}
    assert desk.volume_metric(model, by["cancel_rate"]) == "orders"
    assert desk.volume_metric(model, by["aov"]) is None and desk.volume_metric(model, by["orders"]) is None


# ── offers: Yes / No when she ends by asking to do something ──

async def test_only_a_closing_question_can_be_an_offer(monkeypatch):
    asked = []

    async def jev(state, qs):
        asked.append(state["last_sentence"])
        return {"offers": 0.9 if state["last_sentence"].startswith("Shall I") else 0.1}

    monkeypatch.setattr(brain, "_one", jev)
    assert await brain.offer("[warm] Orders were low. Shall I pull a breakdown by city?") == "Shall I pull a breakdown by city?"
    assert await brain.offer("Orders were low. What would you like to look at?") is None
    assert await brain.offer("Orders were low. I'm watching it.") is None  # no question: Jev isn't even asked
    assert asked == ["Shall I pull a breakdown by city?", "What would you like to look at?"]
