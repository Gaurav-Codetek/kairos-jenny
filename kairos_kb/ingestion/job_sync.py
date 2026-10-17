"""Job sync — extracts jobs, tasks, and runs from Databricks."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.connectors.base import PlatformConnector
from kairos_kb.ingestion.progress import NullProgress, SyncProgress
from kairos_kb.ingestion.run_errors import error_detail
from kairos_kb.ingestion.change_detector import (
    create_evidence,
    detect_changes,
    record_creation,
)
from kairos_kb.models.job import Job
from kairos_kb.models.run import Run
from kairos_kb.models.task import Task
from kairos_kb.models.task_run import TaskRun

logger = logging.getLogger(__name__)

# A task that failed on its own; UPSTREAM_FAILED and CANCELED have no error of their own.
FAILED_STATES = {"FAILED", "TIMEDOUT", "INTERNAL_ERROR"}


def select_jobs(raw_jobs: List[Dict[str, Any]], job_filter: Optional[List[str]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The jobs a filter names, by job name or job id, case-insensitively.

    Returns (selected, unmatched): the filter entries that matched no job come
    back so the sync can say so, rather than silently syncing nothing.
    """
    wanted = [w.strip() for w in job_filter or [] if w and w.strip()]
    if not wanted:
        return raw_jobs, []
    keys = {w.lower() for w in wanted}
    selected, hit = [], set()
    for job in raw_jobs:
        name = ((job.get("settings") or {}).get("name") or "").strip().lower()
        job_id = str(job.get("job_id", ""))
        for key in (name, job_id):
            if key and key in keys:
                selected.append(job)
                hit.add(key)
                break
    return selected, [w for w in wanted if w.lower() not in hit]


class JobSync:
    """Synchronizes Databricks jobs, tasks, and runs into the Synthetic Warehouse."""

    def __init__(
        self,
        connector: PlatformConnector,
        workspace_id: uuid.UUID,
        workspace_name: str,
        progress: Optional[SyncProgress] = None,
    ) -> None:
        self._progress = progress or NullProgress()
        self._connector = connector
        self._workspace_id = workspace_id
        self._workspace_name = workspace_name
        self._notebooks: Dict[str, Optional[str]] = {}

    def _entity_id(self, *parts: str) -> str:
        return ":".join(parts)

    async def _notebook_source(self, path: Optional[str]) -> Optional[str]:
        """A notebook's source, read once per sync: every failure in it shares one export."""
        if not path:
            return None
        if path not in self._notebooks:
            try:
                self._notebooks[path] = await self._connector.read_workspace_file(path)
            except Exception as exc:  # noqa: BLE001 — the error itself is still worth keeping
                logger.info("Could not read notebook %s to locate a failure: %s", path, exc)
                self._notebooks[path] = None
        return self._notebooks[path]

    async def _capture_failure(self, task_run: TaskRun, task: Optional[Task]) -> bool:
        """Read what actually went wrong in a failed task run, once. Returns True if captured.

        Databricks' task status only says "see run output for details"; the run
        output holds the exception and the traceback naming the notebook cell
        and line. A task skipped because an upstream task failed has no error of
        its own, so it is not fetched.
        """
        if task_run.result_state not in FAILED_STATES or task_run.output_fetched_at is not None:
            return False
        if not task_run.source_native_id:
            return False
        try:
            output = await self._connector.get_run_output(task_run.source_native_id)
        except Exception as exc:  # noqa: BLE001 — the run is still synced without its detail
            logger.info("Could not read output of task run %s: %s", task_run.source_native_id, exc)
            return False
        path = task.notebook_path if task else None
        detail = error_detail(output, await self._notebook_source(path), path)
        task_run.error_detail = {k: v for k, v in detail.items() if k != "trace"}
        task_run.error_trace = detail.get("trace")
        task_run.output_fetched_at = datetime.now(timezone.utc)
        return True

    async def sync(
        self, session: AsyncSession, *, run_limit: int = 25, job_filter: Optional[List[str]] = None
    ) -> Dict[str, int]:
        """Sync jobs (all, or those job_filter names), their tasks, and recent runs."""
        now = datetime.now(timezone.utc)
        counts = {"jobs": 0, "tasks": 0, "runs": 0, "task_runs": 0}

        logger.info("Syncing jobs for workspace %s", self._workspace_name)
        progress = self._progress
        progress.set_step("Listing jobs")
        raw_jobs = await self._connector.list_jobs()
        if job_filter:
            found = len(raw_jobs)
            raw_jobs, unmatched = select_jobs(raw_jobs, job_filter)
            progress.note(f"Found {found} job(s); syncing {len(raw_jobs)} selected")
            if unmatched:
                progress.note("No pipeline matches: " + ", ".join(unmatched), level="warning")
        else:
            progress.note(f"Found {len(raw_jobs)} job(s)")

        for j_idx, raw_job in enumerate(raw_jobs, 1):
            job_native_id = str(raw_job.get("job_id", ""))
            job_name = (raw_job.get("settings") or {}).get("name") or job_native_id
            progress.set_step(f"{job_name}: tasks", index=j_idx, total=len(raw_jobs), unit="job")
            job = await self._sync_job(session, raw_job, now)
            counts["jobs"] += 1
            progress.bump("jobs")

            # Sync tasks from job settings
            settings = raw_job.get("settings", {})
            raw_tasks = settings.get("tasks", [])
            task_map: Dict[str, Task] = {}
            for raw_task in raw_tasks:
                task = await self._sync_task(session, raw_task, job, now)
                task_map[task.task_key] = task
                counts["tasks"] += 1
            progress.bump("tasks", len(raw_tasks))

            # Sync recent runs
            progress.set_step(f"{job_name}: listing recent runs", index=j_idx, total=len(raw_jobs), unit="job")
            try:
                raw_runs = await self._connector.list_job_runs(job_native_id, limit=run_limit)
            except Exception as exc:
                logger.warning("Failed to list runs for job %s: %s", job_native_id, exc)
                progress.note(f"Could not list runs for {job_name}: {exc}", level="warning")
                continue

            job_task_runs = 0
            for r_idx, raw_run in enumerate(raw_runs, 1):
                progress.set_step(f"{job_name}: run {r_idx} of {len(raw_runs)}",
                                  index=j_idx, total=len(raw_jobs), unit="job")
                run = await self._sync_run(session, raw_run, job, now)
                counts["runs"] += 1
                progress.bump("runs")

                # Sync task runs within this run
                try:
                    detailed_run = await self._connector.get_run(str(raw_run.get("run_id")))
                except Exception as exc:
                    logger.warning("Failed to fetch detailed run %s: %s", raw_run.get("run_id"), exc)
                    continue

                run_tasks = detailed_run.get("tasks", [])
                for raw_task_run in run_tasks:
                    task_ref = task_map.get(raw_task_run.get("task_key", ""))
                    task_run = await self._sync_task_run(session, raw_task_run, run, task_ref, now)
                    counts["task_runs"] += 1
                    if await self._capture_failure(task_run, task_ref):
                        counts["error_details"] = counts.get("error_details", 0) + 1
                        progress.bump("error_details")
                progress.bump("task_runs", len(run_tasks))
                job_task_runs += len(run_tasks)
            progress.note(f"{job_name}: {len(raw_tasks)} task(s), {len(raw_runs)} run(s), {job_task_runs} task run(s)")

        await session.flush()
        logger.info(
            "Job sync complete: %d jobs, %d tasks, %d runs, %d task_runs",
            counts["jobs"], counts["tasks"], counts["runs"], counts["task_runs"],
        )
        return counts

    async def _sync_job(self, session: AsyncSession, raw: Dict[str, Any], now: datetime) -> Job:
        """Upsert a job entity."""
        job_native_id = str(raw.get("job_id", ""))
        entity_id = self._entity_id("job", self._workspace_name, job_native_id)
        settings = raw.get("settings", {})

        result = await session.execute(select(Job).where(Job.entity_id == entity_id))
        existing = result.scalars().first()

        if existing:
            await detect_changes(
                session,
                workspace_id=self._workspace_id,
                entity_id=entity_id,
                entity_type="JOB",
                old_values={"name": existing.name, "owner": existing.owner},
                new_values={"name": settings.get("name", ""), "owner": raw.get("creator_user_name")},
                fields_to_compare=["name", "owner"],
            )
            existing.last_seen_at = now
            existing.name = settings.get("name", existing.name)
            existing.owner = raw.get("creator_user_name")
            existing.schedule = settings.get("schedule")
            existing.tags = settings.get("tags")
            existing.settings_snapshot = settings
            return existing

        job = Job(
            entity_id=entity_id,
            workspace_id=self._workspace_id,
            source_native_id=job_native_id,
            name=settings.get("name", ""),
            owner=raw.get("creator_user_name"),
            schedule=settings.get("schedule"),
            tags=settings.get("tags"),
            max_concurrent_runs=settings.get("max_concurrent_runs", 1),
            timeout_seconds=settings.get("timeout_seconds"),
            settings_snapshot=settings,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(job)
        await session.flush()

        await record_creation(session, workspace_id=self._workspace_id, entity_id=entity_id, entity_type="JOB")
        await create_evidence(
            session, workspace_id=self._workspace_id, entity_id=entity_id, source_type="API_RESPONSE", content=raw,
        )
        return job

    async def _sync_task(self, session: AsyncSession, raw: Dict[str, Any], job: Job, now: datetime) -> Task:
        """Upsert a task entity."""
        task_key = raw.get("task_key", "")
        entity_id = self._entity_id("task", self._workspace_name, job.source_native_id, task_key)

        # Determine task type
        task_type = "unknown"
        notebook_path = None
        sql_query = None
        for tt in ("notebook_task", "sql_task", "python_wheel_task", "spark_python_task", "pipeline_task", "dbt_task"):
            if tt in raw:
                task_type = tt
                if tt == "notebook_task":
                    notebook_path = raw[tt].get("notebook_path")
                elif tt == "sql_task":
                    sql_query = raw[tt].get("query", {}).get("query_text")
                break

        result = await session.execute(select(Task).where(Task.entity_id == entity_id))
        existing = result.scalars().first()

        if existing:
            existing.last_seen_at = now
            existing.task_type = task_type
            existing.depends_on = [d.get("task_key") for d in raw.get("depends_on", [])]
            existing.notebook_path = notebook_path
            existing.sql_query = sql_query
            existing.parameters = raw.get("base_parameters") or raw.get("notebook_task", {}).get("base_parameters")
            return existing

        task = Task(
            entity_id=entity_id,
            workspace_id=self._workspace_id,
            job_id=job.id,
            task_key=task_key,
            task_type=task_type,
            depends_on=[d.get("task_key") for d in raw.get("depends_on", [])],
            notebook_path=notebook_path,
            sql_query=sql_query,
            parameters=raw.get("base_parameters") or raw.get("notebook_task", {}).get("base_parameters"),
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(task)
        await session.flush()

        await record_creation(session, workspace_id=self._workspace_id, entity_id=entity_id, entity_type="TASK")
        return task

    async def _sync_run(self, session: AsyncSession, raw: Dict[str, Any], job: Job, now: datetime) -> Run:
        """Upsert a run entity."""
        run_native_id = str(raw.get("run_id", ""))
        entity_id = self._entity_id("run", self._workspace_name, job.source_native_id, run_native_id)

        result = await session.execute(select(Run).where(Run.entity_id == entity_id))
        existing = result.scalars().first()

        state = raw.get("state", {})
        life_cycle_state = state.get("life_cycle_state", "UNKNOWN")
        result_state = state.get("result_state")
        state_message = state.get("state_message")

        start_ms = raw.get("start_time")
        end_ms = raw.get("end_time")
        start_time = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc) if start_ms else None
        end_time = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc) if end_ms else None

        if existing:
            existing.state = life_cycle_state
            existing.result_state = result_state
            existing.end_time = end_time
            existing.error_message = state_message
            existing.execution_duration_ms = raw.get("execution_duration")
            existing.setup_duration_ms = raw.get("setup_duration")
            return existing

        run = Run(
            entity_id=entity_id,
            workspace_id=self._workspace_id,
            job_id=job.id,
            source_native_id=run_native_id,
            run_name=raw.get("run_name"),
            state=life_cycle_state,
            result_state=result_state,
            start_time=start_time,
            end_time=end_time,
            error_message=state_message,
            trigger=raw.get("trigger", {}).get("type", "UNKNOWN") if isinstance(raw.get("trigger"), dict) else str(raw.get("trigger", "UNKNOWN")),
            execution_duration_ms=raw.get("execution_duration"),
            setup_duration_ms=raw.get("setup_duration"),
            run_page_url=raw.get("run_page_url"),
        )
        session.add(run)
        await session.flush()
        return run

    async def _sync_task_run(
        self, session: AsyncSession, raw: Dict[str, Any], run: Run, task: Task | None, now: datetime
    ) -> TaskRun:
        """Upsert a task run entity."""
        task_key = raw.get("task_key", "")
        run_native_id = str(raw.get("run_id", ""))
        attempt = int(raw.get("attempt_number") or 0)
        # A retried task is a second attempt, not an update: keyed apart, a
        # failure followed by a successful retry keeps both facts. The first
        # attempt keeps the original key, so earlier syncs line up.
        parts = [run.source_native_id, task_key] + ([f"attempt-{attempt}"] if attempt else [])
        entity_id = self._entity_id("taskrun", self._workspace_name, *parts)

        result = await session.execute(select(TaskRun).where(TaskRun.entity_id == entity_id))
        existing = result.scalars().first()

        state = raw.get("state", {})
        life_cycle_state = state.get("life_cycle_state", "UNKNOWN")
        result_state = state.get("result_state")

        start_ms = raw.get("start_time")
        end_ms = raw.get("end_time")
        start_time = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc) if start_ms else None
        end_time = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc) if end_ms else None

        if existing:
            if existing.source_native_id and existing.source_native_id != run_native_id:
                # A different execution now sits under this key; its error is not this one's.
                existing.error_detail = None
                existing.error_trace = None
                existing.output_fetched_at = None
            existing.state = life_cycle_state
            existing.result_state = result_state
            existing.start_time = start_time
            existing.end_time = end_time
            existing.error_message = state.get("state_message")
            existing.attempt_number = attempt
            existing.source_native_id = run_native_id
            return existing

        task_run = TaskRun(
            entity_id=entity_id,
            workspace_id=self._workspace_id,
            run_id=run.id,
            task_id=task.id if task else None,
            task_key=task_key,
            source_native_id=run_native_id,
            state=life_cycle_state,
            result_state=result_state,
            start_time=start_time,
            end_time=end_time,
            error_message=state.get("state_message"),
            attempt_number=attempt,
        )
        session.add(task_run)
        await session.flush()
        return task_run
