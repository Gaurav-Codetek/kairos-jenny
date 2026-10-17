"""Incident endpoints — list failed runs as incidents.

This is a placeholder for the full RCA engine in Phase 6. For now,
it surfaces failed runs with basic context.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.db.engine import get_db
from kairos_kb.exceptions import NotFoundError
from kairos_kb.models.incident import Incident, RcaReport
from kairos_kb.models.run import Run
from kairos_kb.models.task_run import TaskRun

router = APIRouter(prefix="/incidents", tags=["incidents"])


class IncidentSummary(BaseModel):
    run_id: uuid.UUID
    entity_id: str
    job_name: Optional[str] = None
    source_native_id: str
    result_state: Optional[str]
    error_message: Optional[str]
    start_time: Optional[str]
    end_time: Optional[str]
    run_page_url: Optional[str]

    model_config = {"from_attributes": True}


@router.get("", response_model=List[IncidentSummary])
async def list_incidents(
    workspace_id: uuid.UUID | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List recent failed runs as incidents."""
    query = (
        select(Run)
        .where(Run.result_state == "FAILED")
        .order_by(Run.start_time.desc())
        .limit(limit)
    )
    if workspace_id:
        query = query.where(Run.workspace_id == workspace_id)

    result = await db.execute(query)
    runs = result.scalars().all()

    incidents = []
    for run in runs:
        incidents.append(
            IncidentSummary(
                run_id=run.id,
                entity_id=run.entity_id,
                source_native_id=run.source_native_id,
                result_state=run.result_state,
                error_message=run.error_message,
                start_time=run.start_time.isoformat() if run.start_time else None,
                end_time=run.end_time.isoformat() if run.end_time else None,
                run_page_url=run.run_page_url,
            )
        )
    return incidents


@router.get("/data-problems")
async def data_problems(days: int = 14, db: AsyncSession = Depends(get_db)):
    """Problems with the data itself rather than a pipeline run: what agents reported (with their evidence, triaged
    by the report loop) and streams the companion saw stop."""
    from datetime import datetime, timedelta, timezone

    from kairos_kb.models.context import ContextFeedback
    from kairos_kb.models.living import AgentNote
    from kairos_kb.products.fixes import payload

    since = datetime.now(timezone.utc) - timedelta(days=days)
    reports = (await db.execute(select(ContextFeedback).where(
        ContextFeedback.entity_id.like("product:%"), ContextFeedback.created_at >= since)
        .order_by(ContextFeedback.created_at.desc()))).scalars().all()
    out = []
    for f in reports:
        loop = payload(f)
        if loop.get("category") != "data_issue":
            continue
        out.append({"id": str(f.id), "source": "report", "product": f.entity_id.split(":")[-1], "title": f.message,
                    "reporter": f.reporter, "status": "resolved" if f.status == "applied" else
                    ("dismissed" if f.status == "dismissed" else "open"),
                    "note": (loop.get("history") or [{}])[-1].get("note"), "resolution": f.resolution,
                    "question": loop.get("question"), "at": f.created_at.isoformat()})
    notes = (await db.execute(select(AgentNote).where(AgentNote.kind == "data_issue", AgentNote.created_at >= since)
                              .order_by(AgentNote.created_at.desc()).limit(50))).scalars().all()
    for n in notes:
        out.append({"id": str(n.id), "source": "pulse", "product": None, "title": n.title, "reporter": "Jenny's pulse",
                    "status": "resolved" if n.status in ("resolved", "withdrawn") else "open", "note": n.body,
                    "resolution": None, "question": None, "at": n.created_at.isoformat()})
    out.sort(key=lambda x: x["at"], reverse=True)
    return {"problems": out}


@router.get("/{run_id}")
async def get_incident(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get incident detail — failed run with task-level breakdown.

    In Phase 6, this will include full RCA with evidence, lineage,
    and remediation suggestions.
    """
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalars().first()
    if not run:
        raise NotFoundError("Run", str(run_id))

    # Get failed task runs
    task_result = await db.execute(
        select(TaskRun)
        .where(TaskRun.run_id == run_id)
        .order_by(TaskRun.task_key)
    )
    task_runs = task_result.scalars().all()

    failed_tasks = [
        {
            "task_key": tr.task_key,
            "state": tr.state,
            "result_state": tr.result_state,
            "error_message": tr.error_message,
            "attempt_number": tr.attempt_number,
        }
        for tr in task_runs
        if tr.result_state == "FAILED"
    ]

    return {
        "run_id": str(run.id),
        "entity_id": run.entity_id,
        "source_native_id": run.source_native_id,
        "state": run.state,
        "result_state": run.result_state,
        "error_message": run.error_message,
        "start_time": run.start_time.isoformat() if run.start_time else None,
        "end_time": run.end_time.isoformat() if run.end_time else None,
        "run_page_url": run.run_page_url,
        "failed_tasks": failed_tasks,
        "total_tasks": len(task_runs),
        **await _rca_payload(db, run_id),
    }


async def _rca_payload(db: AsyncSession, run_id: uuid.UUID) -> dict:
    """The stored RCA for a run, or an explicit 'not analysed yet' marker.

    Reports are append-only per incident, so the newest is served but the
    history is preserved and reachable at /incidents/{run_id}/reports.
    """
    incident = (
        await db.execute(select(Incident).where(Incident.run_id == run_id))
    ).scalars().first()
    if incident is None:
        return {
            "incident_id": None,
            "rca": None,
            "evidence": [],
            "proposed_remediation": None,
            "hint": "No analysis yet. POST /api/v1/agent/rca/{run_id}/structured to generate one.",
        }

    report = (
        await db.execute(
            select(RcaReport)
            .where(RcaReport.incident_id == incident.id)
            .order_by(RcaReport.generated_at.desc())
            .limit(1)
        )
    ).scalars().first()

    if report is None:
        return {"incident_id": str(incident.id), "rca": None, "evidence": [], "proposed_remediation": None}

    # A finding is only true against the state it was derived from; surface
    # whether the run has changed since, so consumers can tell stale from live.
    current = await _run_fingerprint(db, run_id)

    return {
        "incident_id": str(incident.id),
        "incident_status": incident.status,
        "severity": incident.severity,
        "rca": {
            "report_id": str(report.id),
            "root_cause": {
                "category": report.root_cause_category,
                "entity_id": report.root_cause_entity_id,
                "summary": report.root_cause_summary,
                "confidence": report.confidence,
            },
            "timeline": report.timeline or [],
            "affected_assets": report.affected_assets or [],
            "blocked_tasks": report.blocked_tasks or [],
            "open_questions": report.open_questions or [],
            "narrative": report.narrative,
            "model": report.model,
            "tools_used": report.tools_used or [],
            "generated_at": report.generated_at.isoformat(),
            "stale": bool(report.source_fingerprint and report.source_fingerprint != current),
        },
        "evidence": report.evidence or [],
        "proposed_remediation": report.remediation,
    }


async def _run_fingerprint(db: AsyncSession, run_id: uuid.UUID) -> str:
    run = await db.get(Run, run_id)
    task_runs = (
        await db.execute(select(TaskRun).where(TaskRun.run_id == run_id).order_by(TaskRun.task_key))
    ).scalars().all()
    payload = {
        "run": [run.entity_id, run.result_state, run.error_message] if run else [],
        "tasks": [[t.task_key, t.result_state, t.error_message] for t in task_runs],
    }
    return hashlib.sha256(json.dumps(payload, default=str).encode()).hexdigest()


@router.get("/{run_id}/reports")
async def list_incident_reports(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Every analysis produced for this incident, newest first.

    Kept as history rather than overwritten: re-analysing after the warehouse
    learns more should not erase what was previously concluded.
    """
    incident = (
        await db.execute(select(Incident).where(Incident.run_id == run_id))
    ).scalars().first()
    if incident is None:
        return {"incident_id": None, "reports": []}

    reports = (
        await db.execute(
            select(RcaReport)
            .where(RcaReport.incident_id == incident.id)
            .order_by(RcaReport.generated_at.desc())
        )
    ).scalars().all()

    return {
        "incident_id": str(incident.id),
        "reports": [
            {
                "report_id": str(r.id),
                "category": r.root_cause_category,
                "summary": r.root_cause_summary,
                "confidence": r.confidence,
                "remediation_type": (r.remediation or {}).get("type"),
                "generated_at": r.generated_at.isoformat(),
            }
            for r in reports
        ],
    }
