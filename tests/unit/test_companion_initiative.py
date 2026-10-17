"""Jenny speaks first: her sense of her own state, and voice notes only when no call is open."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from kairos_kb.companion import chat, initiative


def state(minutes_ago, live=True, offset=330):
    return SimpleNamespace(last_pulse_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago), live=live,
                           tz_offset_minutes=offset)


def local_today(offset=330):
    return (datetime.utcnow() + timedelta(minutes=offset)).date().isoformat()


def test_a_fresh_dashboard_is_just_reported():
    out = chat.own_state(state(3), {"today": local_today()}, [])
    assert "3 minutes ago (fresh" in out and "older" not in out and "still shows" not in out


def test_a_stale_dashboard_and_yesterdays_numbers_are_said_first():
    out = chat.own_state(state(40, live=False), {"today": "2020-01-01"}, [SimpleNamespace(title="Orders stopped arriving")])
    assert "older than usual" in out
    assert "still shows 2020-01-01" in out
    assert "No live data is flowing" in out
    assert "Open data problem: Orders stopped arriving." in out


def test_no_pulse_yet_means_no_numbers():
    assert "no live numbers" in chat.own_state(None, {}, [])


def test_a_call_checking_in_keeps_her_from_leaving_voice_notes():
    ws = uuid.uuid4()
    assert not initiative.calling(ws)
    initiative.on_call(ws)
    assert initiative.calling(ws)


async def test_no_voice_note_while_on_a_call(monkeypatch):
    ws = uuid.uuid4()
    initiative.on_call(ws)

    def no_db():
        raise AssertionError("shouldn't look for anything to record during a call")

    monkeypatch.setattr(initiative, "async_session_factory", no_db)
    assert await initiative.after_pulse(ws) is None


def test_tone_tags_are_for_the_voice_not_the_note():
    said = "[concerned] Orders in Pune have stopped. [calm] I'd check the feed first."
    assert initiative._TAG.match(said).group(1) == "concerned"
    assert initiative._TAG.sub("", said) == "Orders in Pune have stopped. I'd check the feed first."
