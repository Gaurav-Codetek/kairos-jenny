"""Jenny's voice: ElevenLabs first when a key is set, Kokoro when it refuses — no network."""

import httpx
import pytest

from kairos_kb.companion import voice


class FakeClient:
    """Answers like ElevenLabs and Kokoro would; records what was asked."""

    def __init__(self, eleven_status=200, eleven_body=b"ELEVEN", voices=None):
        self.eleven_status, self.eleven_body, self.voices = eleven_status, eleven_body, voices or []
        self.posts = []

    async def get(self, url, **kw):
        if url.endswith("/voices"):
            return httpx.Response(200, json={"voices": self.voices})
        return httpx.Response(200)  # Kokoro health

    async def post(self, url, **kw):
        self.posts.append((url, kw.get("json")))
        if "elevenlabs" in url:
            return httpx.Response(self.eleven_status, content=self.eleven_body)
        return httpx.Response(200, content=b"KOKORO")


@pytest.fixture
def fresh(monkeypatch):
    voice._cache.clear()
    monkeypatch.setattr(voice, "_eleven_down_until", 0.0)
    monkeypatch.setattr(voice, "_eleven_voice", None)
    monkeypatch.setattr(voice, "ELEVEN_TAGS", True)
    monkeypatch.setattr(voice, "ELEVEN_VOICE", "Narrator")  # a name looked up in the account's voices

    def use(client, key="k"):
        monkeypatch.setattr(voice, "ELEVEN_KEY", key)
        monkeypatch.setattr(voice, "_client", client)
        return client

    return use


async def test_without_a_key_kokoro_speaks(fresh):
    c = fresh(FakeClient(), key="")
    assert await voice.speak("Okay.", "warm") == b"KOKORO"
    assert all("elevenlabs" not in u for u, _ in c.posts)


async def test_with_a_key_elevenlabs_speaks_with_the_tone_as_a_tag(fresh):
    c = fresh(FakeClient(voices=[{"voice_id": "abc123", "name": "Narrator"}]))
    assert await voice.speak("Pune is behind today.", "concerned") == b"ELEVEN"
    url, body = c.posts[0]
    assert url.endswith("/text-to-speech/abc123")
    assert body["text"] == "[sympathetic] Pune is behind today."
    assert body["voice_settings"]["speed"] < 1  # with tags on, the cue also sets the pace


async def test_by_default_the_voice_is_steady_and_plain(fresh, monkeypatch):
    monkeypatch.setattr(voice, "ELEVEN_TAGS", False)
    c = fresh(FakeClient(voices=[{"voice_id": "abc123", "name": "Narrator"}]))
    await voice.speak("Pune is behind today.", "concerned")
    body = c.posts[0][1]
    assert body["text"] == "Pune is behind today."
    assert body["voice_settings"]["speed"] == 1.0 and body["voice_settings"]["stability"] >= 0.7


async def test_a_line_is_made_once(fresh):
    c = fresh(FakeClient(voices=[{"voice_id": "abc123", "name": "Narrator"}]))
    await voice.speak("Mm-hm.", "warm")
    await voice.speak("Mm-hm.", "warm")
    assert len(c.posts) == 1


async def test_a_rejected_key_hands_over_to_kokoro_for_a_while(fresh):
    c = fresh(FakeClient(eleven_status=401, eleven_body=b'{"detail":"invalid_api_key"}'))
    assert await voice.speak("Okay.") == b"KOKORO"
    assert await voice.speak("Right.") == b"KOKORO"
    assert sum("elevenlabs" in u for u, _ in c.posts) == 1  # not asked again until the pause is over


async def test_a_pinned_voice_is_used_by_its_id_whatever_the_account_holds(fresh, monkeypatch):
    monkeypatch.setattr(voice, "ELEVEN_VOICE", "Raju")
    c = fresh(FakeClient(voices=[{"voice_id": "other-raju", "name": "Raju - Human-like Customer Care Voice"}]))
    await voice.speak("Okay.")
    assert c.posts[0][0].endswith(f"/text-to-speech/{voice.PREMADE['raju']}")


async def test_a_name_not_in_the_library_falls_back_to_the_premade_voice(fresh, monkeypatch):
    monkeypatch.setattr(voice, "ELEVEN_VOICE", "Sarah")
    c = fresh(FakeClient(voices=[]))
    await voice.speak("Okay.")
    assert c.posts[0][0].endswith(f"/text-to-speech/{voice.PREMADE['sarah']}")


async def test_info_names_the_engine(fresh):
    fresh(FakeClient(voices=[{"voice_id": "abc123", "name": "Narrator"}]))
    i = await voice.info()
    assert i["available"] and i["voice"] == "Narrator" and i["engine"].startswith("elevenlabs")


async def test_the_sentence_before_is_sent_so_the_intonation_flows(fresh):
    c = fresh(FakeClient(voices=[{"voice_id": "abc123", "name": "Narrator"}]))
    await voice.speak("And Pune is the one slipping.", previous="Most cities are on track today.")
    assert c.posts[0][1]["previous_text"] == "Most cities are on track today."
    await voice.speak("And Pune is the one slipping.")  # a different context is a different recording
    assert len(c.posts) == 2 and "previous_text" not in c.posts[1][1]


async def test_streaming_falls_back_to_the_whole_phrase(fresh):
    fresh(FakeClient(), key="")  # no ElevenLabs: Kokoro's whole phrase, in one piece
    got = [chunk async for chunk in voice.stream("Okay.", "warm")]
    assert got == [b"KOKORO"]
