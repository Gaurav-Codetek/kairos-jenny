"""Jenny in a meeting: quiet unless addressed, her answer said sentence by sentence, stopped when talked over."""

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
    return s


def reads(**over):
    base = {"addressed": 0.9, "finished": 0.9, "bears": 0.1, "agreement": 0.1, "dismisses": 0.05}
    return {**base, **over}


@pytest.fixture
def room(meet, monkeypatch):
    """The meeting with Jev and her turn stubbed: what she was asked (and how), and what was kept as heard."""
    log = {"read": [], "asked": [], "heard": [], "jev": reads()}

    async def jev(speaker, words, before, recent, last=""):
        log["read"].append(words)
        return log["jev"]

    async def note(conv, speaker, text):
        log["heard"].append(text)

    async def ask(speaker, words, channel, **how):
        log["asked"].append((words, {k: v for k, v in how.items() if v}))

    monkeypatch.setattr(S.brain, "meeting_read", jev)
    monkeypatch.setattr(S.chat, "note_heard", note)
    monkeypatch.setattr(meet, "_ask", ask)
    return log


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


async def test_not_you_gets_an_apology_and_stops_her(meet, room):
    meet.speaking = True
    room["jev"] = reads(addressed=0.3, dismisses=0.9)
    await meet._heard("Gaurav", "No no, Jenny, we're talking among ourselves.")
    assert {"type": "stop"} in meet.ws.sent
    assert room["asked"][0][1] == {"dismissed": True}


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
