"""Who is calling, what they may see, and a record of what they did.

Every agent gets its own key. The key identifies the agent in the audit
trail, limits it to the workspaces it was granted, and decides whether it
may run costed actions. Keys are shown once and stored only as a hash.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Set

from sqlalchemy import select, update

from kairos_kb.config import get_settings
from kairos_kb.db.engine import async_session_factory
from kairos_kb.models.context import AgentActivity, AgentClient
from kairos_kb.models.workspace import Workspace

logger = logging.getLogger(__name__)

KEY_PREFIX = "kai_"


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: Optional[uuid.UUID]
    name: str
    scopes: frozenset = frozenset({"read"})
    # None: every workspace. Otherwise the workspace UUIDs and names allowed.
    workspace_ids: Optional[frozenset] = None
    workspace_names: Optional[frozenset] = None
    channel: str = "mcp"
    # Catalogs this agent may query with run_sql; None: no per-agent limit.
    sql_catalogs: Optional[frozenset] = None

    def can(self, scope: str) -> bool:
        return scope in self.scopes

    def sees_workspace_name(self, name: str) -> bool:
        return self.workspace_names is None or name in self.workspace_names

    def sees_entity(self, entity_id: str) -> bool:
        parts = entity_id.split(":")
        return len(parts) < 2 or self.sees_workspace_name(parts[1])


ANONYMOUS = AgentIdentity(agent_id=None, name="anonymous", scopes=frozenset({"read"}))

_current: contextvars.ContextVar[AgentIdentity] = contextvars.ContextVar("kairos_agent", default=ANONYMOUS)


def current_agent() -> AgentIdentity:
    return _current.get()


def set_current_agent(identity: AgentIdentity):
    return _current.set(identity)


# ── keys ─────────────────────────────────────────────────────────────


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def key_from_headers(headers: Dict[str, str]) -> Optional[str]:
    """Authorization: Bearer <key>, or X-Kairos-Key: <key>."""
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return (headers.get("x-kairos-key") or "").strip() or None


class AccessDenied(Exception):
    pass


def anonymous_scopes() -> frozenset:
    """What a caller without a key may do, from settings. Always at least the map."""
    listed = {x.strip() for x in get_settings().anonymous_scopes.split(",") if x.strip()}
    return frozenset(listed | {"read"})


async def resolve_identity(key: Optional[str], channel: str) -> AgentIdentity:
    """The agent a key belongs to. Raises AccessDenied when the key is not acceptable."""
    mode = get_settings().agent_auth_mode.lower()
    if mode == "off":
        return AgentIdentity(agent_id=None, name="anonymous", scopes=anonymous_scopes(), channel=channel)
    if not key:
        if mode == "required":
            raise AccessDenied("An agent key is required. Create one on the Agents screen.")
        return AgentIdentity(agent_id=None, name="anonymous", scopes=anonymous_scopes(), channel=channel)
    async with async_session_factory() as db:
        agent = (await db.execute(
            select(AgentClient).where(AgentClient.key_hash == hash_key(key))
        )).scalars().first()
        if agent is None or agent.revoked:
            raise AccessDenied("This agent key is not valid or has been revoked.")
        names = None
        if agent.workspace_ids:
            rows = (await db.execute(
                select(Workspace.id, Workspace.name).where(
                    Workspace.id.in_([uuid.UUID(str(w)) for w in agent.workspace_ids])
                )
            )).all()
            names = frozenset(n for _, n in rows)
        return AgentIdentity(
            agent_id=agent.id,
            name=agent.name,
            scopes=frozenset(agent.scopes or ["read"]),
            workspace_ids=frozenset(str(w) for w in agent.workspace_ids) if agent.workspace_ids else None,
            workspace_names=names,
            channel=channel,
            sql_catalogs=frozenset(c.lower() for c in agent.sql_catalogs) if agent.sql_catalogs else None,
        )


# ── the audit trail ──────────────────────────────────────────────────


def _entities_in(value: Any, found: Set[str], depth: int = 0) -> None:
    """Entity ids mentioned in a call's arguments or result, for the audit trail."""
    if depth > 4 or len(found) >= 25:
        return
    if isinstance(value, str):
        if value.count(":") >= 2 and value.split(":", 1)[0].isalpha() and len(value) < 400:
            found.add(value)
    elif isinstance(value, dict):
        for k in ("entity_id", "source", "target", "from_entity", "to_entity"):
            if isinstance(value.get(k), str):
                _entities_in(value[k], found, depth + 1)
        for v in value.values():
            if isinstance(v, (list, dict)):
                _entities_in(v, found, depth + 1)
    elif isinstance(value, list):
        for v in value[:30]:
            _entities_in(v, found, depth + 1)


async def record_activity(identity: AgentIdentity, tool: str, arguments: Dict[str, Any], result: Any,
                          ok: bool, error: Optional[str], duration_ms: int) -> None:
    """Own session: an audit write never fails, or is rolled back with, the call."""
    try:
        size = len(json.dumps(result, default=str)) if result is not None else 0
        from kairos_kb.context.usage import call_usage

        usage = call_usage(arguments, result)
        entities: Set[str] = set()
        # What the call was about: the entities it named, and for a query the tables it
        # read — not every neighbour a response happens to mention.
        _entities_in(arguments, entities)
        entities |= subject_tables(result)
        safe_args = json.loads(json.dumps(arguments, default=str)) if arguments else None
        async with async_session_factory() as db:
            db.add(AgentActivity(
                agent_id=identity.agent_id, agent_name=identity.name, channel=identity.channel,
                tool=tool, arguments=safe_args, entity_ids=sorted(entities)[:25] or None,
                ok=ok, error=(error or "")[:2000] or None, duration_ms=duration_ms, result_size=size, **usage,
            ))
            if identity.agent_id:
                await db.execute(update(AgentClient).where(AgentClient.id == identity.agent_id).values(
                    last_seen_at=datetime.now(timezone.utc), call_count=AgentClient.call_count + 1,
                ))
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Could not record agent activity for %s", tool)


def subject_tables(result: Any) -> Set[str]:
    """The tables a run_sql result says it read (its "tables" block)."""
    if isinstance(result, dict) and isinstance(result.get("tables"), dict):
        return {t["entity_id"] for t in result["tables"].values()
                if isinstance(t, dict) and isinstance(t.get("entity_id"), str)}
    return set()


def audited(scope: str = "read") -> Callable:
    """Wrap a tool: check the caller's scope, time it, and record it.

    The wrapped function keeps its signature (functools.wraps), which is what
    MCP reads to build the tool's input schema.
    """
    def decorate(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            identity = current_agent()
            started = time.perf_counter()
            if not identity.can(scope):
                result = {"error": f"This agent key does not have the '{scope}' scope needed for {fn.__name__}."}
                await record_activity(identity, fn.__name__, kwargs, result, False, result["error"], 0)
                return result
            # Workspace scoping: an entity outside the key's workspaces does not exist for this agent.
            for arg in ("entity_id", "from_entity", "to_entity"):
                value = kwargs.get(arg)
                if isinstance(value, str) and value and not identity.sees_entity(value):
                    result = {"error": f"No such entity for this agent: {value}"}
                    await record_activity(identity, fn.__name__, kwargs, result, False, result["error"], 0)
                    return result
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                await record_activity(identity, fn.__name__, kwargs, None, False, str(exc),
                                      int((time.perf_counter() - started) * 1000))
                raise
            error = result.get("error") if isinstance(result, dict) else None
            await record_activity(identity, fn.__name__, kwargs, result, error is None, error,
                                  int((time.perf_counter() - started) * 1000))
            return result
        return wrapper
    return decorate


# ── ASGI guard for the MCP endpoint ──────────────────────────────────


class AgentAuthMiddleware:
    """Identifies the agent on every MCP HTTP request before the protocol sees it."""

    def __init__(self, app, channel: str = "mcp") -> None:
        self.app = app
        self.channel = channel

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        try:
            identity = await resolve_identity(key_from_headers(headers), self.channel)
        except AccessDenied as exc:
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"www-authenticate", b'Bearer realm="kairos"')]})
            await send({"type": "http.response.body", "body": body})
            return
        token = set_current_agent(identity)
        seen: Dict[str, Any] = {"method": None, "status": None}

        async def receive_logged():
            message = await receive()
            if message.get("type") == "http.request" and seen["method"] is None:
                try:
                    payload = json.loads(message.get("body") or b"{}")
                    if isinstance(payload, list):
                        seen["method"] = ",".join(str(p.get("method")) for p in payload if isinstance(p, dict))
                    elif isinstance(payload, dict):
                        seen["method"] = payload.get("method") or ("response" if "result" in payload else "?")
                except ValueError:
                    seen["method"] = "unparsable"
            return message

        async def send_logged(message):
            if message.get("type") == "http.response.start":
                seen["status"] = message.get("status")
            await send(message)

        try:
            await self.app(scope, receive_logged, send_logged)
        finally:
            _current.reset(token)
            # One line per MCP request: what the client asked and how it was answered.
            logger.info("MCP %s %s method=%s protocol=%s agent=%s -> %s",
                        scope.get("method"), scope.get("path"), seen["method"],
                        headers.get("mcp-protocol-version", "-"), identity.name, seen["status"])


def visible_workspace_filter(identity: AgentIdentity, column) -> List[Any]:
    """SQLAlchemy where-clauses restricting a workspace_id column to what the agent may see."""
    if identity.workspace_ids is None:
        return []
    return [column.in_([uuid.UUID(w) for w in identity.workspace_ids])]
