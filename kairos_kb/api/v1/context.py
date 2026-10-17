"""The context layer over REST — the same answers MCP gives, for any HTTP client.

An agent framework without MCP support reads Kairos through these endpoints,
authenticated with the same agent key (Authorization: Bearer kai_…). The
Kairos console uses them too, to show exactly what an agent would see.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.context import feedback as feedback_mod
from kairos_kb.context.access import AccessDenied, AgentIdentity, key_from_headers, record_activity, resolve_identity
from kairos_kb.context.cards import entity_card
from kairos_kb.context.documents import index_workspace
from kairos_kb.context.joins import join_path
from kairos_kb.context.orientation import overview
from kairos_kb.context.search import find_data
from kairos_kb.db.engine import get_db
from kairos_kb.exceptions import KairosException, NotFoundError
from kairos_kb.models.context import ContextDocument, ContextFeedback
from kairos_kb.models.entity_profile import EntityProfile
from kairos_kb.models.table import Table
from kairos_kb.models.workspace import Workspace

router = APIRouter(prefix="/context", tags=["context"])

_REINDEX: Dict[str, asyncio.Task] = {}


async def agent_identity(request: Request) -> AgentIdentity:
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        return await resolve_identity(key_from_headers(headers), "rest")
    except AccessDenied as exc:
        raise KairosException(str(exc), status_code=401)


async def _audit(identity: AgentIdentity, tool: str, args: Dict[str, Any], result: Any, started: float) -> None:
    # Console browsing is not agent activity; calls made with a key are.
    if identity.agent_id is None:
        return
    error = result.get("error") if isinstance(result, dict) else None
    await record_activity(identity, tool, args, result, error is None, error, int((time.perf_counter() - started) * 1000))


@router.get("/overview")
async def get_overview(identity: AgentIdentity = Depends(agent_identity), db: AsyncSession = Depends(get_db)):
    """What this warehouse covers: data products, key tables, pipelines, trust, freshness."""
    started = time.perf_counter()
    result = await overview(db, identity)
    await _audit(identity, "get_overview", {}, result, started)
    return result


@router.get("/search")
async def search(
    q: str = Query(..., description="What you are looking for, in plain words or as a name"),
    kinds: Optional[str] = Query(None, description="Comma-separated: table, job, task, schema, catalog"),
    limit: int = Query(10, ge=1, le=50),
    identity: AgentIdentity = Depends(agent_identity),
    db: AsyncSession = Depends(get_db),
):
    """Find data by meaning, keywords or name."""
    started = time.perf_counter()
    kind_list = [k.strip() for k in (kinds or "").split(",") if k.strip()] or None
    result = await find_data(db, q, identity, kinds=kind_list, limit=limit)
    await _audit(identity, "find_data", {"question": q, "kinds": kinds, "limit": limit}, result, started)
    return result


@router.get("/entities/{entity_id:path}")
async def get_context(
    entity_id: str,
    max_columns: int = Query(150, ge=10, le=1000),
    detail: str = Query("summary", pattern="^(summary|full)$"),
    identity: AgentIdentity = Depends(agent_identity),
    db: AsyncSession = Depends(get_db),
):
    """Everything needed to understand and use one entity."""
    started = time.perf_counter()
    if not identity.sees_entity(entity_id):
        raise NotFoundError("Entity", entity_id)
    card = await entity_card(db, entity_id, max_columns=max_columns)
    if card is None:
        raise NotFoundError("Entity", entity_id)
    from kairos_kb.context.cards import summarize_card

    card = card if detail == "full" else summarize_card(card)
    await _audit(identity, "get_context", {"entity_id": entity_id, "detail": detail}, card, started)
    return card


@router.get("/join-path")
async def get_join_path(
    from_entity: str,
    to_entity: str,
    identity: AgentIdentity = Depends(agent_identity),
    db: AsyncSession = Depends(get_db),
):
    """How two tables join, with evidence and example SQL."""
    started = time.perf_counter()
    for e in (from_entity, to_entity):
        if not identity.sees_entity(e):
            raise NotFoundError("Entity", e)
    result = await join_path(db, from_entity, to_entity)
    await _audit(identity, "find_join_path", {"from_entity": from_entity, "to_entity": to_entity}, result, started)
    return result


# ── feedback ─────────────────────────────────────────────────────────


class FeedbackIn(BaseModel):
    entity_id: str
    kind: str = Field(..., description="incorrect | missing | stale | confusing | useful")
    message: str
    field: Optional[str] = None
    suggestion: Optional[str] = None


@router.post("/feedback", status_code=201)
async def post_feedback(body: FeedbackIn, identity: AgentIdentity = Depends(agent_identity),
                        db: AsyncSession = Depends(get_db)):
    """Report that context about an entity is wrong, missing, stale or confusing."""
    started = time.perf_counter()
    if identity.agent_id is None:
        identity = AgentIdentity(agent_id=None, name="console user", scopes=identity.scopes, channel="rest")
    result = await feedback_mod.report_issue(db, identity, body.entity_id, body.kind, body.message,
                                             body.field, body.suggestion)
    if "error" in result:
        raise KairosException(result["error"], status_code=400)
    await _audit(identity, "report_context_issue", body.model_dump(), result, started)
    return result


def _feedback_payload(f: ContextFeedback) -> Dict[str, Any]:
    from kairos_kb.products.fixes import payload as loop_payload

    return {
        "id": str(f.id), "entity_id": f.entity_id, "name": f.entity_id.split(":")[-1], "kind": f.kind,
        "message": f.message, "field": f.field, "suggestion": f.suggestion, "reporter": f.reporter,
        "status": f.status, "resolution": f.resolution, "created_at": f.created_at.isoformat(),
        **({"loop": loop_payload(f)} if f.entity_id.startswith("product:") else {}),
    }


@router.get("/feedback")
async def list_feedback(status: Optional[str] = Query(None), limit: int = Query(100, le=500),
                        db: AsyncSession = Depends(get_db)):
    q = select(ContextFeedback).order_by(ContextFeedback.created_at.desc()).limit(limit)
    if status:
        q = q.where(ContextFeedback.status == status)
    return {"feedback": [_feedback_payload(f) for f in (await db.execute(q)).scalars()]}


class FeedbackUpdate(BaseModel):
    status: str = Field(..., description="open | dismissed | applied")
    resolution: Optional[str] = None


@router.patch("/feedback/{feedback_id}")
async def update_feedback(feedback_id: uuid.UUID, body: FeedbackUpdate, db: AsyncSession = Depends(get_db)):
    row = await db.get(ContextFeedback, feedback_id)
    if row is None:
        raise NotFoundError("Feedback", str(feedback_id))
    if body.status not in ("open", "dismissed", "applied"):
        raise KairosException("status must be open, dismissed or applied", status_code=400)
    row.status = body.status
    row.resolution = body.resolution or row.resolution
    await db.commit()
    return _feedback_payload(row)


async def _loop_action(feedback_id: uuid.UUID, action, db: AsyncSession) -> Dict[str, Any]:
    if await action(feedback_id) is None and await db.get(ContextFeedback, feedback_id) is None:
        raise NotFoundError("Feedback", str(feedback_id))
    db.expire_all()
    return _feedback_payload(await db.get(ContextFeedback, feedback_id))


@router.post("/feedback/{feedback_id}/process")
async def process_feedback(feedback_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Work on a report about a data product now: triage it and, where the warehouse allows, fix and prove it."""
    from kairos_kb.products import fixes

    return await _loop_action(feedback_id, fixes.process, db)


@router.post("/feedback/{feedback_id}/approve")
async def approve_feedback(feedback_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Apply a proposed product change that was waiting for approval, and prove it."""
    from kairos_kb.products import fixes

    return await _loop_action(feedback_id, fixes.approve, db)


@router.post("/feedback/{feedback_id}/build")
async def build_from_feedback(feedback_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Build the new data product a report needs (in the background; it starts as a draft)."""
    from kairos_kb.products import fixes

    return await _loop_action(feedback_id, fixes.build_product, db)


@router.post("/feedback/{feedback_id}/reject")
async def reject_feedback(feedback_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from kairos_kb.products import fixes

    return await _loop_action(feedback_id, fixes.reject, db)


@router.post("/feedback/{feedback_id}/rollback")
async def rollback_feedback(feedback_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Take an applied product change back out."""
    from kairos_kb.products import fixes

    return await _loop_action(feedback_id, fixes.roll_back, db)


# ── health and indexing ──────────────────────────────────────────────


@router.get("/health")
async def context_health(db: AsyncSession = Depends(get_db)):
    """How ready each workspace is for agents: synced → indexed → profiled → verified."""
    out = []
    for ws in (await db.execute(select(Workspace).order_by(Workspace.name))).scalars():
        tables = (await db.execute(select(func.count()).select_from(Table).where(Table.workspace_id == ws.id))).scalar() or 0
        docs = dict((await db.execute(
            select(ContextDocument.trust_level, func.count())
            .where(ContextDocument.workspace_id == ws.id, ContextDocument.kind == "table")
            .group_by(ContextDocument.trust_level)
        )).all())
        embedded = (await db.execute(select(func.count()).select_from(ContextDocument).where(
            ContextDocument.workspace_id == ws.id, ContextDocument.embedding.is_not(None)
        ))).scalar() or 0
        all_docs = (await db.execute(select(func.count()).select_from(ContextDocument).where(
            ContextDocument.workspace_id == ws.id
        ))).scalar() or 0
        profiles = dict((await db.execute(
            select(EntityProfile.kind, func.count()).where(EntityProfile.workspace_id == ws.id)
            .group_by(EntityProfile.kind)
        )).all())
        open_fb = (await db.execute(select(func.count()).select_from(ContextFeedback).where(
            ContextFeedback.workspace_id == ws.id, ContextFeedback.status == "open"
        ))).scalar() or 0
        task = _REINDEX.get(str(ws.id))
        out.append({
            "workspace_id": str(ws.id), "name": ws.name, "tables": tables,
            "tables_indexed": sum(docs.values()),
            "tables_profiled": docs.get("profiled", 0) + docs.get("verified", 0),
            "tables_verified": docs.get("verified", 0),
            "documents": all_docs, "documents_embedded": embedded,
            "profiles_by_kind": profiles, "open_feedback": open_fb,
            "indexing": bool(task and not task.done()),
            "last_synced_at": ws.last_synced_at.isoformat() if ws.last_synced_at else None,
        })
    return {"workspaces": out}


def reindex_running(workspace_id: uuid.UUID) -> bool:
    task = _REINDEX.get(str(workspace_id))
    return bool(task and not task.done())


@router.post("/reindex", status_code=202)
async def reindex(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Rebuild the search index for a workspace in the background."""
    if not await db.get(Workspace, workspace_id):
        raise NotFoundError("Workspace", str(workspace_id))
    key = str(workspace_id)
    if key in _REINDEX and not _REINDEX[key].done():
        return {"status": "already running"}
    _REINDEX[key] = asyncio.create_task(index_workspace(workspace_id))
    return {"status": "started"}


# ── agent readiness: the cold-agent evaluation ───────────────────────

_EVAL: Dict[str, asyncio.Task] = {}


@router.post("/evals/cold-agent", status_code=202)
async def run_cold_agent_eval(toolset: str = Query("full", pattern="^(full|legacy)$")):
    """Run the cold-agent evaluation in the background (spends LLM budget: a few minutes)."""
    from kairos_kb.evals.cold_agent import run

    task = _EVAL.get(toolset)
    if task and not task.done():
        return {"status": "already running", "toolset": toolset}
    _EVAL[toolset] = asyncio.create_task(run(toolset))
    return {"status": "started", "toolset": toolset}


@router.get("/evals/cold-agent")
async def list_cold_agent_evals():
    from kairos_kb.evals.cold_agent import list_reports

    return {
        "running": sorted(k for k, t in _EVAL.items() if not t.done()),
        "reports": list_reports(),
    }


@router.get("/evals/cold-agent/{file_name}")
async def get_cold_agent_eval(file_name: str):
    import json

    from kairos_kb.evals.cold_agent import results_dir

    path = results_dir() / file_name
    if "/" in file_name or "\\" in file_name or not path.is_file():
        raise NotFoundError("Evaluation report", file_name)
    return json.loads(path.read_text(encoding="utf-8"))


# ── read-only SQL ────────────────────────────────────────────────────


class QueryIn(BaseModel):
    sql: str
    limit: int = Field(100, ge=1, le=1000)


@router.post("/query")
async def run_query(body: QueryIn, identity: AgentIdentity = Depends(agent_identity),
                    db: AsyncSession = Depends(get_db)):
    """Run one read-only SQL statement (needs the 'query' permission). Personal-data columns are masked."""
    from kairos_kb.context.query import run_sql

    started = time.perf_counter()
    result = await run_sql(db, identity, body.sql, body.limit)
    await _audit(identity, "run_sql", body.model_dump(), result, started)
    if "error" in result and "permission" in result["error"]:
        raise KairosException(result["error"], status_code=403)
    return result


# ── agent demand: enrich what agents actually use ────────────────────


@router.get("/demand")
async def agent_demand(days: int = Query(14, ge=1, le=90), limit: int = Query(25, ge=1, le=100),
                       db: AsyncSession = Depends(get_db)):
    """Entities agents asked about or queried, ranked by use, with how much Kairos knows about each.

    The ones agents rely on but Kairos has not profiled or verified are where
    enrichment pays off first.
    """
    from datetime import datetime, timedelta, timezone

    from kairos_kb.models.context import AgentActivity

    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(AgentActivity.entity_ids, AgentActivity.tool, AgentActivity.created_at)
        .where(AgentActivity.created_at >= since, AgentActivity.entity_ids.is_not(None))
    )).all()
    uses: Dict[str, Dict[str, Any]] = {}
    for ids, tool, at in rows:
        for e in ids or []:
            if e.split(":", 1)[0] not in ("table", "job", "task"):
                continue
            entry = uses.setdefault(e, {"calls": 0, "queried": 0, "last_used": at})
            entry["calls"] += 1
            entry["queried"] += 1 if tool == "run_sql" else 0
            entry["last_used"] = max(entry["last_used"], at)
    docs = {d.entity_id: d.trust_level for d in (await db.execute(
        select(ContextDocument).where(ContextDocument.entity_id.in_(list(uses)))
    )).scalars()} if uses else {}
    ranked = sorted(uses.items(), key=lambda kv: (-kv[1]["calls"], kv[0]))
    items = [{
        "entity_id": e, "kind": e.split(":", 1)[0], "name": e.split(":")[-1],
        "calls": u["calls"], "queried_with_sql": u["queried"], "last_used": u["last_used"].isoformat(),
        "trust_level": docs.get(e, "synced"),
    } for e, u in ranked]
    gaps = [i for i in items if i["trust_level"] != "verified"]
    return {"days": days, "entities": items[:limit], "needs_enrichment": gaps[:limit]}


# ── Volume files ─────────────────────────────────────────────────────


@router.get("/files")
async def list_files(path: str, identity: AgentIdentity = Depends(agent_identity), db: AsyncSession = Depends(get_db)):
    """List a Unity Catalog Volume directory (needs the 'files' permission)."""
    from kairos_kb.context.files import list_volume_files

    started = time.perf_counter()
    result = await list_volume_files(db, identity, path)
    await _audit(identity, "list_volume_files", {"path": path}, result, started)
    return result


@router.get("/files/read")
async def read_file(path: str, max_rows: int = Query(50, ge=1, le=500),
                    identity: AgentIdentity = Depends(agent_identity), db: AsyncSession = Depends(get_db)):
    """Read the start of a Volume file, personal data masked (needs the 'files' permission)."""
    from kairos_kb.context.files import read_volume_file

    started = time.perf_counter()
    result = await read_volume_file(db, identity, path, max_rows)
    await _audit(identity, "read_volume_file", {"path": path, "max_rows": max_rows}, result, started)
    return result
