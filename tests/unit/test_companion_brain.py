"""Jenny's brain: how a read of the turn becomes guidance — no Jev call, no LLM."""

from kairos_kb.companion import brain


def read(**kw):
    base = {"turn_kind": {"choice": "question", "confidence": 0.9}, "emotion": {"choice": "neutral", "confidence": 0.8},
            "move": {"choice": "answer_brief", "confidence": 0.8}, "tone": {"choice": "calm", "confidence": 0.8},
            "length": {"score": 1.0, "confidence": 0.7, "first_level": 0}, "needs_data": 0.8, "ambiguous": 0.1,
            "urgency": 0.1, "confused": 0.1}
    base.update(kw)
    return base


def test_no_read_means_no_guidance():
    assert brain.guidance(None, True) == ""


def test_a_confident_read_becomes_guidance():
    g = brain.guidance(read(), voice=True)
    assert "question" in g and "sentence or two" in g and "[thoughtful]" in g


def test_unconfident_choices_are_left_to_the_model():
    g = brain.guidance(read(move={"choice": "answer_deep", "confidence": 0.3}), voice=False)
    assert "fuller answer" not in g


def test_ambiguity_means_asking_back():
    g = brain.guidance(read(ambiguous=0.65), voice=False)
    assert "clarifying question" in g


def test_never_ask_back_at_someone_annoyed_or_just_corrected_or_twice_in_a_row():
    annoyed = brain.guidance(read(ambiguous=0.7, emotion={"choice": "frustrated", "confidence": 0.8}), voice=False)
    corrected = brain.guidance(read(ambiguous=0.8, turn_kind={"choice": "correction", "confidence": 0.95}), voice=False)
    twice = brain.guidance(read(ambiguous=0.7), voice=False, last_reply="Do you mean Pune or Patna?")
    for g in (annoyed, corrected, twice):
        assert "clarifying question" not in g and "which one you took" in g


def test_a_confident_goodbye_means_one_sentence_even_if_the_move_is_unsure():
    g = brain.guidance(read(turn_kind={"choice": "closing", "confidence": 0.95}, move={"choice": "wrap_up", "confidence": 0.4}), voice=False)
    assert "ONE sentence" in g


def test_frustration_is_met_first():
    g = brain.guidance(read(emotion={"choice": "frustrated", "confidence": 0.8}), voice=False)
    assert "Fair enough" in g and "once" in g


def test_no_offer_two_turns_running():
    assert brain.ended_with_offer("Pune has seven orders. If you like, I can pull its delivery times.")
    assert brain.ended_with_offer("All normal so far. Want a city breakdown?")
    assert not brain.ended_with_offer("All normal so far; nothing needs you.")
    g = brain.guidance(read(), voice=False, last_reply="Normal so far. Want me to break it down by city?")
    assert "end on a statement" in g


def test_quick_only_when_nothing_needs_looking_up():
    assert brain.quick(read(move={"choice": "small_talk", "confidence": 0.8}, needs_data=0.2))
    assert not brain.quick(read(move={"choice": "small_talk", "confidence": 0.8}, needs_data=0.7))
    assert not brain.quick(read(move={"choice": "answer_deep", "confidence": 0.8}, needs_data=0.1))


def test_a_request_jev_cant_place_is_still_answered_with_a_look():
    # Jenny's read of "okay up the tell me whether the field has started again or not" (17 Oct, a misheard "feed"):
    # no kind confident, "acknowledge" at .78, needs_data .15 — she answered "Let me pull…" with no tools at all.
    garbled = read(turn_kind={"choice": "question", "confidence": 0.17, "probabilities": {
                       "question": 0.27, "follow_up": 0.03, "reaction": 0.17, "correction": 0.0, "instruction": 0.22,
                       "small_talk": 0.05, "closing": 0.23, "unclear": 0.03}},
                   move={"choice": "acknowledge", "confidence": 0.75}, needs_data=0.15)
    assert brain.asks(garbled) >= brain.ASKS
    assert brain.decide(garbled)["move"] == "answer_brief"
    assert not brain.quick(garbled)
    # The thank-you that came just before it stays a quick, tool-free reply.
    thanks = read(turn_kind={"choice": "small_talk", "confidence": 0.6, "probabilities": {
                      "question": 0.0, "follow_up": 0.0, "reaction": 0.15, "instruction": 0.0, "small_talk": 0.65,
                      "closing": 0.2}},
                  move={"choice": "acknowledge", "confidence": 0.86}, needs_data=0.25)
    assert brain.quick(thanks) and brain.decide(thanks)["move"] == "acknowledge"


def test_saying_she_will_look_is_noticed():
    assert brain.announces_lookup("Let me pull the latest feed status to see if any new records have come in.")
    assert brain.announces_lookup("[warm] One sec — I'll quickly check that.")
    assert not brain.announces_lookup("You are very welcome. I will keep watching the feed for you.")
    assert not brain.announces_lookup("I'll let you know as soon as it moves.")


def test_a_line_that_only_announces_a_lookup_is_recognised():
    assert brain.opens_with_lookup("Let me check cancellation rates for Bikaner, Noida, and Ambala today.")
    assert brain.opens_with_lookup("[thoughtful] Okay, let me pull the top items.")
    assert not brain.opens_with_lookup("Bikaner is at nine percent; let me check Noida next.")
    # the line said after "mm-hm, sure, let me see" in the 18 Oct take
    assert brain.opens_with_lookup("Let me take a look at the cancellations across cities and restaurants.")
    assert brain.opens_with_lookup("Let's have a quick look at Delhi.")


def test_being_told_to_stop_only_wins_over_a_clear_request_when_it_outweighs_it():
    assert brain.dismissed({"addressed": 0.37, "dismisses": 0.61})
    assert not brain.dismissed({"addressed": 0.86, "dismisses": 0.61})
    assert not brain.dismissed({"addressed": 0.1, "dismisses": 0.4})


def test_an_opener_is_said_once():
    assert brain.drop_repeated_opener("Fair enough — I'll check cancellations.",
                                      "[warm] Fair enough — they aren't high.") == "[warm] they aren't high."
    assert brain.drop_repeated_opener("I'll check cancellations.", "Fair enough — fine.") == "Fair enough — fine."


def test_a_confident_social_turn_never_looks_anything_up():
    # Jev's "needs data" can sit near 0.4 for a thank-you; the kind of turn is the reliable signal.
    for kind in ("small_talk", "reaction", "closing"):
        assert brain.quick(read(turn_kind={"choice": kind, "confidence": 0.8}, move={"choice": "acknowledge", "confidence": 0.6},
                                needs_data=0.44))
    assert not brain.quick(read(turn_kind={"choice": "small_talk", "confidence": 0.4}, needs_data=0.44))
    assert not brain.quick(read(turn_kind={"choice": "question", "confidence": 0.9}, needs_data=0.33))


def test_jev_decides_whether_a_turn_stands_on_its_own():
    # a repeat of an earlier question still stands on its own, however Jev labels the kind of turn
    assert brain.stands_alone(read(turn_kind={"choice": "question", "confidence": 0.47}, self_contained=0.9))
    assert not brain.stands_alone(read(turn_kind={"choice": "question", "confidence": 0.9}, self_contained=0.3))


def test_only_a_new_question_can_be_answered_from_memory():
    assert brain.stands_alone(read(turn_kind={"choice": "question", "confidence": 0.9}))
    # however long or short it is: "and Pune?" builds on the last answer; "GMV today?" stands on its own
    assert not brain.stands_alone(read(turn_kind={"choice": "follow_up", "confidence": 0.9}))
    for kind in ("small_talk", "reaction", "closing", "correction"):
        assert not brain.stands_alone(read(turn_kind={"choice": kind, "confidence": 0.9}))
    assert not brain.stands_alone(read(turn_kind={"choice": "question", "confidence": 0.4}))  # unsure: answer afresh
    assert brain.stands_alone(None) is None  # no read at all: the caller falls back


def test_a_social_turn_never_comes_from_memory_even_if_it_stands_alone():
    assert not brain.stands_alone(read(turn_kind={"choice": "reaction", "confidence": 0.97}, self_contained=0.73))


async def test_an_interruption_that_starts_like_an_addition_adds_to_the_request_without_a_read(monkeypatch):
    async def no_jev(state, qs):
        return None

    monkeypatch.setattr(brain, "_one", no_jev)
    assert (await brain.relation("Which cities are behind on delivered orders?", "", "also by cancellation rate"))["relation"] == "adds_to"
    assert (await brain.relation("Which cities are behind on delivered orders?", "", "how is GMV today"))["relation"] == "replaces"


async def test_jev_decides_how_an_interruption_relates(monkeypatch):
    async def jev(state, qs):
        assert set(state) == {"earlier_request", "jenny_had_said", "new_words"}
        return {"relation": {"choice": "corrects", "confidence": 0.9}, "latency_ms": 300}

    monkeypatch.setattr(brain, "_one", jev)
    assert (await brain.relation("GMV in Pune", "", "sorry, I meant Mumbai"))["relation"] == "corrects"


def test_a_standing_preference_is_noticed_and_followed():
    r = read(sets_preference=0.9)
    assert brain.sets_preference(r)
    assert "from now on" in brain.guidance(r, voice=True)
    assert not brain.sets_preference(read(sets_preference=0.3))
