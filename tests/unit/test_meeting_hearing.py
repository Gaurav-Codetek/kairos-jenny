"""Hearing a meeting through Meet's captions: settled words become utterances, once each."""

from kairos_kb.meetings.hearing import FINAL_S, Hearing, mentions_jenny, refers_to_her, split_at_name


def test_a_caption_counts_once_it_has_settled():
    h = Hearing()
    h.caption("b1", "Priya", "Jenny how did", 0.0)
    h.caption("b1", "Priya", "Jenny, how did Pune do", 0.4)
    assert h.due(1.0) == []                      # still changing
    out = h.due(0.4 + FINAL_S)
    assert [(u.speaker, u.text) for u in out] == [("Priya", "Jenny, how did Pune do")]
    assert h.due(5.0) == []                      # taken once


def test_rewrites_of_the_last_words_before_settling_are_fine():
    h = Hearing()
    h.caption("b1", "Rahul", "cancellations in poon", 0.0)
    h.caption("b1", "Rahul", "cancellations in Pune", 0.3)
    assert [u.text for u in h.due(2.0)] == ["cancellations in Pune"]


def test_a_block_that_grows_after_a_pause_gives_only_the_new_words():
    h = Hearing()
    h.caption("b1", "Priya", "Thanks Jenny.", 0.0)
    assert [u.text for u in h.due(2.0)] == ["Thanks Jenny."]
    h.caption("b1", "Priya", "Thanks Jenny. And what about Delhi?", 3.0)
    assert [u.text for u in h.due(5.0)] == ["And what about Delhi?"]


def test_two_speakers_come_out_in_order():
    h = Hearing()
    h.caption("b1", "Priya", "Sales look fine.", 0.0)
    h.caption("b2", "Rahul", "Agreed.", 0.5)
    assert [(u.speaker, u.text) for u in h.due(3.0)] == [("Priya", "Sales look fine."), ("Rahul", "Agreed.")]


def test_her_own_voice_is_not_someone_talking():
    h = Hearing()
    h.caption("b1", "You", "Chennai is up the most.", 0.0)
    h.caption("b2", "Jenny (Kairos)", "Chennai is up the most.", 0.0)
    assert h.due(3.0) == []


def test_talking_over_her_needs_new_words():
    h = Hearing()
    h.caption("b1", "Priya", "Jenny what about Pune", 0.0)
    h.due(2.0)
    h.she_starts_speaking()
    assert h.talking_over(2.1) is None           # the question she's answering isn't talking over her
    h.caption("b1", "Priya", "Jenny what about Pune sorry wait stop", 3.0)
    over = h.talking_over(3.1)
    assert over and over.speaker == "Priya" and over.text == "sorry wait stop"


def test_her_name_as_captions_spell_it():
    assert mentions_jenny("Jenni, what's GMV?") and mentions_jenny("hey jenny") and not mentions_jenny("Jennifer said")


def test_the_question_starts_where_she_is_addressed():
    talk = ("During the weekends we are seeing a surge, and frequent data loss in the morning. We have to fix that. "
            "So Jenny, what was the exact timing on Saturday and Sunday? It was around the morning.")
    before, ask = split_at_name(talk)
    assert before.endswith("We have to fix that.")
    assert ask == "So Jenny, what was the exact timing on Saturday and Sunday? It was around the morning."


def test_an_earlier_mention_stays_context_and_no_name_is_all_question():
    before, ask = split_at_name("As Jenny said earlier, Pune is slow. Jenny, why is that?")
    assert before == "As Jenny said earlier, Pune is slow." and ask == "Jenny, why is that?"
    assert split_at_name("And Delhi?") == ("", "And Delhi?")
    assert split_at_name("Jenny, what's GMV today") == ("", "Jenny, what's GMV today")


def test_her_name_tagged_on_at_the_end_makes_the_sentence_before_the_question():
    before, ask = split_at_name("Kochi had fewer orders. So the rate is higher because of volume. Right, Jenny?")
    assert ask == "So the rate is higher because of volume. Right, Jenny?" and before == "Kochi had fewer orders."
    assert split_at_name("Why such a big difference between Chennai and Kochi? Jenny?")[1].startswith("Why such")


def test_words_pointing_back_at_her():
    assert refers_to_her("That was the order volume you mentioned, correct?")
    assert refers_to_her("Is your number for today?") and not refers_to_her("You should check Pune.")
