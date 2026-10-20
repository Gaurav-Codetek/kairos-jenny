"""Hearing a meeting through its audio: ElevenLabs' realtime speech to text (Scribe v2 Realtime).

Captions are slow ears: Meet shows a line a moment after it's said, keeps rewriting it, and never says when someone has
finished — so their words could only be taken once the line had sat still for most of a second. The meeting's own
audio (her body sends it, 16 kHz mono, in 100 ms pieces) goes straight to ElevenLabs instead, whose voice activity
detection commits a phrase SILENCE_S after the speaker stops: their words reach her in about half a second, spelled
the way this business spells them (keyterms: her name, the cities in its data). Partial words arrive while they're
still talking, which is how someone talking over her is noticed at once.

Who said it still comes from the captions, read on the side and never waited on (session.py).

Settings:
    JENNY_MEET_HEARING   audio (default when an ElevenLabs key is set) or captions
    JENNY_STT_SILENCE_S  silence that ends a phrase, 0.3-3.0 (default 0.5)
    JENNY_STT_LANGUAGE   default en; empty lets ElevenLabs detect it
    JENNY_STT_KEYTERMS   extra words to listen for, comma-separated
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Awaitable, Callable, Deque, List, Optional
from urllib.parse import urlencode

from kairos_kb.companion import voice

logger = logging.getLogger(__name__)

URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
MODEL = "scribe_v2_realtime"
RATE = 16000
SILENCE_S = min(3.0, max(0.3, float(os.getenv("JENNY_STT_SILENCE_S", "0.5"))))
LANGUAGE = os.getenv("JENNY_STT_LANGUAGE", "en").strip()
MAX_KEYTERMS = 60
KEYTERM_CHARS = 20   # ElevenLabs refuses the whole session over a longer one
BUFFER = 50          # pieces (5 s) kept while connecting, so the start of what's said isn't lost
RETRY_S = 5.0        # after a dropped connection, wait this long before connecting again
START_S = 5.0        # how long start() waits for ElevenLabs to say it's listening
# No point retrying these: the meeting falls back to captions.
FATAL = {"auth_error", "quota_exceeded", "unaccepted_terms", "invalid_request"}

Words = Callable[[str], Awaitable[None]]


def enabled() -> bool:
    """Hear meetings through their audio: there's an ElevenLabs key, and captions haven't been asked for."""
    return bool(voice.ELEVEN_KEY) and os.getenv("JENNY_MEET_HEARING", "audio").strip().lower() != "captions"


def url(keyterms: List[str]) -> str:
    params = [("model_id", MODEL), ("audio_format", f"pcm_{RATE}"), ("commit_strategy", "vad"),
              ("vad_silence_threshold_secs", SILENCE_S), ("enable_logging", "false")]
    if LANGUAGE:
        params.append(("language_code", LANGUAGE))
    params += [("keyterms", k) for k in [k for k in keyterms if len(k) <= KEYTERM_CHARS][:MAX_KEYTERMS]]
    return f"{URL}?{urlencode(params)}"


class Transcriber:
    """One meeting's ears on ElevenLabs: audio in, words out (partial while they talk, committed when they stop)."""

    def __init__(self, on_partial: Words, on_committed: Words, keyterms: Optional[List[str]] = None) -> None:
        self.on_partial, self.on_committed = on_partial, on_committed
        self.keyterms = list(keyterms or [])
        self.ws = None
        self.failed: Optional[str] = None     # refused for good: the meeting goes back to captions
        self.closed = False
        self._connecting: Optional[asyncio.Task] = None
        self._reader: Optional[asyncio.Task] = None
        self._pending: Deque[str] = deque(maxlen=BUFFER)
        self._retry_at = 0.0
        self._started = asyncio.Event()

    @property
    def live(self) -> bool:
        return self.ws is not None and not self.failed and not self.closed

    async def start(self) -> bool:
        """Connect now; True once ElevenLabs says it's listening (a session it accepted, not just a socket)."""
        await self._connect()
        if self.ws is not None:
            try:
                await asyncio.wait_for(self._started.wait(), timeout=START_S)
            except asyncio.TimeoutError:
                logger.warning("ElevenLabs speech to text didn't start within %.0fs", START_S)
        return self.live and self._started.is_set()

    async def feed(self, pcm_b64: str) -> None:
        """A 100 ms piece of the meeting's audio (16-bit mono PCM, base64)."""
        if self.failed or self.closed:
            return
        if self.ws is None:
            self._pending.append(pcm_b64)
            if (self._connecting is None or self._connecting.done()) and time.monotonic() >= self._retry_at:
                self._connecting = asyncio.create_task(self._connect())
            return
        await self._send(pcm_b64)

    async def _send(self, pcm_b64: str) -> None:
        try:
            await self.ws.send(json.dumps({"message_type": "input_audio_chunk", "audio_base_64": pcm_b64,
                                           "commit": False, "sample_rate": RATE}))
        except Exception as exc:  # noqa: BLE001 — dropped: the next piece reconnects
            logger.info("Speech to text connection dropped (%s)", type(exc).__name__)
            self._dropped()

    async def _connect(self) -> None:
        import websockets

        if self.ws is not None or self.failed or self.closed:
            return
        try:
            self.ws = await websockets.connect(url(self.keyterms), additional_headers={"xi-api-key": voice.ELEVEN_KEY},
                                               max_size=2 ** 22, open_timeout=8)
        except Exception as exc:  # noqa: BLE001 — captions keep working meanwhile
            status = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning("Couldn't reach ElevenLabs speech to text (%s %s)", type(exc).__name__, status or exc)
            if status in (401, 403):
                self.failed = f"refused ({status})"
            self._retry_at = time.monotonic() + RETRY_S
            return
        self._reader = asyncio.create_task(self._read(self.ws))
        while self._pending and self.ws is not None:
            await self._send(self._pending.popleft())

    async def _read(self, ws) -> None:
        try:
            async for raw in ws:
                msg = json.loads(raw)
                kind = msg.get("message_type")
                text = (msg.get("text") or "").strip()
                if kind == "partial_transcript" and text:
                    await self.on_partial(text)
                elif kind in ("committed_transcript", "committed_transcript_with_timestamps") and text:
                    await self.on_committed(text)
                elif kind == "session_started":
                    self._started.set()
                    logger.info("ElevenLabs speech to text listening (%s, %.1fs silence ends a phrase, %d keyterms)",
                                MODEL, SILENCE_S, len(self.keyterms))
                elif kind in FATAL or (msg.get("error") and not self._started.is_set()):
                    self.failed = f"{kind}: {msg.get('error')}"
                    logger.warning("ElevenLabs speech to text refused: %s — back to captions", self.failed)
                    break
                elif kind and kind not in ("warning",) and msg.get("error"):
                    logger.warning("ElevenLabs speech to text: %s: %s", kind, str(msg.get("error"))[:200])
        except Exception as exc:  # noqa: BLE001 — the connection closed: the next piece reconnects
            logger.info("Speech to text stream ended (%s)", type(exc).__name__)
        finally:
            if self.ws is ws:
                self._dropped()

    def _dropped(self) -> None:
        ws, self.ws = self.ws, None
        self._retry_at = time.monotonic() + RETRY_S
        if ws is not None:
            asyncio.create_task(_quietly_close(ws))

    async def close(self) -> None:
        self.closed = True
        for t in (self._connecting, self._reader):
            if t and not t.done():
                t.cancel()
        if self.ws is not None:
            await _quietly_close(self.ws)
            self.ws = None


async def _quietly_close(ws) -> None:
    try:
        await ws.close()
    except Exception:  # noqa: BLE001
        pass


async def keyterms(workspace_id) -> List[str]:
    """Words to listen for: her name, the data products, and the places in this business's data (the cities it sells
    in, most orders first) — the names captions kept mishearing ("Bikonnell" for Bikaner)."""
    from sqlalchemy import select

    from kairos_kb.companion.vitals import event_column, live_model, run
    from kairos_kb.db.engine import async_session_factory
    from kairos_kb.models.data_product import DataProduct

    terms: List[str] = ["Jenny", "Kairos"]
    terms += [t.strip() for t in os.getenv("JENNY_STT_KEYTERMS", "").split(",") if t.strip()]
    try:
        async with async_session_factory() as db:
            products = (await db.execute(select(DataProduct).where(DataProduct.workspace_id == workspace_id))).scalars().all()
            for p in products:
                terms.append(p.name)
                ev = await event_column(db, p)
                model = live_model(p, {"table": ev[0], "column": ev[1]} if ev else None)
                count = next((m["name"] for m in model.get("metrics") or [] if m.get("additive")
                              and (m.get("unit") or "") == "count"), None)
                for d in model.get("dimensions") or []:
                    if not count or d.get("type") == "time" or d["name"].lower() not in ("city", "state", "region", "zone"):
                        continue
                    r = await run(db, model, [count], [d["name"]], order=f"{count} desc", limit=40)
                    terms += [str(row[0]) for row in r.get("rows") or [] if row and row[0]]
    except Exception:  # noqa: BLE001 — words to listen for are a nicety
        logger.exception("Couldn't gather speech to text keyterms")
    seen, out = set(), []
    for t in terms:
        k = t.strip()
        if k and len(k) <= KEYTERM_CHARS and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out[:MAX_KEYTERMS]
