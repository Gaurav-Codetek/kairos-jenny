"""Companion endpoints — its live view, its moments, its settings, a pulse on demand, and conversation."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.companion import chat, scheduler
from kairos_kb.db.engine import get_db
from kairos_kb.exceptions import KairosException, NotFoundError
from kairos_kb.models.companion import CompanionPulse
from kairos_kb.models.living import AgentNote
from kairos_kb.models.workspace import Workspace

router = APIRouter(prefix="/companion", tags=["Companion"])


class Settings(BaseModel):
    enabled: Optional[bool] = None
    interval_seconds: Optional[int] = Field(None, ge=60, le=86400)
    tz_offset_minutes: Optional[int] = Field(None, ge=-14 * 60, le=14 * 60)


class NewChat(BaseModel):
    workspace_id: uuid.UUID


class Say(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    voice: bool = False  # on a call: a short, spoken answer
    interrupt: bool = False  # the owner cut in: stop whatever Jenny was saying or working out
    heard: str = Field("", max_length=4000)  # what the owner heard of it before cutting in
    speculation: Optional[str] = None  # the speculative turn started on these words during the pause, to confirm
    pointing: Optional[dict] = None  # what the owner is pointing at on Jenny's stage: {scene_id, key, label, title}
    answering: Optional[dict] = None  # the owner pressed Yes/No on an offer of hers: {message_id, answer: yes|no}


class Likely(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    voice: bool = True


def _note(n: AgentNote) -> dict:
    return {"id": str(n.id), "kind": n.kind, "signal": n.signal, "title": n.title, "body": n.body, "facts": n.facts,
            "status": n.status, "importance": n.importance, "confidence": n.confidence, "feedback": n.feedback,
            "period": n.period.isoformat() if n.period else None, "created_at": n.created_at.isoformat(),
            "updated_at": n.updated_at.isoformat() if n.updated_at else None}


@router.get("/state")
async def state(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Everything the Pulse screen shows: settings, snapshot, headline, moments, the day's timeline."""
    from kairos_kb.companion.pulse import interval_for

    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise NotFoundError("Workspace", str(workspace_id))
    st = await scheduler.state_for(db, ws.id)
    await db.commit()
    since = datetime.now(timezone.utc) - timedelta(days=2)
    notes = (await db.execute(select(AgentNote).where(
        AgentNote.workspace_id == ws.id, AgentNote.created_at >= since,
        AgentNote.kind.in_(("moment", "daily_briefing")) | AgentNote.signal.in_(("stalled", "flowing")))
        .order_by(AgentNote.created_at.desc()).limit(60))).scalars().all()
    pulses = (await db.execute(select(CompanionPulse).where(CompanionPulse.workspace_id == ws.id, CompanionPulse.as_of >= since)
                               .order_by(CompanionPulse.as_of.desc()).limit(300))).scalars().all()
    nxt_at = st.last_pulse_at + timedelta(seconds=interval_for(st)) if st.last_pulse_at else None
    nxt = nxt_at.isoformat() if nxt_at else None
    nxt_in = max(0, int((nxt_at - datetime.now(timezone.utc)).total_seconds())) if nxt_at else None
    return {
        "workspace": ws.name, "enabled": st.enabled, "interval_seconds": st.interval_seconds,
        "tz_offset_minutes": st.tz_offset_minutes, "tz_source": st.tz_source, "live": st.live,
        "status": "running" if str(ws.id) in scheduler.RUNNING else "idle", "error": st.error,
        "last_pulse_at": st.last_pulse_at.isoformat() if st.last_pulse_at else None, "next_pulse_at": nxt, "next_pulse_in_seconds": nxt_in,
        "headline": st.headline, "headline_at": st.headline_at.isoformat() if st.headline_at else None,
        "snapshot": st.snapshot, "vitals": st.vitals or [], "notes": [_note(n) for n in notes],
        "timeline": [{"as_of": p.as_of.isoformat(), "headline": p.headline, **(p.summary or {})} for p in pulses],
    }


@router.post("/pulse", status_code=202)
async def pulse_now(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Look now, instead of waiting for the next heartbeat."""
    if not await db.get(Workspace, workspace_id):
        raise NotFoundError("Workspace", str(workspace_id))
    if not scheduler.start_pulse(workspace_id, force=True):
        raise KairosException("I'm already looking at this connection.", status_code=409)
    return {"started": True}


@router.patch("/settings")
async def update_settings(workspace_id: uuid.UUID, body: Settings, db: AsyncSession = Depends(get_db)):
    if not await db.get(Workspace, workspace_id):
        raise NotFoundError("Workspace", str(workspace_id))
    st = await scheduler.state_for(db, workspace_id)
    if body.enabled is not None:
        st.enabled = body.enabled
    if body.interval_seconds is not None:
        st.interval_seconds = body.interval_seconds
    if body.tz_offset_minutes is not None:
        st.tz_offset_minutes, st.tz_source = body.tz_offset_minutes, "set"
    await db.commit()
    return {"enabled": st.enabled, "interval_seconds": st.interval_seconds, "tz_offset_minutes": st.tz_offset_minutes,
            "tz_source": st.tz_source}


@router.post("/vitals/derive")
async def rederive(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Choose the vitals again (e.g. after new data products), then look."""
    from kairos_kb.companion.vitals import choose

    st = await scheduler.state_for(db, workspace_id)
    st.vitals = await choose(db, workspace_id)
    await db.commit()
    scheduler.start_pulse(workspace_id, force=True)
    return {"vitals": st.vitals}


class CallEvent(BaseModel):
    event: str = Field(..., pattern="^(start|end)$")
    seconds: Optional[int] = Field(None, ge=0)


class Interrupted(BaseModel):
    heard: str = Field("", max_length=4000)


@router.post("/chat", status_code=201)
async def new_chat(body: NewChat, db: AsyncSession = Depends(get_db)):
    """A fresh conversation."""
    if not await db.get(Workspace, body.workspace_id):
        raise NotFoundError("Workspace", str(body.workspace_id))
    return await chat.create(body.workspace_id)


@router.get("/chat/latest")
async def latest_chat(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """The conversation to pick up after a refresh: the most recent one (or a new one)."""
    if not await db.get(Workspace, workspace_id):
        raise NotFoundError("Workspace", str(workspace_id))
    return await chat.latest(workspace_id)


@router.get("/chats")
async def list_chats(workspace_id: uuid.UUID):
    """Earlier conversations and calls, newest first."""
    return {"conversations": await chat.listing(workspace_id)}


@router.get("/chat/{conversation_id}")
async def get_chat(conversation_id: uuid.UUID):
    return await chat.view(conversation_id)


@router.post("/chat/{conversation_id}/messages", status_code=202)
async def say(conversation_id: uuid.UUID, body: Say):
    return await chat.start_turn(conversation_id, body.text.strip(), body.voice, body.interrupt, body.heard,
                                 body.speculation, body.pointing, body.answering)


@router.post("/chat/{conversation_id}/speculation", status_code=202)
async def speculate(conversation_id: uuid.UUID, body: Likely):
    """The owner paused and has likely finished: start on the turn now, hidden until confirmed."""
    return await chat.speculate(conversation_id, body.text.strip(), body.voice)


@router.delete("/chat/{conversation_id}/speculation", status_code=204)
async def drop_speculation(conversation_id: uuid.UUID):
    """The owner carried on: forget the speculative turn."""
    await chat.discard_speculation(conversation_id)


@router.post("/chat/{conversation_id}/calls")
async def call_event(conversation_id: uuid.UUID, body: CallEvent):
    """A call starting or ending: kept in the conversation's record."""
    return await chat.log_call(conversation_id, body.event, body.seconds)


@router.post("/chat/{conversation_id}/messages/{message_id}/interrupted")
async def interrupted(conversation_id: uuid.UUID, message_id: uuid.UUID, body: Interrupted):
    """An answer cut off on a call, with what was heard before the cut."""
    return await chat.mark_interrupted(conversation_id, message_id, body.heard)


# ── Jenny's voice (open-source text to speech beside Kairos) ─────────


class Speak(BaseModel):
    text: str = Field(..., min_length=1, max_length=600)
    tone: Optional[str] = Field(None, max_length=20)
    previous: Optional[str] = Field(None, max_length=600)  # the sentence just before, for flowing intonation


class Warm(BaseModel):
    phrases: list[str] = Field(default_factory=list, max_length=40)


@router.get("/voice")
async def voice_info():
    """Whether Jenny's own voice is up (otherwise the screen uses the browser's)."""
    from kairos_kb.companion import voice

    return await voice.info()


@router.post("/voice/speak")
async def voice_speak(body: Speak):
    """One phrase, spoken: MP3 audio."""
    from fastapi.responses import Response

    from kairos_kb.companion import voice

    audio = await voice.speak(body.text, body.tone, previous=body.previous)
    if audio is None:
        raise KairosException("The voice service couldn't say that.", status_code=503)
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/voice/stream")
async def voice_stream(text: str = Query(..., min_length=1, max_length=600), tone: Optional[str] = Query(None, max_length=20),
                       previous: Optional[str] = Query(None, max_length=600)):
    """One phrase, streamed as it's made (an audio element plays it as it arrives): for the first thing she says
    in an answer, where waiting for the whole phrase is what you'd hear."""
    from fastapi.responses import StreamingResponse

    from kairos_kb.companion import voice

    return StreamingResponse(voice.stream(text, tone, previous), media_type="audio/mpeg",
                             headers={"Cache-Control": "no-store"})


@router.post("/voice/warm", status_code=202)
async def voice_warm(body: Warm):
    """Say the everyday phrases ahead of time (in the background), so they play instantly on a call."""
    import asyncio

    from kairos_kb.companion import voice

    asyncio.create_task(voice.warm([p[:120] for p in body.phrases if p.strip()]))
    return {"warming": len(body.phrases)}


# ── Jenny speaks first: raising what matters, and a welcome with what changed ─────────


class Raise(BaseModel):
    note_id: uuid.UUID
    voice: bool = False


@router.get("/raises")
async def raises(workspace_id: uuid.UUID, on_call: bool = False):
    """What Jenny should bring up herself now: recent, material moments not yet raised. A call asks with on_call=true
    every few seconds, so what she finds meanwhile is said live rather than left as a voice note."""
    from kairos_kb.companion import initiative

    if on_call:
        initiative.on_call(workspace_id)
    return {"raises": await initiative.pending(workspace_id)}


@router.get("/desk")
async def desk_items(workspace_id: uuid.UUID):
    """Jenny's desk: the watches and checks she has committed to (open, and what closed in the last day)."""
    from kairos_kb.companion import desk

    return {"items": await desk.listing(workspace_id), "standing": desk.STANDING}


@router.delete("/desk/{item_id}")
async def desk_drop(item_id: uuid.UUID, workspace_id: uuid.UUID):
    """Take an item off her desk."""
    from kairos_kb.companion import desk

    return await desk.call(workspace_id, "drop_watch", {"id": str(item_id)})


class Seen(BaseModel):
    ids: list[uuid.UUID]


@router.post("/notes/seen")
async def notes_seen(body: Seen):
    """She has told the owner these (in a welcome): not raised again."""
    from kairos_kb.companion import initiative

    await initiative.mark_seen(body.ids)
    return {"ok": True}


@router.get("/voice-notes")
async def voice_notes():
    """The voice notes Jenny left while the owner was away, not yet played."""
    from kairos_kb.companion import initiative

    return {"notes": await initiative.voice_notes()}


@router.get("/voice-notes/{message_id}/audio")
async def voice_note_audio(message_id: uuid.UUID):
    from fastapi.responses import FileResponse

    from kairos_kb.companion import initiative
    from kairos_kb.exceptions import KairosException

    path = initiative.audio_file(message_id)
    if path is None:
        raise KairosException("No recording for this note.", status_code=404)
    return FileResponse(path, media_type="audio/mpeg")


@router.post("/voice-notes/{message_id}/heard")
async def voice_note_heard(message_id: uuid.UUID):
    from kairos_kb.companion import initiative

    await initiative.heard(message_id)
    return {"ok": True}


@router.post("/chat/{conversation_id}/raise", status_code=202)
async def raise_moment(conversation_id: uuid.UUID, body: Raise):
    """Jenny brings a moment up herself, as a message in the conversation (spoken, on a call)."""
    from kairos_kb.companion import initiative

    return await initiative.start_raise(conversation_id, body.note_id, body.voice)


@router.get("/welcome")
async def welcome(workspace_id: uuid.UUID, conversation_id: Optional[uuid.UUID] = None):
    """How a call opens: what changed since the owner was last here, in a sentence or two."""
    from kairos_kb.companion import initiative

    return await initiative.welcome(workspace_id, conversation_id)


# ── Jack: the same business through an ElevenLabs Agent (an experiment beside Jenny) ─────────


class JackSession(BaseModel):
    workspace_id: uuid.UUID


class JackTool(BaseModel):
    workspace_id: uuid.UUID
    name: str = Field(..., max_length=64)
    args: dict = Field(default_factory=dict)


@router.get("/jack/status")
async def jack_status():
    """Whether Jack (the ElevenLabs agent experiment) is switched on; the panel offers him only then."""
    from kairos_kb.companion import jack

    return {"enabled": jack.ENABLED}


@router.post("/jack/session")
async def jack_session(body: JackSession):
    """Start a call with Jack: a short-lived ElevenLabs conversation token and the business's clock for his prompt."""
    from kairos_kb.companion import jack

    return await jack.session(body.workspace_id)


@router.post("/jack/tool")
async def jack_tool(body: JackTool):
    """One of Jack's tools (data products and the live pulse only), run for the browser on his behalf."""
    from kairos_kb.companion import jack

    return {"result": await jack.run_tool(body.workspace_id, body.name, body.args)}


class TurnSoFar(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    jenny_last: str = Field("", max_length=2000)


@router.post("/turn/finished")
async def turn_finished(body: TurnSoFar):
    """Has the owner finished speaking? (0–1, from their words so far) — for Jenny's turn-taking on a call."""
    import time as _time

    from kairos_kb.companion import brain

    t0 = _time.perf_counter()
    p = await brain.finished(body.text, body.jenny_last)
    return {"done": p, "ms": round((_time.perf_counter() - t0) * 1000)}


@router.post("/turn/audio")
async def turn_audio(request: Request):
    """Has the owner finished speaking? (0–1, from how they said it): the body is the last few seconds of their
    voice, 16 kHz mono 16-bit PCM, ending now. Smart Turn reads the intonation and pace; Jev reads the words."""
    import time as _time

    from kairos_kb.companion import smart_turn

    pcm = await request.body()
    if len(pcm) > 16000 * 2 * 9:
        raise KairosException("At most eight seconds of audio.", status_code=413)
    t0 = _time.perf_counter()
    p = await smart_turn.probability(pcm)
    return {"done": p, "ms": round((_time.perf_counter() - t0) * 1000)}
