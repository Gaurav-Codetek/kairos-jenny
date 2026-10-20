"""Jenny in a meeting: quiet unless addressed, her answer said sentence by sentence, stopped when talked over."""

import asyncio
import json
import time
import uuid

import pytest

from kairos_kb.meetings import session as S


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, t):
        self.sent.append(json.loads(t))


@pytest.fixture
def meet(monkeypatch):
    s = S.MeetingSession(uuid.uuid4(), "https://meet.google.com/abc-defg-hij", uuid.uuid4())
    s.ws, s.state = FakeWS(), "in_meeting"

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(S.chat, "note_heard", nothing)
    monkeypatch.setattr(s, "_note", nothing)
    monkeypatch.setattr(S.voice, "_last_back", {})  # each test starts the phrases from the first
    return s


def reads(**over):
    base = {"addressed": 0.9, "finished": 0.9, "bears": 0.1, "agreement": 0.1, "dismisses": 0.05}
    return {**base, **over}


@pytest.fixture
def room(meet, monkeypatch):
    """The meeting with Jev, her voice and her turn stubbed: what she was asked (and how), what was kept as heard,
    and the turns cut off."""
    log = {"read": [], "asked": [], "heard": [], "cut": [], "jev": reads()}

    async def jev(speaker, words, before, recent, last=""):
        log["read"].append(words)
        return log["jev"]

    async def note(conv, speaker, text):
        log["heard"].append(text)

    async def ask(speaker, words, channel, **how):
        log["asked"].append((words, {k: v for k, v in how.items() if v}))

    async def speak(text, tone=None, previous=None):
        return b"mp3"

    async def cut_off(conv, heard):
        log["cut"].append(heard)

    monkeypatch.setattr(S.brain, "meeting_read", jev)
    monkeypatch.setattr(S.chat, "note_heard", note)
    monkeypatch.setattr(S.chat, "_cut_off", cut_off)
    monkeypatch.setattr(S.voice, "speak", speak)
    monkeypatch.setattr(meet, "_ask", ask)
    return log


async def said(meet):
    """What she said aloud (each queued sound gets a moment to go out)."""
    for _ in range(3):
        await asyncio.sleep(0)
    return [m["text"] for m in meet.ws.sent if m["type"] == "say"]


async def test_people_talking_among_themselves_never_reach_jev(meet, room):
    await meet._heard("Rahul", "Pune looked fine to me.")
    assert room["read"] == [] and room["asked"] == [] and room["heard"] == ["Pune looked fine to me."]


async def test_her_name_makes_a_question(meet, room):
    await meet._heard("Priya", "Jenny, how did Pune do?")
    assert room["asked"] == [("Jenny, how did Pune do?", {})]


async def test_pointing_back_at_what_she_said_reaches_her_without_her_name(meet, room):
    room["jev"] = reads(agreement=0.9)
    await meet._heard("Gaurav", "So that was the order volume you mentioned, correct?")
    assert room["asked"] == [("So that was the order volume you mentioned, correct?", {"agreement": True})]


async def test_a_thought_cut_off_midway_waits_for_the_rest(meet, room, monkeypatch):
    room["jev"] = reads(finished=0.2)
    await meet._heard("Gaurav", "Jenny, listen, actually I wanted.")
    assert room["asked"] == [] and "Gaurav" in meet.held
    room["jev"] = reads()
    await meet._heard("Gaurav", "The per day distribution, not the total.")
    assert room["asked"] == [("Jenny, listen, actually I wanted. The per day distribution, not the total.", {})]
    assert not meet.held


async def test_told_to_stop_she_stops_drops_her_answer_says_mm_okay_and_listens(meet, room):
    meet.speaking = meet.answering = True
    room["jev"] = reads(addressed=0.37, finished=0.11, dismisses=0.61)   # "No, no, no, no, no stop, um?"
    await meet._heard("Gaurav", "No, no, no, no, no stop, um?")
    assert {"type": "stop"} in meet.ws.sent and room["cut"] == [""]       # the answer being worked out is dropped
    assert await said(meet) == [S.voice.BACKCHANNEL["stop"][0]] and room["asked"] == []
    assert "Gaurav" in meet.answered                                       # what they say next is for her


async def test_not_you_when_shes_quiet_gets_a_quick_sorry(meet, room):
    meet.answered["Gaurav"] = time.monotonic()
    room["jev"] = reads(addressed=0.3, dismisses=0.9)
    await meet._heard("Gaurav", "No no, Jenny, we're talking among ourselves.")
    assert await said(meet) == [S.voice.BACKCHANNEL["sorry"][0]] and room["asked"] == [] and room["cut"] == []


async def test_a_question_right_after_stop_is_a_question_not_a_dismissal(meet, room):
    # 18 Oct: read addressed .86, dismisses .61 — and she replied "Oh, my bad — I thought you were asking me."
    meet.answered["Gaurav"] = time.monotonic()
    room["jev"] = reads(addressed=0.86, finished=0.46, dismisses=0.61)
    await meet._heard("Gaurav", "So Jenny North Indian cities. I want to know what people are ordering most.")
    assert [w for w, _ in room["asked"]] == ["So Jenny North Indian cities. I want to know what people are ordering most."]


async def test_a_question_needing_a_lookup_gets_mm_hm_at_once(meet, room):
    room["jev"] = reads(needs_look=0.9)
    await meet._heard("Priya", "Jenny, how did Pune do?")
    ack = S.voice.BACKCHANNEL["look"][0]
    assert await said(meet) == [ack]
    assert room["asked"] == [("Jenny, how did Pune do?", {"acked": ack})]
    room["jev"] = reads(needs_look=0.1)                                     # "how are you?" needs no "one sec"
    await meet._heard("Priya", "Jenny, how are you?")
    assert await said(meet) == [ack]


async def test_trailing_off_gets_mm_hm_and_she_keeps_waiting(meet, room, monkeypatch):
    meet.answered["Gaurav"] = time.monotonic()                               # she'd just answered him
    room["jev"] = reads(finished=0.07)
    await meet._heard("Gaurav", "Okay, and can you tell me about?")
    meet.held["Gaurav"]["at"] -= S.GO_ON_S + 0.1                            # a moment of quiet

    async def one_tick(_s):
        meet.state = "done"

    real_sleep = asyncio.sleep
    monkeypatch.setattr(S.asyncio, "sleep", one_tick)
    await meet._listen()
    monkeypatch.setattr(S.asyncio, "sleep", real_sleep)
    assert await said(meet) == [S.voice.BACKCHANNEL["go_on"][0]]
    assert "Gaurav" in meet.held and room["asked"] == []                    # still waiting for the rest


class LiveEars:
    live = True

    async def feed(self, pcm):
        self.fed = getattr(self, "fed", []) + [pcm]


def test_a_phrase_from_the_audio_is_named_by_the_latest_caption_never_waiting_for_one(meet):
    assert meet._speaker_now() == "Someone"                                  # no caption yet: not waited for
    meet.hearing.caption("b1", "Gaurav", "Jenny how did", time.monotonic())
    assert meet._speaker_now() == "Gaurav"
    meet.hearing.blocks.clear()
    assert meet._speaker_now() == "Gaurav"                                   # the last one named stands in


async def test_talking_over_her_is_heard_from_words_still_being_said(meet, room):
    meet.speaking = True
    await meet._partial("wait")
    assert {"type": "stop"} not in meet.ws.sent                              # one word isn't talking over her
    await meet._partial("wait wait stop")
    assert {"type": "stop"} in meet.ws.sent


async def test_with_audio_ears_the_captions_only_name_people(meet, room, monkeypatch):
    meet.ears = LiveEars()
    await meet.on_event({"type": "audio", "pcm": "AAAA"})
    assert meet.ears.fed == ["AAAA"]
    meet.hearing.caption("b1", "Gaurav", "Jenny, how did Pune do?", 0.0)

    async def one_tick(_s):
        meet.state = "done"

    real_sleep = asyncio.sleep
    monkeypatch.setattr(S.asyncio, "sleep", one_tick)
    await meet._listen()
    monkeypatch.setattr(S.asyncio, "sleep", real_sleep)
    assert room["asked"] == [] and room["read"] == []                        # the audio's phrase is the turn, not this


async def test_the_18_oct_meeting_replayed_she_answers_and_says_yes_when_called(meet, room, monkeypatch):
    # What she heard by ear (names from captions that trailed the audio), and what Jev read — she answered none of it.
    meet.ears = LiveEars()
    jev = {"Hey, Jenny. How are you?": reads(addressed=0.57, needs_look=0.02),
           "Hello.": reads(addressed=0.2, needs_look=0.02),
           "Hello. Can you tell me about cancellation rates?": reads(addressed=0.45, needs_look=0.9)}

    async def read(speaker, words, before, recent, last=""):
        room["read"].append(words)
        return jev[words]

    monkeypatch.setattr(S.brain, "meeting_read", read)
    await meet._heard("Someone", "Hey, Jenny. How are you?")
    assert room["asked"][-1][0] == "Hey, Jenny. How are you?"               # her name, said to her: it's for her
    await meet._heard("Gaurav Patel", "Hey, Jenny.")
    assert "Hey, Jenny." not in room["read"]                                 # just calling her: no read to wait on
    assert await said(meet) == [S.voice.BACKCHANNEL["here"][0]]              # "Hi — yes?"
    await meet._heard("Gaurav Patel", "Hello.")
    assert "Gaurav Patel" in meet.held                                       # not a request yet: the start of one
    await meet._heard("Gaurav Patel", "Can you tell me about cancellation rates?")
    asked = [w for w, _ in room["asked"]]
    assert asked[-1] == "Hello. Can you tell me about cancellation rates?"   # the answer to her "yes?" is for her


async def test_the_meet_take_a_lead_in_waits_for_the_question_and_gets_one_mm_hm(meet, room, monkeypatch):
    # 18 Oct take: "Uh, cancellations look a bit high today." (a pause) "Can you tell me which cities…" — she answered
    # the first half, said "mm-hm" over him, then "sure, let me see" for the second, and answered 19 s later.
    meet.ears = LiveEars()
    lead = "Uh, cancellations look a bit high today."
    ask = "Can you tell me which cities are driving them, and is it one restaurant or spread out?"
    jev = {lead: reads(addressed=0.45, finished=0.65, needs_look=0.57),
           f"{lead} {ask}": reads(addressed=0.9, finished=0.9, needs_look=0.9)}

    async def read(speaker, words, before, recent, last=""):
        room["read"].append(words)
        return jev[words]

    monkeypatch.setattr(S.brain, "meeting_read", read)
    await meet._heard("Gaurav Patel", "Hey, Jenny.")
    await meet._heard("Gaurav Patel", lead)
    assert room["asked"] == [] and "Gaurav Patel" in meet.held
    await meet._heard("Gaurav Patel", ask)
    assert [w for w, _ in room["asked"]] == [f"{lead} {ask}"]
    assert await said(meet) == [S.voice.BACKCHANNEL["here"][0], S.voice.BACKCHANNEL["look"][0]]  # "Hi — yes?", one "mm-hm"


async def test_a_question_waiting_behind_another_gets_no_second_mm_hm(meet, room):
    meet.answering = True
    room["jev"] = reads(needs_look=0.9)
    await meet._heard("Priya", "Jenny, and Pune?")
    assert await said(meet) == []


def test_her_name_said_to_her_is_told_apart_from_a_mention():
    from kairos_kb.meetings.hearing import just_calling, named_to_her

    for s in ("Hey, Jenny. How are you?", "Jenny, what about Pune?", "Okay so Jenny, what's GMV?", "That's right, Jenny?"):
        assert named_to_her(s), s
    assert not named_to_her("As Jenny said earlier, Pune is fine.")
    for s in ("Hey, Jenny.", "Jenny?", "Hi Jenny, you there?", "Hello Jenny"):
        assert just_calling(s), s
    assert not just_calling("Hey Jenny, how did Pune do?")


def test_words_to_listen_for_fit_elevenlabs_limits():
    u = S.stt.url(["Jenny", "Bikaner", "Delivered Orders Index"])
    assert "keyterms=Jenny" in u and "keyterms=Bikaner" in u and "Delivered" not in u
    assert "commit_strategy=vad" in u and "audio_format=pcm_16000" in u


async def test_after_mm_hm_the_lookup_isnt_announced_again(meet, monkeypatch):
    frames = iter([{"pending": False, "live": "", "scenes": [],
                    "narration": ["Let me check cancellation rates for Bikaner, Noida, and Ambala today."],
                    "text": "[thoughtful] Bikaner is at about nine percent."}])

    async def message(_id):
        return next(frames)

    async def speak(text, tone=None, previous=None):
        return b"mp3"

    monkeypatch.setattr(S.chat, "message", message)
    monkeypatch.setattr(S.voice, "speak", speak)
    await meet._follow(uuid.uuid4(), "voice", skip_plan=True)
    assert [m["text"] for m in meet.ws.sent if m["type"] == "say"] == ["Bikaner is at about nine percent."]


async def test_her_answer_is_said_as_it_is_released_and_scenes_go_to_her_camera(meet, monkeypatch):
    scene = {"id": "sc1", "kind": "breakdown", "title": "Cancellation rate by city"}
    frames = iter([
        {"pending": True, "live": "[thoughtful] Chennai is up the most. Delhi", "text": "", "narration": [], "scenes": [scene]},
        {"pending": False, "live": "", "text": "[thoughtful] Chennai is up the most. Delhi is close behind.",
         "narration": [], "scenes": [scene]},
    ])

    async def message(_id):
        return next(frames)

    async def speak(text, tone=None, previous=None):
        return b"mp3:" + text.encode()

    monkeypatch.setattr(S.chat, "message", message)
    monkeypatch.setattr(S.voice, "speak", speak)
    monkeypatch.setattr(S.asyncio, "sleep", _instant)
    await meet._follow(uuid.uuid4(), "voice")
    says = [m["text"] for m in meet.ws.sent if m["type"] == "say"]
    assert says == ["Chennai is up the most.", "Delhi is close behind."]   # each sentence once, tags off
    assert [m["type"] for m in meet.ws.sent].count("scene") == 1


async def test_someone_talking_over_her_stops_her(meet, monkeypatch):
    meet.hearing.caption("b1", "Priya", "Jenny what about Pune", 0.0)
    meet.hearing.due(2.0)
    await meet.on_event({"type": "spoken", "event": "start", "id": 1})
    meet.hearing.caption("b1", "Priya", "Jenny what about Pune sorry stop there", time.monotonic())
    over = meet.hearing.talking_over(time.monotonic())
    assert over is not None
    if over and not meet.cut:
        meet.cut = True
        await meet.send({"type": "stop"})
    assert {"type": "stop"} in meet.ws.sent


async def test_once_admitted_she_introduces_herself(meet, monkeypatch):
    meet.state = "waiting_to_be_admitted"

    async def no_listening():
        return None

    monkeypatch.setattr(meet, "_listen", no_listening)
    await meet.on_event({"type": "state", "state": "in_meeting"})
    assert meet.state == "in_meeting"
    assert any(m["type"] == "chat_send" and "I'm Jenny" in m["text"] for m in meet.ws.sent)


def test_only_meet_links_are_accepted():
    assert S.MEET_URL.match("https://meet.google.com/abc-defg-hij")
    assert not S.MEET_URL.match("https://zoom.us/j/123")


async def _instant(_s):
    return None


async def test_the_talk_before_her_name_is_context_not_the_question(meet, room):
    room["jev"] = reads(bears=0.85)
    await meet._heard("Gaurav", "We see data loss on weekend mornings. So Jenny, what was the exact timing?")
    assert room["asked"] == [("So Jenny, what was the exact timing?",
                              {"before": "We see data loss on weekend mornings.", "bears": True})]
    assert room["heard"] == ["We see data loss on weekend mornings."]   # kept as heard; the question is her turn
