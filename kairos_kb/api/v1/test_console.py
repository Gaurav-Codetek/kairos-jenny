"""Test screen endpoints — chat with an agent over a Kairos MCP connector, and watch what happens."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from kairos_kb.evals.connector_eval import known_connector
from kairos_kb.exceptions import KairosException, NotFoundError
from kairos_kb.playground import session as console

router = APIRouter(prefix="/test", tags=["Test console"])


class NewSession(BaseModel):
    connector: str = "v2"


class SwitchConnector(BaseModel):
    connector: str


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def _get(session_id: str):
    s = console.SESSIONS.get(session_id)
    if s is None:
        raise NotFoundError("Test session", session_id)
    return s


def _check(connector: str) -> None:
    if not known_connector(connector):
        raise KairosException(f"Unknown connector '{connector}'. Use v1, v2 or c:<connection>.", status_code=400)


@router.get("/connectors")
async def list_connectors():
    """Every MCP endpoint the console can chat through."""
    return {"connectors": await console.connectors()}


@router.post("/sessions", status_code=201)
async def create_session(body: NewSession):
    _check(body.connector)
    return console.view(console.new_session(body.connector))


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, after: int = Query(0, ge=0)):
    """The conversation, and the trace from event `after` on (poll with the last trace_total)."""
    return console.view(_get(session_id), after)


@router.patch("/sessions/{session_id}")
async def switch_connector(session_id: str, body: SwitchConnector):
    """Change the connector; the conversation carries on through the new one."""
    s = _get(session_id)
    _check(body.connector)
    if s["status"] == "running":
        raise KairosException("Wait for the current answer before switching the connector.", status_code=409)
    console.switch(s, body.connector)
    return console.view(s)


@router.post("/sessions/{session_id}/messages", status_code=202)
async def send_message(session_id: str, body: Message):
    """Ask the agent. It answers in the background; poll the session for the trace and the answer."""
    s = _get(session_id)
    if s["status"] == "running":
        raise KairosException("The agent is still answering the previous message.", status_code=409)
    console.start_turn(s, body.text.strip())
    return console.view(s)


@router.get("/sessions/{session_id}/audit")
async def get_audit(session_id: str):
    """What Kairos's audit log recorded for the console's agent during this session."""
    return {"audit": await console.audit(_get(session_id))}
