"""Her voice: a phrase with nothing to say is never sent, and one refused phrase never switches her voice off."""

from kairos_kb.companion import voice


def test_only_a_tag_or_punctuation_is_nothing_to_say():
    assert not voice.sayable("[warm]") and not voice.sayable(" [concerned]  — … ") and not voice.sayable("")
    assert voice.sayable("[warm] Anytime.") and voice.sayable("9")


def test_one_refused_phrase_keeps_her_voice_on(monkeypatch):
    monkeypatch.setattr(voice, "_eleven_down_until", 0.0)
    detail = '{"detail":{"code":"invalid_parameters","message":"Input at position 0 has empty text."}}'
    assert voice._refused(400, detail) is True and voice._eleven_on()
    assert voice._refused(404, '{"detail":{"status":"voice_not_found"}}') is False and not voice._eleven_on()
