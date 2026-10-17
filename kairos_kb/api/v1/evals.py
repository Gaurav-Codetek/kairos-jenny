"""Connector evaluations over REST, for the Evaluations screen.

Start a run (questions × connectors), watch it fill in, and open any thread to
replay the conversation: what the agent said, each tool it called with the
arguments and result, its final answer, and how that answer scored.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, select

from kairos_kb.db.engine import async_session_factory
from kairos_kb.evals import connector_eval as ce
from kairos_kb.exceptions import KairosException, NotFoundError
from kairos_kb.models.evaluation import EvalRun, EvalThread

router = APIRouter(prefix="/evals", tags=["evals"])


def _run_row(r: EvalRun) -> dict:
    return {"id": str(r.id), "name": r.name, "status": r.status, "model": r.model, "judge_model": r.judge_model,
            "connectors": r.connectors, "total_threads": r.total_threads, "finished_threads": r.finished_threads,
            "summary": r.summary or {}, "error": r.error, "selection": r.selection,
            "created_at": r.created_at.isoformat(),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None}


def _thread_row(t: EvalThread, full: bool = False) -> dict:
    row = {"id": str(t.id), "run_id": str(t.run_id), "case_id": t.case_id, "connector": t.connector,
           "category": t.category, "question": t.question, "status": t.status, "passed": t.passed,
           "judge_score": t.judge_score, "mention_score": t.mention_score, "tool_calls": t.tool_calls,
           "tool_errors": t.tool_errors, "tools_used": t.tools_used or [],
           "tokens": (t.input_tokens or 0) + (t.output_tokens or 0), "duration_ms": t.duration_ms,
           "verdict": t.verdict, "step_limit_hit": t.step_limit_hit, "error": t.error}
    if full:
        row.update({"reference": t.reference, "answer": t.answer, "transcript": t.transcript or [],
                    "mentions_missing": t.mentions_missing or [], "missing_context": t.missing_context,
                    "input_tokens": t.input_tokens, "output_tokens": t.output_tokens,
                    "tool_result_chars": t.tool_result_chars,
                    "started_at": t.started_at.isoformat() if t.started_at else None,
                    "finished_at": t.finished_at.isoformat() if t.finished_at else None})
    return row


@router.get("/questions")
async def questions():
    from kairos_kb.connectors.factory import connections_by_slug

    qs = ce.load_questions()
    async with async_session_factory() as db:
        conns = await connections_by_slug(db, fresh=True)
    options = [{"id": "v1", "label": "v1 · all connections · 20 tools"},
               {"id": "v2", "label": "v2 · all connections · 11 tools"}] + [
        {"id": f"c:{slug}", "label": f"{ws.name} · {(ws.platform or 'databricks').title()} endpoint"}
        for slug, ws in conns.items()]
    return {"total": len(qs), "categories": dict(Counter(q["category"] for q in qs).most_common()),
            "sources": dict(Counter(q["source"] for q in qs)), "questions": qs,
            "connectors": [o["id"] for o in options], "connector_options": options,
            "default_model": ce.default_model()}


class RunIn(BaseModel):
    name: str = ""
    connectors: List[str] = Field(default_factory=lambda: ["v1", "v2"])
    categories: Optional[List[str]] = None
    case_ids: Optional[List[str]] = None
    limit: Optional[int] = Field(default=None, ge=1, le=1000)


@router.post("/runs", status_code=202)
async def start(body: RunIn):
    try:
        run = await ce.create_run(body.name, body.connectors, body.case_ids, body.categories, body.limit)
    except ValueError as exc:
        raise KairosException(str(exc), status_code=400)
    ce.start_run(run.id)
    return _run_row(run)


@router.get("/runs")
async def runs(limit: int = Query(30, ge=1, le=200)):
    async with async_session_factory() as db:
        rows = (await db.execute(select(EvalRun).order_by(desc(EvalRun.created_at)).limit(limit))).scalars().all()
    return {"runs": [_run_row(r) for r in rows]}


@router.get("/runs/{run_id}")
async def run_detail(run_id: uuid.UUID):
    async with async_session_factory() as db:
        run = await db.get(EvalRun, run_id)
        if run is None:
            raise NotFoundError("Evaluation run", str(run_id))
        threads = (await db.execute(select(EvalThread).where(EvalThread.run_id == run_id)
                                    .order_by(EvalThread.created_at, EvalThread.connector))).scalars().all()
    return {"run": _run_row(run), "threads": [_thread_row(t) for t in threads]}


@router.get("/threads/{thread_id}")
async def thread(thread_id: uuid.UUID):
    async with async_session_factory() as db:
        t = await db.get(EvalThread, thread_id)
    if t is None:
        raise NotFoundError("Evaluation thread", str(thread_id))
    return _thread_row(t, full=True)


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: uuid.UUID):
    async with async_session_factory() as db:
        run = await db.get(EvalRun, run_id)
        if run is None:
            raise NotFoundError("Evaluation run", str(run_id))
        if run.status in ("queued", "running"):
            run.status = "cancelled"
            await db.commit()
    return {"status": "cancelled"}


@router.delete("/runs/{run_id}")
async def remove(run_id: uuid.UUID):
    async with async_session_factory() as db:
        run = await db.get(EvalRun, run_id)
        if run is None:
            raise NotFoundError("Evaluation run", str(run_id))
        if run.status in ("queued", "running"):
            raise KairosException("Cancel the run before deleting it.", status_code=409)
        await db.execute(delete(EvalRun).where(EvalRun.id == run_id))
        await db.commit()
    return {"deleted": str(run_id)}
