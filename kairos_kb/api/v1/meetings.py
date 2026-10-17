"""Jenny in meetings: send her to a Google Meet, see how it's going, ask her to leave; and the channel her meeting
client (the jenny-meet service) talks to her through."""

from __future__ import annotations

import secrets
import uuid

import httpx
from fastapi import APIRouter, WebSocket
from pydantic import BaseModel, Field

from kairos_kb.exceptions import KairosException
from kairos_kb.meetings import session

router = APIRouter(prefix="/meetings", tags=["Meetings"])


class Join(BaseModel):
    workspace_id: uuid.UUID
    url: str = Field(..., min_length=10, max_length=300)


@router.post("", status_code=201)
async def join(body: Join):
    """Send Jenny to a Google Meet: she asks to join as "Jenny (Kairos)", and the host admits her."""
    return await session.start(body.workspace_id, body.url)


# ── her own Google account (signed in once, by the owner, on her meeting machine) ──

async def _body(method: str, path: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.request(method, f"{session.BODY_URL}{path}")
    except httpx.HTTPError:
        raise KairosException("Jenny's meeting client isn't running. Start it with: docker compose up -d jenny-meet",
                              status_code=503)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise KairosException(str(data.get("error") or "Her meeting client couldn't do that."), status_code=r.status_code)
    return data


@router.get("/identity")
async def identity():
    """Whether Jenny has her own Google account signed in (and which), or joins as a guest."""
    return await _body("GET", "/identity")


@router.post("/identity/sign-in")
async def sign_in():
    """Open the one-time sign-in screen: returns the address to open it at (this computer only)."""
    return await _body("POST", "/identity/sign-in")


@router.post("/identity/done")
async def sign_in_done():
    """Close the sign-in screen and check she's signed in."""
    return await _body("POST", "/identity/done")


@router.delete("/identity")
async def sign_out():
    """Forget her account (meetings fall back to joining as a guest)."""
    return await _body("DELETE", "/identity")


@router.get("")
async def meetings(workspace_id: uuid.UUID):
    """Her meetings for this business: the one she's in (or joining), and recent ones."""
    return {"meetings": session.listing(workspace_id)}


@router.delete("/{session_id}")
async def leave(session_id: str):
    s = session.get(session_id)
    await s.leave()
    return s.view()


@router.websocket("/{session_id}/body")
async def body(ws: WebSocket, session_id: str, token: str = ""):
    """Her meeting client's channel: events in (call state, captions, chat, her speech), commands out."""
    s = session.SESSIONS.get(session_id)
    if s is None or not secrets.compare_digest(token, session.TOKEN):
        await ws.close(code=4403)
        return
    await ws.accept()
    await s.attach(ws)
