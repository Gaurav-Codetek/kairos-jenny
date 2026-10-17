"""A meeting Jenny is in.

Her body (the jenny-meet service) sits in the Google Meet and talks to this session over a WebSocket: it reports
what the call is doing (asking to join, admitted, ended), the captions as they appear, the Meet chat, and when each
of her sentences starts and ends; it takes sentences to say (audio), scenes for her camera, chat messages to send,
and "stop" / "leave".

Quiet unless addressed: what others say is kept in the meeting's conversation; only words said to her (her name, a
follow-up from the person she just answered, or words pointing back at what she said — judged by Jev,
brain.meeting_read) start a turn. Her answer runs
through the same turn as anywhere else (tools, desk, claim gate, stage), with the meeting as context, and is said
sentence by sentence as the claim gate releases it. Someone talking over her stops her, the way a call does.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from kairos_kb.companion import brain, chat, claims, voice
from kairos_kb.db.engine import async_session_factory
from kairos_kb.exceptions import KairosException
from kairos_kb.meetings.hearing import Hearing, mentions_jenny, refers_to_her, split_at_name
from kairos_kb.models.companion import CompanionConversation, CompanionMessage

logger = logging.getLogger(__name__)

BODY_URL = os.getenv("JENNY_MEET_URL", "http://jenny-meet:7070")
API_WS = os.getenv("KAIROS_API_WS", "ws://api:8000")
NAME = os.getenv("JENNY_MEET_NAME", "Jenny (Kairos)")
TOKEN = os.getenv("JENNY_MEET_TOKEN", "").strip() or secrets.token_hex(16)  # the body proves it's ours
MAX_HOURS = 3
FOLLOW_S = 45        # right after she answers someone, their next words may be for her without her name
HOLD_S = 4.0         # someone stopped mid-thought ("Jenny, listen, actually I wanted…"): wait this long for the rest
TICK_S = 0.3
INTRO = ("Hi everyone, I'm Jenny, Kairos's AI assistant. I'm listening quietly. Say \"Jenny…\" or message me here to "
         "ask about the numbers.")
MEET_URL = re.compile(r"^https://meet\.google\.com/[a-z]{3,4}-[a-z]{4}-[a-z]{3,4}(?:[/?#].*)?$", re.I)
_TAG = re.compile(r"\[([a-z]+)\]\s*", re.I)
ENDED = ("left", "ended", "refused", "removed", "error")

SESSIONS: Dict[str, "MeetingSession"] = {}


def _plain(text: str) -> str:
    """Words for the Meet chat: no tone tags, no markdown."""
    t = _TAG.sub("", text or "")
    t = re.sub(r"[*_`#>]+", "", t)
    return re.sub(r"\s+\n", "\n", t).strip()


class MeetingSession:
    def __init__(self, workspace_id: uuid.UUID, url: str, conversation_id: uuid.UUID) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.workspace_id, self.url, self.conversation_id = workspace_id, url, conversation_id
        self.state, self.error = "starting", None
        self.started = datetime.now(timezone.utc)
        self.joined_at: Optional[datetime] = None
        self.participants: List[str] = []
        self.recent: List[str] = []                      # "Name: words", most recent last
        self.hearing = Hearing()
        self.ws = None
        self.speaking = False                            # a sentence of hers is playing
        self.answering = False
        self.waiting: Optional[Dict[str, str]] = None    # asked while she was answering: next
        self.answered: Dict[str, float] = {}             # speaker -> when she last answered them
        self.jenny_last = ""
        self.cut = False
        self.spoken: List[str] = []
        self._said = 0
        self._tick: Optional[asyncio.Task] = None
        self.sent_chat: set = set()                      # what she wrote in the Meet chat (never read as a question)
        self.held: Dict[str, Dict[str, Any]] = {}         # speaker -> an unfinished request, waiting for the rest

    # ── what the screen sees ──
    def view(self) -> Dict[str, Any]:
        return {"id": self.id, "url": self.url, "state": self.state, "error": self.error,
                "conversation_id": str(self.conversation_id), "participants": self.participants,
                "started_at": self.started.isoformat(), "joined_at": self.joined_at.isoformat() if self.joined_at else None,
                "speaking": self.speaking, "answering": self.answering, "recent": self.recent[-6:]}

    async def send(self, msg: Dict[str, Any]) -> None:
        if msg.get("type") == "chat_send":
            self.sent_chat.add(" ".join(str(msg.get("text") or "").split()))
        if self.ws is not None:
            try:
                await self.ws.send_text(json.dumps(msg))
            except Exception:  # noqa: BLE001 — the body went away; its disconnect is handled by attach()
                logger.debug("Couldn't reach Jenny's meeting body", exc_info=True)

    # ── the body's channel ──
    async def attach(self, ws) -> None:
        self.ws = ws
        if self.state == "starting":
            self.state = "joining"
        try:
            while True:
                evt = json.loads(await ws.receive_text())
                await self.on_event(evt)
        except Exception as exc:  # noqa: BLE001 — a closed socket ends the session
            logger.info("Meeting %s: body disconnected (%s)", self.id, type(exc).__name__)
        finally:
            self.ws = None
            if self.state not in ENDED:
                await self._ended("left")

    async def on_event(self, evt: Dict[str, Any]) -> None:
        kind = evt.get("type")
        if kind == "state":
            await self._state(str(evt.get("state")), evt.get("detail"))
        elif kind == "caption":
            self.hearing.caption(str(evt.get("block")), str(evt.get("speaker") or "Someone"), str(evt.get("text") or ""),
                                 time.monotonic())
        elif kind == "participants":
            self.participants = [p for p in (evt.get("names") or []) if not self.hearing.mine(p)][:50]
        elif kind == "chat":
            sender, text = str(evt.get("sender") or ""), str(evt.get("text") or "")
            flat = " ".join(text.split())
            if any(flat.startswith(t[:60]) or t[:60] in flat for t in self.sent_chat if t):
                return  # her own message (Meet adds its own words around it)
            if text and not self.hearing.mine(sender) and mentions_jenny(text):
                self._remember(sender, text)
                await chat.note_heard(self.conversation_id, sender, f"(in the chat) {text}")
                await self._ask(sender, text, "chat")
        elif kind == "spoken":
            if evt.get("event") == "start":
                if not self.speaking:
                    self.hearing.she_starts_speaking()
                self.speaking = True
            elif evt.get("event") in ("end", "stopped") and evt.get("last"):
                self.speaking = False
                await self.send({"type": "status", "status": "listening" if not self.answering else "thinking"})

    async def _state(self, state: str, detail: Any = None) -> None:
        logger.info("Meeting %s: %s %s", self.id, state, detail or "")
        if state == "in_meeting" and self.state != "in_meeting":
            self.state, self.joined_at = "in_meeting", datetime.now(timezone.utc)
            await self._note("Joined the Google Meet", "start")
            await self.send({"type": "chat_send", "text": INTRO})
            await self.send({"type": "status", "status": "listening"})
            self._tick = asyncio.create_task(self._listen())
        elif state in ENDED:
            await self._ended(state, str(detail) if detail else None)
        else:
            self.state = state

    async def _ended(self, state: str, detail: Optional[str] = None) -> None:
        was_in = self.state == "in_meeting"
        self.state, self.error = state, (detail if state in ("refused", "error") else self.error)
        if self._tick:
            self._tick.cancel()
        if was_in and self.joined_at:
            mins = int((datetime.now(timezone.utc) - self.joined_at).total_seconds() // 60)
            await self._note(f"Left the meeting · {mins} min", "end", mins * 60)

    async def _note(self, text: str, event: str, seconds: Optional[int] = None) -> None:
        async with async_session_factory() as db:
            db.add(CompanionMessage(conversation_id=self.conversation_id, role="call", text=text, voice=True,
                                    status="done", meta={"call": {"event": event, "seconds": seconds, "meet": True}},
                                    created_at=datetime.now(timezone.utc)))
            await db.commit()

    # ── listening ──
    async def _listen(self) -> None:
        while self.state == "in_meeting":
            await asyncio.sleep(TICK_S)
            now = time.monotonic()
            try:
                if self.speaking:
                    over = self.hearing.talking_over(now)
                    if over and not self.cut:
                        logger.info("Meeting %s: %s talked over Jenny: %r", self.id, over.speaker, over.text)
                        self.cut = True
                        await self.send({"type": "stop"})
                for u in self.hearing.due(now):
                    await self._heard(u.speaker, u.text)
                for speaker, h in list(self.held.items()):  # nothing more came: take what was said
                    if now - h["at"] >= HOLD_S:
                        self.held.pop(speaker, None)
                        await self._heard(speaker, h["text"], final=True)
                if datetime.now(timezone.utc) - self.started > timedelta(hours=MAX_HOURS):
                    await self.leave()
            except Exception:  # noqa: BLE001 — listening never stops on one bad line
                logger.exception("Meeting %s: listening failed", self.id)

    async def _heard(self, speaker: str, text: str, final: bool = False) -> None:
        """Words someone said, read the way a person in the room would: kept as heard; and if they're for her, the
        part from her name on is the question, with what came before as context (used only when it bears on it). If
        they stopped mid-thought she waits for the rest; "not you, Jenny" gets an apology; "…, right Jenny?" a plain
        yes or no."""
        held = self.held.pop(speaker, None)
        if held:
            text = f"{held['text']} {text}"
        before, ask = split_at_name(text)
        recently = time.monotonic() - self.answered.get(speaker, -1e9) < FOLLOW_S
        if not (mentions_jenny(ask) or recently or refers_to_her(ask) or self.speaking or self.answering):
            return await self._keep(speaker, text)
        r = await brain.meeting_read(speaker, ask, before, self.recent, self.jenny_last)
        if r is None:  # no Jev: her name at the start of the words is enough
            named = bool(re.match(r"^\W*(so\s+|hey\s+|ok\s+|okay\s+)?(jenny|jenni|jennie|jeni)\b", ask, re.I))
            r = {"addressed": 1.0 if named else 0.0, "finished": 1.0, "bears": 0.0, "agreement": 0.0, "dismisses": 0.0}
        if r["dismisses"] >= brain.DISMISSES and (self.speaking or self.answering or recently):
            if self.speaking:
                self.cut = True
                await self.send({"type": "stop"})
            await self._keep(speaker, text)
            return await self._ask(speaker, ask, "voice", dismissed=True)
        if r["addressed"] < brain.ADDRESSED:
            return await self._keep(speaker, text)
        if r["finished"] < brain.FINISHED and not final:
            self.held[speaker] = {"text": text, "at": time.monotonic()}  # wait for the rest of the thought
            return
        if before:
            await self._keep(speaker, before)
        self._remember(speaker, ask)
        await self._ask(speaker, ask, "voice", before=before, bears=r["bears"] >= brain.BEARS,
                        agreement=r["agreement"] >= brain.AGREES)

    async def _keep(self, speaker: str, text: str) -> None:
        self._remember(speaker, text)
        await chat.note_heard(self.conversation_id, speaker, text)

    def _remember(self, speaker: str, text: str) -> None:
        self.recent = (self.recent + [f"{speaker}: {text}"])[-20:]
        if speaker not in self.participants and not self.hearing.mine(speaker):
            self.participants.append(speaker)

    # ── answering ──
    async def _ask(self, speaker: str, words: str, channel: str, before: str = "", bears: bool = False,
                   agreement: bool = False, dismissed: bool = False) -> None:
        how = {"before": before, "bears": bears, "agreement": agreement, "dismissed": dismissed}
        if self.answering and not dismissed:
            self.waiting = {"speaker": speaker, "words": words, "channel": channel, **how}
            return
        self.answering = True
        asyncio.create_task(self._answer(speaker, words, channel, **how))

    async def _answer(self, speaker: str, words: str, channel: str, before: str = "", bears: bool = False,
                      agreement: bool = False, dismissed: bool = False) -> None:
        try:
            await self.send({"type": "status", "status": "thinking"})
            meeting = {"speaker": speaker, "participants": self.participants, "recent": self.recent[-8:],
                       "before": before, "bears": bears, "agreement": agreement, "dismissed": dismissed}
            view = await chat.start_turn(self.conversation_id, words, voice=channel == "voice", meeting=meeting)
            aid = next((m["id"] for m in reversed(view["messages"]) if m["role"] == "assistant" and m["pending"]), None)
            if aid is None:
                return
            self.cut, self.spoken = False, []
            m = await self._follow(uuid.UUID(aid), channel)
            if m is None:
                return
            self.answered[speaker] = time.monotonic()
            self.jenny_last = _plain(m.get("text") or "")
            if channel == "chat" and m.get("text"):
                await self.send({"type": "chat_send", "text": _plain(m["text"])[:1500]})
            if self.cut and self.spoken:
                await chat.mark_interrupted(self.conversation_id, uuid.UUID(aid), " ".join(self.spoken))
        except KairosException as exc:
            logger.info("Meeting %s: couldn't answer (%s)", self.id, exc.message)
            if dismissed:  # still finishing the last answer: say the apology straight away instead
                await self._say("Oh, my bad — I thought you were asking me.", None)
        except Exception:  # noqa: BLE001
            logger.exception("Meeting %s: answering failed", self.id)
        finally:
            self.answering = False
            if not self.speaking:
                await self.send({"type": "status", "status": "listening"})
            nxt, self.waiting = self.waiting, None
            if nxt and self.state == "in_meeting":
                await self._ask(nxt["speaker"], nxt["words"], nxt["channel"], nxt.get("before", ""),
                                nxt.get("bears", False), nxt.get("agreement", False))

    async def _follow(self, aid: uuid.UUID, channel: str) -> Optional[Dict[str, Any]]:
        """Follow her answer as it's written: each released sentence said in turn (voice), each scene to her camera."""
        sent: Dict[int, int] = {}
        shown: set = set()
        previous: Optional[str] = None
        m: Optional[Dict[str, Any]] = None
        for _ in range(int(180 / 0.25)):
            m = await chat.message(aid)
            if m is None:
                return None
            for sc in m.get("scenes") or []:
                if sc.get("id") not in shown:
                    shown.add(sc.get("id"))
                    await self.send({"type": "scene", "scene": sc})
            if channel == "voice" and not self.cut:
                parts = list(m.get("narration") or []) + [m["live"] if m["pending"] else m["text"]]
                for i, part in enumerate(parts):
                    finished = i < len(parts) - 1 or not m["pending"]
                    pieces = claims.sentences(part or "")
                    ready = pieces if finished else pieces[:-1]
                    for sentence in ready[sent.get(i, 0):]:
                        previous = await self._say(sentence, previous) or previous
                    sent[i] = max(sent.get(i, 0), len(ready))
            if not m["pending"]:
                return m
            await asyncio.sleep(0.25)
        return m

    async def _say(self, sentence: str, previous: Optional[str]) -> Optional[str]:
        first = _TAG.match(sentence.strip())
        tone = first.group(1).lower() if first else None
        text = _TAG.sub("", sentence).strip()
        if not voice.sayable(text) or self.cut:
            return None
        audio = await voice.speak(text, tone, previous=previous)
        if not audio or self.cut:
            return None
        self._said += 1
        self.spoken.append(text)
        await self.send({"type": "say", "id": self._said, "text": text, "audio": base64.b64encode(audio).decode()})
        return text

    async def leave(self) -> None:
        if self.ws is not None:
            await self.send({"type": "leave"})
        else:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    await c.delete(f"{BODY_URL}/sessions/{self.id}")
            except httpx.HTTPError:
                pass
            await self._ended("left")


# ── the sessions ─────────────────────────────────────────────────────


async def start(workspace_id: uuid.UUID, url: str) -> Dict[str, Any]:
    """Send Jenny to a Google Meet: a meeting conversation, then her body asks to join."""
    url = (url or "").strip()
    if not MEET_URL.match(url):
        raise KairosException("That doesn't look like a Google Meet link (https://meet.google.com/abc-defg-hij).",
                              status_code=422)
    live = [s for s in SESSIONS.values() if s.workspace_id == workspace_id and s.state not in ENDED]
    if live:
        raise KairosException("Jenny is already in a meeting for this business. Ask her to leave it first.",
                              status_code=409)
    async with async_session_factory() as db:
        now = datetime.now(timezone.utc)
        conv = CompanionConversation(workspace_id=workspace_id, history=[], last_at=now,
                                     title=f"Google Meet · {now.strftime('%d %b %H:%M')} UTC")
        db.add(conv)
        await db.commit()
        cid = conv.id
    s = MeetingSession(workspace_id, url, cid)
    SESSIONS[s.id] = s
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{BODY_URL}/sessions", json={
                "session_id": s.id, "url": url, "name": NAME,
                "api_ws": f"{API_WS}/api/v1/meetings/{s.id}/body?token={TOKEN}"})
            r.raise_for_status()
    except httpx.HTTPError as exc:
        s.state, s.error = "error", "Jenny's meeting client isn't running. Start it with: docker compose up -d jenny-meet"
        logger.warning("Meeting body unreachable: %s", exc)
        raise KairosException(s.error, status_code=503)
    return s.view()


def listing(workspace_id: uuid.UUID) -> List[Dict[str, Any]]:
    return [s.view() for s in sorted(SESSIONS.values(), key=lambda x: x.started, reverse=True)
            if s.workspace_id == workspace_id][:10]


def get(session_id: str) -> "MeetingSession":
    s = SESSIONS.get(session_id)
    if s is None:
        raise KairosException("No such meeting.", status_code=404)
    return s
