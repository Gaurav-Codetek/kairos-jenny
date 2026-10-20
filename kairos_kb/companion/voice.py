"""Jenny's voice: ElevenLabs when a key is set, otherwise open-source text to speech (Kokoro-82M) beside Kairos.

The screen asks Kairos for each phrase; Kairos asks the voice engine and keeps the result, so lines said
often (the "Mm-hm." and "One sec." of a conversation) come back at once.

ElevenLabs (eleven_v4_turbo by default, made for real time) says each sentence in a steady, clean assistant's voice:
high stability, no added style, one even pace. (Tone cues can be sent as audio tags with JENNY_ELEVEN_TAGS=1.) Kokoro has no emotion styles, so
there a concerned line is just said a touch slower and an upbeat one a touch quicker. If ElevenLabs refuses
(key rejected, credits used up, unreachable) Kokoro takes over until it's back; with neither, the screen
falls back to the browser's own voice.

Settings:
    ELEVENLABS_API_KEY   turns ElevenLabs on (a key with Text to Speech access; Voices read lets names resolve)
    JENNY_ELEVEN_VOICE   a voice name from your ElevenLabs library, or its id (default Alisha, an Indian English voice)
    JENNY_ELEVEN_MODEL   default eleven_v4_turbo
    JENNY_ELEVEN_TAGS    0 (default): plain, even delivery; 1 sends tone cues as audio tags
    JENNY_ELEVEN_STABILITY  0.75 (default): higher is steadier, lower more expressive
    JENNY_ACCENT         optional, e.g. "Indian English": an accent for her voice (an accent tag, never read out)
    KAIROS_VOICE_URL     Kokoro (default http://voice:8880, the compose service); JENNY_VOICE its voice (af_heart)
"""

from __future__ import annotations

import asyncio
import re
import logging
import os
import time
from collections import OrderedDict
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

URL = os.getenv("KAIROS_VOICE_URL", "http://voice:8880").rstrip("/")
VOICE = os.getenv("JENNY_VOICE", "af_heart")
ENGINE = "kokoro"
MAX_CACHED = 400

ELEVEN_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVEN_VOICE = os.getenv("JENNY_ELEVEN_VOICE", "Alisha").strip()
ELEVEN_MODEL = os.getenv("JENNY_ELEVEN_MODEL", "eleven_v4_turbo").strip()
# Off by default: an assistant's voice stays even; emotion tags make it sound like a person on a call.
ELEVEN_TAGS = os.getenv("JENNY_ELEVEN_TAGS", "0").strip().lower() not in ("0", "false", "no", "off")
# An accent for her voice, e.g. "Indian English": sent as an accent tag, which shapes delivery and is never read out.
ELEVEN_ACCENT = os.getenv("JENNY_ACCENT", "").strip()
# Higher is steadier (less expressive); ElevenLabs' range is 0-1.
ELEVEN_STABILITY = float(os.getenv("JENNY_ELEVEN_STABILITY", "0.75"))
ELEVEN_API = "https://api.elevenlabs.io/v1"
# ElevenLabs' own premade voices, for when the key can't list voices.
# Indian English voices from the ElevenLabs library, pinned by id: Alisha ("Soft and Engaging", Jenny's voice) and
# Raju ("Natural Conversationalist", Jack's).
PREMADE = {"alisha": "ftDdhfYtmfGP0tFlBYA1", "raju": "pzxut4zZz4GImZNlqQ3H", "sarah": "EXAVITQu4vr4xnSDxMaL", "jessica": "cgSgspJ2msm6clMCkdW9", "laura": "FGY2WhTYpPnrIDTdsKH5",
           "alice": "Xb7hH8MSUJpSbSDYk0k2", "matilda": "XrExE9yKIg1WjnnlVkGX", "lily": "pFZP5JQG7iQjIQuC4Bku"}
# Tone cue -> audio tag (only tags ElevenLabs documents; the rest are carried by pace alone).
TAG = {"warm": "warm", "happy": "warm", "reassuring": "reassuring", "calm": "reassuring", "concerned": "sympathetic",
       "sad": "sympathetic", "curious": "curious", "upbeat": "excited", "excited": "excited"}

PACE = {"concerned": 0.92, "sad": 0.9, "serious": 0.94, "thoughtful": 0.95, "calm": 0.96, "reassuring": 0.96,
        "warm": 1.0, "curious": 1.03, "happy": 1.04, "upbeat": 1.06, "excited": 1.08}

# The little sounds a listener makes, said the instant they fit — before any thinking — so a conversation never
# hangs in silence: "mm-hm, one sec" as soon as a question needing a lookup ends, "mm, okay" when she's told to stop,
# "mm-hm?" when someone trails off mid-thought, "oh, sorry" when it wasn't for her. Rotated, never the same twice
# running.
BACKCHANNEL = {
    "look": ["Mm-hm, one sec.", "Sure, let me see.", "Mm, okay — one moment.", "Mm-hm, let me look."],
    "stop": ["Mm, okay.", "Mm-hm, sure.", "Okay — go on."],
    "go_on": ["Mm-hm?", "Mm?", "Yeah?"],
    "sorry": ["Oh — sorry, carry on.", "Oops, my bad."],
    "here": ["Hi — yes?", "Yes?", "Hey — I'm here."],
}
_last_back: Dict[str, str] = {}


def backchannel(kind: str) -> Optional[str]:
    """One of the kind's phrases, not the one said last time."""
    options = BACKCHANNEL.get(kind) or []
    if not options:
        return None
    last = _last_back.get(kind)
    pick = options[(options.index(last) + 1) % len(options)] if last in options else options[0]
    _last_back[kind] = pick
    return pick


# Phrases said in almost every conversation: made when Kairos starts, so they play instantly.
COMMON = ["I'm still working on your last question — one moment."] + [p for ps in BACKCHANNEL.values() for p in ps]

_cache: "OrderedDict[tuple, bytes]" = OrderedDict()  # (engine, text, tone or pace) -> MP3
# Kokoro works through one phrase at a time on a CPU; requests in parallel only slow each other down. Live phrases
# (someone is waiting to hear them) always go before phrases made ahead of time.
_gate = asyncio.Semaphore(1)
_live_waiting = 0
_health: Tuple[float, bool] = (0.0, False)
_last_made = 0.0  # when the voice last made a phrase: proof it's up, without asking
_client: Optional[httpx.AsyncClient] = None
_eleven_gate = asyncio.Semaphore(4)  # remote: a few at once is fine (plans allow several concurrent requests)
_eleven_down_until = 0.0  # after a refusal, Kokoro speaks until then
_eleven_voice: Optional[Tuple[str, str]] = None  # (id, name) once resolved


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=3.0))
    return _client


async def available() -> bool:
    """Whether the voice service answers (checked at most every 30 seconds)."""
    global _health
    if _eleven_on():
        return True
    # Busy making a phrase, or made one recently: it's up (a busy CPU can make a health check slow to answer).
    if _gate.locked() or time.monotonic() - _last_made < 120:
        return True
    at, ok = _health
    if time.monotonic() - at < 30:
        return ok
    try:
        ok = (await _http().get(f"{URL}/health", timeout=5.0)).status_code == 200
    except httpx.HTTPError:
        ok = False
    _health = (time.monotonic(), ok)
    return ok


def _clean(text: Optional[str]) -> str:
    return " ".join(_plain(text or "").split())[:600]


def _plain(text: str) -> str:
    """What a written reply sounds like said: no markdown. Bold and code marks go, bullets and headings lose their
    markers, a table row becomes its cells in a phrase and its rule line goes — so none of it is read out."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if re.fullmatch(r"\|?[\s:|-]*-{3,}[\s:|-]*", s):
            continue  # a table's rule line
        if s.startswith("|"):
            s = ", ".join(c.strip() for c in s.strip("|").split("|") if c.strip())
        s = re.sub(r"^(?:#+|[-*•]|\d+[.)])\s+", "", s)
        out.append(s.replace("**", "").replace("__", "").replace("`", ""))
    return "\n".join(out)


_TAGS = re.compile(r"\[[^\]]*\]")


def sayable(text: str) -> bool:
    """Something to say once tone tags ([warm]…) are taken out: a line that's only a tag or punctuation isn't (ElevenLabs
    refuses it as empty text)."""
    return bool(re.search(r"[A-Za-z0-9]", _TAGS.sub("", text or "")))


async def speak(text: str, tone: Optional[str] = None, *, ahead: bool = False,
                previous: Optional[str] = None) -> Optional[bytes]:
    """The phrase as MP3 audio, or None when the voice service can't say it. `ahead`: made in advance, so it
    waits until no one is waiting on a live phrase. `previous`: the sentence she said just before, so the
    intonation carries on from it instead of starting fresh (ElevenLabs)."""
    text, previous = _clean(text), _clean(previous)[-300:]
    if not sayable(text):
        return None
    pace = PACE.get((tone or "").lower(), 1.0)
    if _eleven_on():
        key = ("eleven", text, (tone or "").lower() if ELEVEN_TAGS else "", previous, ELEVEN_ACCENT)
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        audio = await _eleven(text, tone, pace, previous)
        if audio:
            return _keep(key, audio)
        if audio == b"":  # ElevenLabs can't say this one phrase: skip it rather than say it in another voice
            return None
    return await _kokoro(text, pace, ahead)


def _keep(key, audio: bytes) -> bytes:
    _cache[key] = audio
    while len(_cache) > MAX_CACHED:
        _cache.popitem(last=False)
    return audio


async def _kokoro(text: str, pace: float, ahead: bool) -> Optional[bytes]:
    global _live_waiting
    key = ("kokoro", text, pace)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    if not ahead:
        _live_waiting += 1
    try:
        if ahead:
            while _live_waiting:
                await asyncio.sleep(0.2)
        async with _gate:
            if key in _cache:  # made while this request waited its turn
                return _cache[key]
            r = await _http().post(f"{URL}/v1/audio/speech", json={
                "model": "kokoro", "voice": VOICE, "input": text, "response_format": "mp3", "speed": pace,
                "stream": False})
    except httpx.HTTPError as exc:
        logger.warning("Voice service unreachable: %s %s", type(exc).__name__, exc)
        return None
    finally:
        if not ahead:
            _live_waiting -= 1
    if r.status_code != 200 or not r.content:
        logger.warning("Voice service could not say %r: %s", text[:40], r.status_code)
        return None
    global _last_made
    _last_made = time.monotonic()
    return _keep(key, r.content)


# ── ElevenLabs ─────────────────────────────────────────────────────────────

def _eleven_on() -> bool:
    return bool(ELEVEN_KEY) and time.monotonic() >= _eleven_down_until


def _eleven_off(seconds: float, why: str) -> None:
    global _eleven_down_until
    _eleven_down_until = time.monotonic() + seconds
    logger.warning("ElevenLabs voice off for %ds (%s); Kokoro speaks meanwhile", seconds, why)


async def _eleven_voice_id() -> Tuple[str, str]:
    """The configured voice as (id, name): looked up by name in the account's voices, or taken as an id."""
    global _eleven_voice
    if _eleven_voice:
        return _eleven_voice
    want = ELEVEN_VOICE.lower()
    if want in PREMADE:
        # A voice we've pinned by id (Raju from the voice library): the account may hold another voice of that name.
        _eleven_voice = (PREMADE[want], ELEVEN_VOICE)
        logger.info("Jenny's ElevenLabs voice: %s (%s, %s)", ELEVEN_VOICE, PREMADE[want], ELEVEN_MODEL)
        return _eleven_voice
    found = None
    try:
        r = await _http().get(f"{ELEVEN_API}/voices", headers={"xi-api-key": ELEVEN_KEY}, timeout=10.0)
        if r.status_code == 200:
            for v in r.json().get("voices", []):
                name = (v.get("name") or "").strip()
                if v.get("voice_id") == ELEVEN_VOICE or name.lower() == want or name.lower().split(" - ")[0] == want:
                    found = (v["voice_id"], name)
                    break
    except (httpx.HTTPError, ValueError):
        return (PREMADE.get(want, ELEVEN_VOICE), ELEVEN_VOICE)  # try the lookup again next time
    # The key can't list voices, or the name isn't in the library: a premade voice by that name, or the id as given.
    _eleven_voice = found or (PREMADE.get(want, ELEVEN_VOICE), ELEVEN_VOICE)
    logger.info("Jenny's ElevenLabs voice: %s (%s, %s)", _eleven_voice[1], _eleven_voice[0], ELEVEN_MODEL)
    return _eleven_voice


def _eleven_body(text: str, tone: Optional[str], pace: float, previous: str = "") -> Dict[str, Any]:
    tag = TAG.get((tone or "").lower()) if ELEVEN_TAGS else None
    lead = (f"[{ELEVEN_ACCENT} accent] " if ELEVEN_ACCENT else "") + (f"[{tag}] " if tag else "")
    body: Dict[str, Any] = {
        "text": lead + text,
        "model_id": ELEVEN_MODEL,
        # Steady and clean: high stability, no added style, one even pace (tone cues only colour Kokoro's pace).
        "voice_settings": {"stability": ELEVEN_STABILITY, "similarity_boost": 0.8, "style": 0.0, "use_speaker_boost": True,
                           "speed": max(0.8, min(1.15, pace)) if ELEVEN_TAGS else 1.0},
    }
    if previous:
        body["previous_text"] = previous
    return body


def _about_the_phrase(status: int, detail: str) -> bool:
    """A refusal of this one phrase's text (empty after tags, too long…), not of the key, voice or model."""
    d = detail.lower()
    return status in (400, 422) and ("text" in d) and not any(w in d for w in ("voice_id", "voice not", "model"))


def _refused(status: int, detail: str) -> bool:
    """React to a refusal; True when only this phrase was refused (her voice stays on for everything else)."""
    if _about_the_phrase(status, detail):
        logger.warning("ElevenLabs couldn't say one phrase (%s: %s); skipped, voice stays on", status, detail[:160])
        return True
    if status == 401 or "quota" in detail:
        _eleven_off(600, f"{status}: key rejected or out of credits: {detail[:160]}")
    elif status in (400, 404, 422):
        _eleven_off(600, f"{status}: check JENNY_ELEVEN_VOICE / JENNY_ELEVEN_MODEL: {detail[:160]}")
    else:
        _eleven_off(30, f"{status}: {detail[:160]}")
    return False


async def stream(text: str, tone: Optional[str] = None, previous: Optional[str] = None) -> AsyncIterator[bytes]:
    """The phrase as MP3, streamed as ElevenLabs makes it — the first audio arrives in about a third of a second
    instead of after the whole phrase — and kept once complete. Otherwise (cached, or Kokoro) the whole phrase."""
    global _last_made
    text, previous = _clean(text), _clean(previous)[-300:]
    if not sayable(text):
        return
    pace = PACE.get((tone or "").lower(), 1.0)
    key = ("eleven", text, (tone or "").lower() if ELEVEN_TAGS else "", previous, ELEVEN_ACCENT)
    if _eleven_on() and key not in _cache:
        voice_id, _ = await _eleven_voice_id()
        chunks: List[bytes] = []
        try:
            async with _eleven_gate:
                async with _http().stream("POST", f"{ELEVEN_API}/text-to-speech/{voice_id}/stream",
                                          params={"output_format": "mp3_44100_128"}, headers={"xi-api-key": ELEVEN_KEY},
                                          json=_eleven_body(text, tone, pace, previous), timeout=15.0) as r:
                    if r.status_code == 200:
                        async for c in r.aiter_bytes():
                            chunks.append(c)
                            yield c
                    elif _refused(r.status_code, (await r.aread()).decode("utf-8", "replace")[:300]):
                        return  # this phrase can't be said: skipped, not said in another voice
        except httpx.HTTPError as exc:
            _eleven_off(30, f"unreachable: {type(exc).__name__}")
        if chunks:
            _last_made = time.monotonic()
            _keep(key, b"".join(chunks))
            return
    audio = await speak(text, tone, previous=previous)
    if audio:
        yield audio


async def _eleven(text: str, tone: Optional[str], pace: float, previous: str = "") -> Optional[bytes]:
    """The line from ElevenLabs as MP3, or None (and Kokoro takes over for a while) when it refuses."""
    global _last_made
    voice_id, _ = await _eleven_voice_id()
    body = _eleven_body(text, tone, pace, previous)
    for attempt in range(2):
        try:
            async with _eleven_gate:
                r = await _http().post(f"{ELEVEN_API}/text-to-speech/{voice_id}",
                                       params={"output_format": "mp3_44100_128"},
                                       headers={"xi-api-key": ELEVEN_KEY}, json=body, timeout=15.0)
        except httpx.HTTPError as exc:
            _eleven_off(30, f"unreachable: {type(exc).__name__}")
            return None
        if r.status_code == 200 and r.content:
            _last_made = time.monotonic()
            return r.content
        detail = r.text[:300]
        if r.status_code == 429 and attempt == 0 and "quota" not in detail:
            await asyncio.sleep(0.4)  # too many at once: one short retry
            continue
        return b"" if _refused(r.status_code, detail) else None
    return None


async def info() -> dict:
    """What the screen shows: whether her own voice is up, which voice, which engine."""
    up = await available()
    if _eleven_on():
        _, name = await _eleven_voice_id()
        return {"available": up, "voice": name, "engine": f"elevenlabs ({ELEVEN_MODEL})"}
    return {"available": up, "voice": VOICE, "engine": ENGINE}


async def warm(phrases: list[str], tone: str = "warm") -> None:
    """Say the everyday phrases once ahead of time, so they come back instantly on a call. At startup the voice
    service may still be loading: wait for it (up to two minutes)."""
    global _health
    for _ in range(40):
        _health = (0.0, False)  # check afresh
        if await available():
            break
        await asyncio.sleep(3)
    else:
        return
    started = time.monotonic()
    for p in phrases:
        try:
            await speak(p, tone, ahead=True)
        except Exception:  # noqa: BLE001 — warming is a nicety
            return
        await asyncio.sleep(0)
    logger.info("Jenny's everyday phrases ready in her voice (%d, %.1fs)", len(phrases), time.monotonic() - started)
