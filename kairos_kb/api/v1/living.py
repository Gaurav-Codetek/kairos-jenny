"""Living agent endpoints — what it watches, what it noticed, its looks and replays, and your feedback."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.db.engine import get_db
from kairos_kb.exceptions import KairosException, NotFoundError
from kairos_kb.living import agent
from kairos_kb.living.maturity import maturity
from kairos_kb.models.data_product import DataProduct
from kairos_kb.models.living import AgentNote, AgentRun, MetricObservation, Watch
from kairos_kb.models.workspace import Workspace

router = APIRouter(prefix="/living", tags=["Living agent"])


class StartRun(BaseModel):
    workspace_id: uuid.UUID
    mode: str = Field("live", pattern="^(live|replay)$")
    start: Optional[date] = None
    end: Optional[date] = None


class NoteFeedback(BaseModel):
    feedback: Optional[str] = Field(None, pattern="^(useful|not_useful)$")
    status: Optional[str] = Field(None, pattern="^(dismissed|resolved|open)$")
    note: Optional[str] = None


class WatchUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern="^(active|muted)$")
    good_direction: Optional[str] = Field(None, pattern="^(up|down|neutral)$")
    min_impact_pct: Optional[float] = Field(None, ge=0.5, le=100)


def _note(n: AgentNote) -> dict:
    return {"id": str(n.id), "kind": n.kind, "signal": n.signal, "title": n.title, "body": n.body,
            "facts": n.facts, "period": n.period.isoformat() if n.period else None,
            "as_of": n.as_of.isoformat() if n.as_of else None, "importance": n.importance,
            "confidence": n.confidence, "status": n.status, "feedback": n.feedback, "mode": n.mode,
            "watch_id": str(n.watch_id) if n.watch_id else None, "product_id": str(n.product_id) if n.product_id else None,
            "created_at": n.created_at.isoformat(), "supersedes_id": str(n.supersedes_id) if n.supersedes_id else None}


def _run(r: AgentRun) -> dict:
    return {"id": str(r.id), "mode": r.mode, "status": r.status, "stats": r.stats, "error": r.error,
            "step": agent.step_of(r.id), "created_at": r.created_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None}


@router.get("/state")
async def state(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Everything the screen shows: watches with their latest series, live notes, recent looks."""
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise NotFoundError("Workspace", str(workspace_id))
    products = {p.id: p for p in (await db.execute(select(DataProduct).where(DataProduct.workspace_id == ws.id))).scalars()}
    watches = (await db.execute(select(Watch).where(Watch.workspace_id == ws.id)
                                .order_by(Watch.product_id, Watch.metric))).scalars().all()
    # Latest value per period, as of the newest look (the series the agent last saw).
    latest = {}
    if watches:
        newest = dict((await db.execute(select(MetricObservation.watch_id, func.max(MetricObservation.as_of))
                                        .where(MetricObservation.watch_id.in_([w.id for w in watches]),
                                               MetricObservation.run_id.is_(None))
                                        .group_by(MetricObservation.watch_id))).all())
        for wid, at in newest.items():
            rows = (await db.execute(select(MetricObservation.period, MetricObservation.value).where(
                MetricObservation.watch_id == wid, MetricObservation.as_of == at, MetricObservation.slice == "")
                .order_by(MetricObservation.period))).all()
            latest[wid] = [[d.isoformat(), v] for d, v in rows]
    open_by_watch = defaultdict(list)
    # The companion's live moments and daily briefings have their own view; this is the monthly notebook.
    notes = (await db.execute(select(AgentNote).where(
        AgentNote.workspace_id == ws.id, AgentNote.mode == "live",
        AgentNote.kind.notin_(("moment", "daily_briefing")),
        func.coalesce(AgentNote.signal, "").notin_(("stalled", "flowing")))
        .order_by(AgentNote.created_at.desc()).limit(80))).scalars().all()
    for n in notes:
        if n.watch_id and n.status in ("open", "provisional", "confirmed") and n.kind in ("finding", "data_issue"):
            open_by_watch[n.watch_id].append(n.status)
    out_watches = []
    for w in watches:
        p = products.get(w.product_id)
        mat = await maturity(db, w)
        out_watches.append({
            "id": str(w.id), "product": p.name if p else None, "product_id": str(w.product_id), "metric": w.metric,
            "label": w.label, "time_dim": w.time_dim, "slices": w.slices or [], "good_direction": w.good_direction,
            "settle_periods": mat["settle_periods"], "settle_measured": mat["measured"], "settle_reason": mat["reason"],
            "maturity_curve": mat["curve"], "looks": mat["looks"], "why": w.why, "min_impact_pct": w.min_impact_pct,
            "sensitivity": w.sensitivity, "status": w.status, "origin": w.origin,
            "series": latest.get(w.id, []), "attention": open_by_watch.get(w.id, []),
        })
    runs = (await db.execute(select(AgentRun).where(AgentRun.workspace_id == ws.id)
                             .order_by(AgentRun.created_at.desc()).limit(6))).scalars().all()
    return {"workspace": ws.name, "products": len(products), "watches": out_watches,
            "notes": [_note(n) for n in notes], "runs": [_run(r) for r in runs]}


@router.post("/runs", status_code=202)
async def start_run(body: StartRun, db: AsyncSession = Depends(get_db)):
    """A look at the business now (live), or a replay of history month by month."""
    ws = await db.get(Workspace, body.workspace_id)
    if not ws:
        raise NotFoundError("Workspace", str(body.workspace_id))
    busy = (await db.execute(select(AgentRun.id).where(AgentRun.workspace_id == ws.id,
                                                       AgentRun.status == "running"))).first()
    if busy and agent.step_of(busy[0]):
        raise KairosException("The agent is already looking at this connection.", status_code=409)
    if body.mode == "replay" and not (body.start and body.end and body.start <= body.end):
        raise KairosException("A replay needs a start and an end month.", status_code=400)
    run = AgentRun(workspace_id=ws.id, mode=body.mode, status="running")
    db.add(run)
    await db.commit()
    agent.start(run.id, start=body.start, end=body.end)
    return _run(run)


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    r = await db.get(AgentRun, run_id)
    if not r:
        raise NotFoundError("Run", str(run_id))
    return _run(r)


@router.get("/replay")
async def replay_notes(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """The latest replay: what the agent would have said at each month-end."""
    notes = (await db.execute(select(AgentNote).where(AgentNote.workspace_id == workspace_id, AgentNote.mode == "replay")
                              .order_by(AgentNote.as_of, AgentNote.importance.desc()))).scalars().all()
    run = (await db.execute(select(AgentRun).where(AgentRun.workspace_id == workspace_id, AgentRun.mode == "replay")
                            .order_by(AgentRun.created_at.desc()).limit(1))).scalars().first()
    return {"run": _run(run) if run else None, "notes": [_note(n) for n in notes]}


@router.patch("/notes/{note_id}")
async def feedback(note_id: uuid.UUID, body: NoteFeedback, db: AsyncSession = Depends(get_db)):
    """Tell the agent whether a note helped. 'Not useful' makes it ask for stronger evidence on that metric."""
    n = await db.get(AgentNote, note_id)
    if not n:
        raise NotFoundError("Note", str(note_id))
    if body.feedback:
        n.feedback, n.feedback_note = body.feedback, body.note
        w = await db.get(Watch, n.watch_id) if n.watch_id else None
        if w:
            w.sensitivity = min(3.0, w.sensitivity * 1.25) if body.feedback == "not_useful" else max(1.0, w.sensitivity * 0.9)
    if body.status:
        n.status = body.status
    await db.commit()
    return _note(n)


@router.patch("/watches/{watch_id}")
async def update_watch(watch_id: uuid.UUID, body: WatchUpdate, db: AsyncSession = Depends(get_db)):
    w = await db.get(Watch, watch_id)
    if not w:
        raise NotFoundError("Watch", str(watch_id))
    for k in ("status", "good_direction", "min_impact_pct"):
        v = getattr(body, k)
        if v is not None:
            setattr(w, k, v)
    w.origin = "person"
    await db.commit()
    return {"id": str(w.id), "status": w.status, "good_direction": w.good_direction, "min_impact_pct": w.min_impact_pct}


@router.post("/watches/derive")
async def rederive(workspace_id: uuid.UUID = Query(...), db: AsyncSession = Depends(get_db)):
    """Propose the watch list again from the data products (person-made settings are kept)."""
    from kairos_kb.living.watch import derive

    n = 0
    for p in (await db.execute(select(DataProduct).where(DataProduct.workspace_id == workspace_id))).scalars().all():
        n += len(await derive(db, p))
        await db.commit()
    return {"watches": n}
