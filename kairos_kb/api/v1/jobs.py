"""Job endpoints — browse jobs, tasks, and runs."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kairos_kb.db.engine import get_db
from kairos_kb.exceptions import NotFoundError
from kairos_kb.models.job import Job
from kairos_kb.models.run import Run
from kairos_kb.models.task import Task
from kairos_kb.models.task_run import TaskRun
from kairos_kb.schemas.jobs import JobResponse, RunResponse, TaskResponse, TaskRunResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=List[JobResponse])
async def list_jobs(workspace_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)):
    """List all jobs, optionally filtered by workspace."""
    query = select(Job).options(selectinload(Job.tasks)).order_by(Job.name)
    if workspace_id:
        query = query.where(Job.workspace_id == workspace_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get job details with tasks."""
    result = await db.execute(select(Job).options(selectinload(Job.tasks)).where(Job.id == job_id))
    job = result.scalars().first()
    if not job:
        raise NotFoundError("Job", str(job_id))

    task_result = await db.execute(select(Task).where(Task.job_id == job_id).order_by(Task.task_key))
    tasks = task_result.scalars().all()

    response = JobResponse.model_validate(job)
    response.tasks = [TaskResponse.model_validate(t) for t in tasks]
    return response


@router.get("/{job_id}/runs", response_model=List[RunResponse])
async def list_runs(job_id: uuid.UUID, limit: int = 25, db: AsyncSession = Depends(get_db)):
    """List runs for a job."""
    result = await db.execute(
        select(Run)
        .options(selectinload(Run.task_runs))
        .where(Run.job_id == job_id)
        .order_by(Run.start_time.desc())
        .limit(limit)
    )
    return result.scalars().all()

@router.get("/runs/all", response_model=List[RunResponse])
async def list_all_runs(limit: int = 1000, db: AsyncSession = Depends(get_db)):
    """List all recent runs across all jobs."""
    result = await db.execute(
        select(Run)
        .order_by(Run.start_time.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get run details with task runs."""
    result = await db.execute(select(Run).options(selectinload(Run.task_runs)).where(Run.id == run_id))
    run = result.scalars().first()
    if not run:
        raise NotFoundError("Run", str(run_id))

    task_run_result = await db.execute(
        select(TaskRun).where(TaskRun.run_id == run_id).order_by(TaskRun.task_key)
    )
    task_runs = task_run_result.scalars().all()

    response = RunResponse.model_validate(run)
    response.task_runs = [TaskRunResponse.model_validate(tr) for tr in task_runs]
    return response
