"""Agents that use Kairos: their keys, what they are allowed, and what they did."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.config import get_settings
from kairos_kb.context.access import hash_key, new_key
from kairos_kb.db.engine import get_db
from kairos_kb.exceptions import KairosException, NotFoundError
from kairos_kb.models.context import AgentActivity, AgentClient
from kairos_kb.models.workspace import Workspace

router = APIRouter(prefix="/agents", tags=["agents"])

SCOPES = ("read", "query", "files", "act")


def _payload(a: AgentClient) -> Dict[str, Any]:
    return {
        "id": str(a.id), "name": a.name, "description": a.description, "key_prefix": a.key_prefix,
        "workspace_ids": a.workspace_ids or [], "scopes": a.scopes or ["read"], "revoked": a.revoked,
        "sql_catalogs": a.sql_catalogs or [],
        "created_at": a.created_at.isoformat(), "last_seen_at": a.last_seen_at.isoformat() if a.last_seen_at else None,
        "call_count": a.call_count,
    }


class AgentIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    workspace_ids: Optional[List[uuid.UUID]] = Field(None, description="Empty for every workspace")
    scopes: List[str] = Field(default_factory=lambda: ["read"])
    sql_catalogs: Optional[List[str]] = Field(None, description="Catalogs run_sql may query; empty for no limit")


@router.get("")
async def list_agents(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AgentClient).order_by(AgentClient.created_at.desc()))).scalars().all()
    return {"agents": [_payload(a) for a in rows]}


async def _validated(body: AgentIn, db: AsyncSession) -> None:
    bad = [s for s in body.scopes if s not in SCOPES]
    if bad or "read" not in body.scopes:
        raise KairosException(f"scopes must include 'read' and only use {', '.join(SCOPES)}", status_code=400)
    for w in body.workspace_ids or []:
        if not await db.get(Workspace, w):
            raise NotFoundError("Workspace", str(w))


@router.post("", status_code=201)
async def create_agent(body: AgentIn, db: AsyncSession = Depends(get_db)):
    """Register an agent. The key is returned once — store it; Kairos keeps only a hash."""
    await _validated(body, db)
    key = new_key()
    agent = AgentClient(
        name=body.name.strip(), description=body.description, key_prefix=key[:12], key_hash=hash_key(key),
        workspace_ids=[str(w) for w in body.workspace_ids] if body.workspace_ids else None,
        scopes=sorted(set(body.scopes)),
        sql_catalogs=[c.strip() for c in body.sql_catalogs if c.strip()] if body.sql_catalogs else None,
    )
    db.add(agent)
    await db.commit()
    return {**_payload(agent), "key": key, "note": "This key is shown only once."}


@router.post("/{agent_id}/rotate")
async def rotate_key(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    agent = await db.get(AgentClient, agent_id)
    if not agent:
        raise NotFoundError("Agent", str(agent_id))
    key = new_key()
    agent.key_prefix, agent.key_hash, agent.revoked = key[:12], hash_key(key), False
    await db.commit()
    return {**_payload(agent), "key": key, "note": "The old key stopped working. This key is shown only once."}


@router.post("/{agent_id}/revoke")
async def revoke(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    agent = await db.get(AgentClient, agent_id)
    if not agent:
        raise NotFoundError("Agent", str(agent_id))
    agent.revoked = True
    await db.commit()
    return _payload(agent)


@router.get("/activity")
async def activity(
    agent_id: Optional[uuid.UUID] = None,
    tool: Optional[str] = None,
    channel: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = select(AgentActivity).order_by(desc(AgentActivity.created_at)).limit(limit)
    if channel:
        q = q.where(AgentActivity.channel == channel)
    if agent_id:
        q = q.where(AgentActivity.agent_id == agent_id)
    if tool:
        q = q.where(AgentActivity.tool == tool)
    rows = (await db.execute(q)).scalars().all()
    return {"activity": [
        {"id": str(r.id), "at": r.created_at.isoformat(), "agent": r.agent_name,
         "agent_id": str(r.agent_id) if r.agent_id else None, "channel": r.channel, "tool": r.tool,
         "arguments": r.arguments, "entity_ids": r.entity_ids, "ok": r.ok, "error": r.error,
         "duration_ms": r.duration_ms, "result_size": r.result_size,
         "args_tokens": r.args_tokens, "result_tokens": r.result_tokens,
         "tokens": (r.args_tokens or 0) + (r.result_tokens or 0) if r.result_tokens is not None else None,
         "est_cost_usd": r.est_cost_usd}
        for r in rows
    ]}


@router.get("/stats")
async def stats(days: int = Query(7, ge=1, le=90), channel: Optional[str] = None,
                db: AsyncSession = Depends(get_db)):
    """Usage over a window: calls by tool and by agent, error rate, most-requested entities.

    channel narrows everything to one surface (mcp, mcp-v2, rest); by_channel always
    compares all of them, so the v1 and v2 MCP servers can be read side by side.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    in_window = AgentActivity.created_at >= since
    window = (in_window & (AgentActivity.channel == channel)) if channel else in_window
    by_channel = {
        ch: {"calls": n, "errors": int(e or 0), "tools_used": t, "tokens": int(tok or 0),
             "avg_tokens": round((tok or 0) / m) if m else None, "est_cost_usd": round(float(c or 0), 6)}
        for ch, n, e, t, tok, m, c in (await db.execute(
            select(AgentActivity.channel, func.count(),
                   func.sum(case((AgentActivity.ok.is_(False), 1), else_=0)),
                   func.count(func.distinct(AgentActivity.tool)),
                   func.sum(func.coalesce(AgentActivity.args_tokens, 0) + func.coalesce(AgentActivity.result_tokens, 0)),
                   func.count(AgentActivity.result_tokens),
                   func.sum(AgentActivity.est_cost_usd))
            .where(in_window).group_by(AgentActivity.channel)
        )).all()
    }
    by_tool = dict((await db.execute(
        select(AgentActivity.tool, func.count()).where(window).group_by(AgentActivity.tool)
    )).all())
    by_agent = dict((await db.execute(
        select(AgentActivity.agent_name, func.count()).where(window).group_by(AgentActivity.agent_name)
    )).all())
    errors = (await db.execute(
        select(func.count()).select_from(AgentActivity).where(window, AgentActivity.ok.is_(False))
    )).scalar() or 0
    rows = (await db.execute(select(AgentActivity.entity_ids).where(window, AgentActivity.tool == "get_context"))).all()
    requested: Dict[str, int] = {}
    for (ids,) in rows:
        for e in ids or []:
            requested[e] = requested.get(e, 0) + 1
    top = sorted(requested.items(), key=lambda kv: -kv[1])[:10]
    total = sum(by_tool.values())
    # What the calls cost the agents making them (rows recorded before tokens were tracked are skipped).
    settings = get_settings()
    usage_rows = (await db.execute(
        select(AgentActivity.tool, func.count(AgentActivity.result_tokens),
               func.coalesce(func.sum(AgentActivity.args_tokens), 0),
               func.coalesce(func.sum(AgentActivity.result_tokens), 0),
               func.coalesce(func.sum(AgentActivity.est_cost_usd), 0.0))
        .where(window).group_by(AgentActivity.tool)
    )).all()
    tool_usage = {
        tool: {"measured_calls": n, "args_tokens": int(a), "result_tokens": int(r),
               "avg_tokens": round((a + r) / n) if n else None, "est_cost_usd": round(float(c), 6)}
        for tool, n, a, r, c in usage_rows
    }
    return {
        "days": days, "channel": channel, "by_channel": by_channel, "calls": total, "errors": errors,
        "error_rate": round(errors / total, 3) if total else 0.0,
        "by_tool": by_tool, "by_agent": by_agent,
        "tokens": {
            "args": sum(u["args_tokens"] for u in tool_usage.values()),
            "results": sum(u["result_tokens"] for u in tool_usage.values()),
        },
        "est_cost_usd": round(sum(u["est_cost_usd"] for u in tool_usage.values()), 6),
        "tool_usage": tool_usage,
        "pricing": {"model": settings.llm_pricing_model, "input_per_m": settings.llm_price_input_per_m,
                    "output_per_m": settings.llm_price_output_per_m,
                    "basis": "Responses are input tokens for the calling agent; arguments are its output tokens."},
        "most_requested": [{"entity_id": e, "name": e.split(":")[-1], "count": c} for e, c in top],
    }


@router.get("/connect")
async def connect_info(db: AsyncSession = Depends(get_db)):
    """Everything an engineer needs to point any agent at Kairos."""
    from kairos_kb.connectors.factory import connections_by_slug
    from kairos_kb.mcp_server.connections import TOOL_NAMES

    settings = get_settings()
    base = settings.public_api_url.rstrip("/")
    mcp_url = f"{base}/mcp/"
    connections = [
        {"name": ws.name, "platform": ws.platform or "databricks", "slug": slug, "mcp_url": f"{base}/mcp/c/{slug}",
         "tools": TOOL_NAMES.get(ws.platform or "databricks", [])}
        for slug, ws in (await connections_by_slug(db, fresh=True)).items()
    ]
    return {
        # One endpoint per connection: that connection only, with its platform's tools.
        "connections": connections,
        "mcp_url": mcp_url,
        # The same map through 11 consolidated tools, run side by side with v1 for comparison.
        "mcp_v2_url": f"{base}/mcp-v2/",
        "rest_base": f"{base}/api/v1/context",
        "openapi_url": f"{base}/openapi.json",
        "auth_mode": settings.agent_auth_mode,
        "header": "Authorization: Bearer <agent key>",
        "snippets": {
            "claude_code": f'claude mcp add --transport http kairos {mcp_url} --header "Authorization: Bearer <agent key>"',
            "mcp_json": {
                "mcpServers": {"kairos": {"type": "http", "url": mcp_url,
                                          "headers": {"Authorization": "Bearer <agent key>"}}}
            },
            "python_mcp": (
                "from mcp import ClientSession\n"
                "from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client\n\n"
                'http = create_mcp_http_client(headers={"Authorization": "Bearer <agent key>"})\n'
                f'async with streamable_http_client("{mcp_url}", http_client=http) as (read, write, *_):\n'
                "    async with ClientSession(read, write) as session:\n"
                "        await session.initialize()\n"
                '        overview = await session.call_tool("get_overview", {})\n'
                '        hits = await session.call_tool("find_data", {"question": "account level sales"})'
            ),
            "rest_curl": (
                f'curl -H "Authorization: Bearer <agent key>" "{base}/api/v1/context/search?q=account%20level%20sales"'
            ),
        },
    }
