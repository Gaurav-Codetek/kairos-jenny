"""Jenny speaks first: what matters is raised before the owner asks, and a call opens with what changed since they
last talked. Her mission (see chat.SYSTEM): I watch the business so the owner doesn't have to, and I tell them what
matters before they have to ask.

  raise     a material moment the pulse found (a real gap, a stream that stopped) is brought up by Jenny herself:
            on a call at the next pause, otherwise as a message in the conversation. Only what's worth an
            interruption (importance RAISE_AT and up), only recent (FRESH_MIN), and only once (the note is marked seen).
  welcome   a call opens with what changed since the owner was last here, in a sentence or two, instead of a generic
            hello. The screen asks for it ahead of the call (it takes a few seconds to word), and marks what it
            mentions as told (mark_seen) only once she has said it — then it isn't raised again.
  look first  before she raises a moment, she looks into it with her tools (desk.investigate): where it sits, since
            when, spreading or one outlier — so she tells the owner what she found, not what she'd check next.
  voice note  when the owner isn't on a call, Jenny doesn't wait: after a pulse finds something material she records a
            short voice note (her own voice, saved as audio) and leaves it in the conversation, unheard, for the next
            time they open Kairos. The heartbeat (scheduler) runs on the server, so she keeps watching with no screen
            open.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from kairos_kb.db.engine import async_session_factory
from kairos_kb.exceptions import KairosException
from kairos_kb.models.companion import CompanionConversation, CompanionMessage
from kairos_kb.models.living import AgentNote

logger = logging.getLogger(__name__)

RAISE_AT = 6          # importance worth interrupting the owner for (strong gaps, stalls, sharp hours)
WELCOME_AT = 4        # worth mentioning when they come back
FRESH_MIN = 45        # an interruption is about something from the last 45 minutes
KINDS = ("moment", "data_issue")
LIVE = ("open", "provisional", "confirmed")
NOTE_WINDOW_H = 6     # a voice note can be about anything material from the last few hours not yet told
NOTE_COOL_MIN = 20    # at most one voice note per 20 minutes; what's new in between waits and is told together
ON_CALL_S = 60        # a call checks in every 15 s; quiet for a minute means it has ended
LOOK_PER_PULSE = 2    # moments looked into per pulse (each is a few lookups)
LOOK_WAIT_MIN = 4     # a moment she couldn't look into within this long is raised as it is
NOTE_WORDS = 70       # a voice note longer than this is tightened before it's recorded
NOTES_DIR = Path(os.getenv("JENNY_NOTES_DIR", "data/voice_notes"))
_on_call: Dict[str, float] = {}
_TAG = re.compile(r"\[([a-z]+)\]\s*", re.I)


def on_call(workspace_id) -> None:
    """A call is open: what she raises is said live on it, not left as a voice note."""
    _on_call[str(workspace_id)] = time.monotonic()


def calling(workspace_id) -> bool:
    return time.monotonic() - _on_call.get(str(workspace_id), -1e9) < ON_CALL_S


async def pending(workspace_id) -> List[Dict[str, Any]]:
    """What Jenny should raise now: recent, material, unresolved, not raised or mentioned before."""
    since = datetime.now(timezone.utc) - timedelta(minutes=FRESH_MIN)
    async with async_session_factory() as db:
        notes = (await db.execute(select(AgentNote).where(
            AgentNote.workspace_id == workspace_id, AgentNote.kind.in_(KINDS), AgentNote.importance >= RAISE_AT,
            AgentNote.created_at >= since, AgentNote.seen.is_(False), AgentNote.status.in_(LIVE))
            .order_by(AgentNote.importance.desc(), AgentNote.created_at.desc()).limit(6))).scalars().all()
    ready = [n for n in notes if _found(n) or datetime.now(timezone.utc) - n.created_at > timedelta(minutes=LOOK_WAIT_MIN)]
    return [{"id": str(n.id), "kind": n.kind, "title": n.title, "importance": n.importance,
             "at": n.created_at.isoformat()} for n in ready[:3]]


def _found(n: AgentNote) -> str:
    return ((n.facts or {}).get("investigation") or "") if isinstance(n.facts, dict) else ""


async def look_into_new(workspace_id) -> int:
    """After a pulse: the material moments she hasn't looked into yet, looked into (a few per pulse)."""
    from kairos_kb.companion import desk

    since = datetime.now(timezone.utc) - timedelta(hours=2)
    async with async_session_factory() as db:
        notes = (await db.execute(select(AgentNote).where(
            AgentNote.workspace_id == workspace_id, AgentNote.kind.in_(KINDS), AgentNote.importance >= RAISE_AT,
            AgentNote.created_at >= since, AgentNote.seen.is_(False), AgentNote.status.in_(LIVE))
            .order_by(AgentNote.importance.desc()).limit(10))).scalars().all()
        todo = [(n.id, n.title, n.body or "") for n in notes if not _found(n)][:LOOK_PER_PULSE]
    for nid, title, body in todo:
        try:
            found = await desk.investigate(workspace_id, (
                f"You noticed: {title}. {body} Look into it before telling the owner: where it sits, since when, and "
                "whether it's spreading or one outlier."))
        except Exception:  # noqa: BLE001 — raised as it is
            logger.exception("Couldn't look into a moment")
            found = ""
        async with async_session_factory() as db:
            n = await db.get(AgentNote, nid)
            if n is not None:
                n.facts = {**(n.facts or {}), "investigation": found or "(couldn't look further)"}
                await db.commit()
    return len(todo)


async def _vet(workspace_id, text: str, found: str, voice: bool) -> str:
    """What she's about to say, through the claim gate: nothing promised or claimed that nothing backs."""
    from kairos_kb.companion import claims, desk

    try:
        return await claims.vet(workspace_id, text, claims.backing(await desk.lines(workspace_id), found=found), voice)
    except Exception:  # noqa: BLE001
        logger.exception("Couldn't vet a line")
        return text


async def _say(workspace_id, instruction: str, voice: bool) -> str:
    """One short line in Jenny's own voice and persona (no tools)."""
    from kairos_kb.companion import chat

    async with async_session_factory() as db:
        ctx = await chat._context(db, workspace_id)

    async def nothing(_t: str) -> None:
        return None

    system = chat.SYSTEM.format(**ctx) + (chat.VOICE_MODE if voice else "")
    from kairos_kb.evals.connector_eval import _client, default_model

    out = await chat._stream_turn(_client(), default_model(), system, [{"role": "user", "content": instruction}], [],
                                  True, nothing, "minimal")
    return (out.get("text") or "").strip()


async def start_raise(conversation_id: uuid.UUID, note_id: uuid.UUID, voice: bool) -> Dict[str, Any]:
    """Jenny brings up a moment herself, as a message in the conversation (spoken, on a call). Returns the view, with
    the new answer pending while she words it."""
    from kairos_kb.companion import chat

    key = str(conversation_id)
    if key in chat.RUNNING:
        raise KairosException("I'm in the middle of an answer.", status_code=409)
    async with async_session_factory() as db:
        conv = await db.get(CompanionConversation, conversation_id)
        note = await db.get(AgentNote, note_id)
        if conv is None or note is None:
            raise KairosException("No such conversation or moment.", status_code=404)
        if note.seen:
            return await chat.view(conversation_id)
        note.seen = True
        m = CompanionMessage(conversation_id=conv.id, role="assistant", text="", voice=voice, status="pending", steps=[],
                             created_at=datetime.now(timezone.utc),
                             meta={"proactive": {"note": str(note.id), "title": note.title, "kind": note.kind}})
        db.add(m)
        conv.last_at = datetime.now(timezone.utc)
        await db.commit()
        mid, workspace_id, title, body, found = m.id, conv.workspace_id, note.title, note.body or "", _found(note)
    chat.RUNNING.add(key)
    asyncio.create_task(_word_raise(conversation_id, mid, workspace_id, title, body, voice, found))
    return await chat.view(conversation_id)


async def _word_raise(conversation_id, message_id, workspace_id, title: str, body: str, voice: bool,
                      found: str = "") -> None:
    from kairos_kb.companion import chat

    try:
        text = await _say(workspace_id, (
            "(This isn't the owner speaking. You're raising something yourself, because it matters — your mission is "
            "to tell them before they have to ask.) In two or three short sentences: open with a brief, polite "
            "interruption, say what changed and how much, and what you found when you looked into it. Offer a next "
            "step only if there's a real decision for the owner. What you noticed: "
            f"{title}. {body}" + (f" What you found looking into it: {found}" if found else "")), voice)
        text = await _vet(workspace_id, text, found, voice)
    except Exception:  # noqa: BLE001 — fall back to the moment's own words
        logger.exception("Couldn't word a raise")
        text = f"A quick heads-up: {title}."
    try:
        async with async_session_factory() as db:
            m = await db.get(CompanionMessage, message_id)
            conv = await db.get(CompanionConversation, conversation_id)
            if m is not None and m.status == "pending":
                m.text, m.status = text or f"A quick heads-up: {title}.", "done"
            if conv is not None:
                conv.history = list(conv.history or []) + [{"role": "assistant", "content": m.text if m else text}]
            await db.commit()
        await chat.mark_offer(message_id, text)
    finally:
        chat.RUNNING.discard(str(conversation_id))


def _ago(delta: timedelta) -> str:
    mins = int(delta.total_seconds() // 60)
    if mins < 90:
        return f"{mins} minutes"
    hours = mins // 60
    return f"{hours} hours" if hours < 36 else f"{hours // 24} days"


async def welcome(workspace_id, conversation_id: Optional[uuid.UUID]) -> Dict[str, Any]:
    """How a call opens: what changed since the owner was last here (or where the day stands), in a sentence or two."""
    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        last = (await db.execute(select(CompanionMessage.created_at).join(
            CompanionConversation, CompanionConversation.id == CompanionMessage.conversation_id).where(
            CompanionConversation.workspace_id == workspace_id, CompanionMessage.role == "user",
            CompanionMessage.status == "done").order_by(CompanionMessage.created_at.desc()).limit(1))).scalar()
        since = last or (now - timedelta(hours=12))
        notes = (await db.execute(select(AgentNote).where(
            AgentNote.workspace_id == workspace_id, AgentNote.kind.in_((*KINDS, "daily_briefing")),
            AgentNote.importance >= WELCOME_AT, AgentNote.created_at >= since, AgentNote.seen.is_(False))
            .order_by(AgentNote.importance.desc(), AgentNote.created_at.desc()).limit(5))).scalars().all()
        mentioned = [n.id for n in notes]
    gap = f" after {_ago(now - last)}" if last and now - last > timedelta(minutes=30) else ""
    changes = "; ".join(n.title for n in notes)
    instruction = (
        "(This isn't the owner speaking: they've just started a call with you.) Greet them in one or two short "
        f"sentences, the way you would when they come back{gap}. "
        + (f"Since they were last here: {changes}. Give the one or two that matter most, in plain words."
           if changes else "Nothing material changed since they were last here: say so in a few words, or say where "
                           "the day stands in your own words (never the status line's wording).")
        + " Then invite their question. No lists.")
    try:
        text = await asyncio.wait_for(_say(workspace_id, instruction, True), timeout=10)
    except Exception:  # noqa: BLE001 — the screen has its own greeting
        return {"text": None, "notes": []}
    return {"text": text or None, "notes": [str(i) for i in mentioned]}


async def mark_seen(note_ids: List[uuid.UUID]) -> None:
    """She has said these (in a welcome): told once, not raised again."""
    async with async_session_factory() as db:
        for nid in note_ids:
            n = await db.get(AgentNote, nid)
            if n is not None:
                n.seen = True
        await db.commit()


# ── voice notes: what she'd have said, recorded for when the owner is back ─────────


def _audio_path(message_id) -> Path:
    return NOTES_DIR / f"{message_id}.mp3"


async def after_pulse(workspace_id) -> Optional[uuid.UUID]:
    """After each pulse: if something material is untold and the owner isn't on a call, record a voice note."""
    if calling(workspace_id):
        return None  # the call raises it live
    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        notes = (await db.execute(select(AgentNote).where(
            AgentNote.workspace_id == workspace_id, AgentNote.kind.in_(KINDS), AgentNote.importance >= RAISE_AT,
            AgentNote.created_at >= now - timedelta(hours=NOTE_WINDOW_H), AgentNote.seen.is_(False),
            AgentNote.status.in_(LIVE)).order_by(AgentNote.importance.desc(), AgentNote.created_at.desc())
            .limit(6))).scalars().all()
        notes = [n for n in notes if _found(n) or now - n.created_at > timedelta(minutes=LOOK_WAIT_MIN)][:3]
        if not notes:
            return None
        recent = (await db.execute(select(CompanionMessage.meta).join(
            CompanionConversation, CompanionConversation.id == CompanionMessage.conversation_id).where(
            CompanionConversation.workspace_id == workspace_id, CompanionMessage.role == "assistant",
            CompanionMessage.created_at >= now - timedelta(minutes=NOTE_COOL_MIN)))).scalars().all()
        if any(((m or {}).get("proactive") or {}).get("recorded") for m in recent):
            return None  # one note at a time; the next pulse after the cool-down tells what's new together
        told = [(n.id, n.title, (n.body or "") + (f" What I found looking into it: {_found(n)}" if _found(n) else ""),
                 n.kind) for n in notes]
        for n in notes:
            n.seen = True  # claimed now, so a second pulse can't record the same thing
        await db.commit()
    try:
        return await _record(workspace_id, told)
    except Exception:  # noqa: BLE001 — not told after all: the next pulse tries again
        logger.exception("Couldn't record a voice note")
        async with async_session_factory() as db:
            for nid, *_ in told:
                n = await db.get(AgentNote, nid)
                if n is not None:
                    n.seen = False
            await db.commit()
        return None


async def _record(workspace_id, told) -> uuid.UUID:
    what = " / ".join(f"{t}. {b}".strip() for _, t, b, _ in told)
    said = await _say(workspace_id, (
        "(This isn't the owner speaking. They're away, and you're leaving them a short voice note to hear when they're "
        "back — your mission is to tell them what matters before they have to ask.) In two or three short sentences: "
        "say what changed and how much (the most important first) and what you found when you looked into it. Offer "
        "a next step only if there's a real decision for the owner. Don't greet at length or sign off. What you "
        f"noticed: {what}"), True)
    said = said or f"A quick note: {told[0][1]}."
    said = await _vet(workspace_id, said, what, True)
    if len(_TAG.sub("", said).split()) > NOTE_WORDS:  # a note is something you listen to: keep it short
        shorter = await _say(workspace_id, (
            "(Not the owner speaking.) Make this voice note shorter: at most sixty words, keeping what changed, how "
            "much, and what you found; drop the rest. Reply with the note only. The note: " + said), True)
        said = shorter or said
    first = _TAG.match(said)
    tone = first.group(1).lower() if first else None
    text = _TAG.sub("", said).strip()
    audio = await _record_whole(text, tone)
    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        conv = (await db.execute(select(CompanionConversation).where(
            CompanionConversation.workspace_id == workspace_id,
            ~CompanionConversation.title.like("Google Meet ·%")).order_by(  # not into a meeting's transcript
            CompanionConversation.last_at.desc()).limit(1))).scalars().first()
        if conv is None:
            conv = CompanionConversation(workspace_id=workspace_id, history=[], last_at=now)
            db.add(conv)
            await db.flush()
        m = CompanionMessage(conversation_id=conv.id, role="assistant", text=text, voice=True, status="done", steps=[],
                             created_at=now,
                             meta={"proactive": {"recorded": True, "heard": False, "audio": bool(audio),
                                                 "notes": [str(i) for i, *_ in told], "title": told[0][1],
                                                 "kind": told[0][3]}})
        db.add(m)
        conv.history = list(conv.history or []) + [{"role": "assistant", "content": text}]
        conv.last_at = now
        await db.commit()
        mid = m.id
    if audio:
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        _audio_path(mid).write_bytes(audio)
    from kairos_kb.companion import chat

    await chat.mark_offer(mid, text)
    logger.info("Jenny left a voice note (%s): %s", "audio" if audio else "text only", told[0][1])
    return mid


async def _record_whole(text: str, tone: Optional[str]) -> Optional[bytes]:
    """The whole note as audio: said in pieces of a few sentences (the voice takes up to 600 characters at a time),
    each carrying on from the one before; MP3 pieces join end to end."""
    from kairos_kb.companion import claims, voice

    pieces, cur = [], ""
    for sentence in claims.sentences(text):
        if cur and len(cur) + len(sentence) > 550:
            pieces.append(cur.strip())
            cur = ""
        cur += sentence
    if cur.strip():
        pieces.append(cur.strip())
    out, previous = b"", None
    for piece in pieces:
        audio = await voice.speak(piece, tone, previous=previous)
        if not audio:
            return out or None
        out += audio
        previous = piece
    return out or None


async def voice_notes(limit: int = 10) -> List[Dict[str, Any]]:
    """The voice notes she left that haven't been played yet, newest first."""
    since = datetime.now(timezone.utc) - timedelta(days=7)
    async with async_session_factory() as db:
        rows = (await db.execute(select(CompanionMessage, CompanionConversation.workspace_id).join(
            CompanionConversation, CompanionConversation.id == CompanionMessage.conversation_id).where(
            CompanionMessage.role == "assistant", CompanionMessage.created_at >= since)
            .order_by(CompanionMessage.created_at.desc()).limit(300))).all()
    out = []
    for m, wid in rows:
        pro = (m.meta or {}).get("proactive") or {}
        if pro.get("recorded") and not pro.get("heard"):
            out.append({"id": str(m.id), "conversation_id": str(m.conversation_id), "workspace_id": str(wid),
                        "text": m.text, "title": pro.get("title"), "kind": pro.get("kind"),
                        "audio": bool(pro.get("audio")) and _audio_path(m.id).exists(),
                        "at": m.created_at.isoformat()})
    return out[:limit]


def audio_file(message_id: uuid.UUID) -> Optional[Path]:
    path = _audio_path(message_id)
    return path if path.exists() else None


async def heard(message_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        m = await db.get(CompanionMessage, message_id)
        if m is None:
            raise KairosException("No such voice note.", status_code=404)
        meta = dict(m.meta or {})
        meta["proactive"] = {**(meta.get("proactive") or {}), "heard": True}
        m.meta = meta
        await db.commit()
