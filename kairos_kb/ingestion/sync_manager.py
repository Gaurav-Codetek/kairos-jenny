"""Sync manager — orchestrates the full synchronization pipeline.

Runs catalog sync → job sync → lineage sync in order, tracking state
via SyncState records.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.connectors.factory import connector_for
from kairos_kb.ingestion.catalog_sync import CatalogSync
from kairos_kb.ingestion.job_sync import JobSync
from kairos_kb.ingestion.lineage_sync import LineageSync
from kairos_kb.ingestion.progress import NullProgress, SyncProgress
from kairos_kb.models.sync_state import SyncState
from kairos_kb.models.workspace import Workspace

logger = logging.getLogger(__name__)


class SyncManager:
    """Orchestrates the full synchronization pipeline for a workspace."""

    def __init__(self, workspace: Workspace, progress: Optional[SyncProgress] = None) -> None:
        self._workspace = workspace
        self._progress = progress or NullProgress()
        # Databricks or Snowflake, by the workspace's platform; credentials come from settings.
        self._connector = connector_for(workspace)

    async def sync_workspace(
        self,
        session: AsyncSession,
        *,
        catalog_filter: Optional[List[str]] = None,
        job_filter: Optional[List[str]] = None,
        run_limit: int = 25,
        skip_lineage: bool = False,
    ) -> Dict[str, Any]:
        """Run a full workspace sync: catalogs → jobs → lineage.

        Args:
            session: Database session.
            catalog_filter: Optional list of catalog names to sync. Syncs all if None.
            job_filter: Optional list of job names or ids to sync. Syncs all if None.
            run_limit: Max number of runs to fetch per job.
            skip_lineage: Skip lineage sync (useful for initial testing).

        Returns:
            Summary of synced entities.
        """
        workspace_id = self._workspace.id
        workspace_name = self._workspace.name
        now = datetime.now(timezone.utc)
        results: Dict[str, Any] = {}

        logger.info("Starting full sync for workspace: %s", workspace_name)

        progress = self._progress

        # 1. Catalog sync
        await self._update_sync_state(session, workspace_id, "catalog", "running")
        try:
            progress.phase_start("catalog", "Catalog: catalogs, schemas, tables and columns")
            catalog_sync = CatalogSync(self._connector, workspace_id, workspace_name, progress)
            catalog_counts = await catalog_sync.sync(session, catalog_filter=catalog_filter)
            results["catalog"] = catalog_counts
            await self._update_sync_state(session, workspace_id, "catalog", "idle", items=sum(catalog_counts.values()))
            progress.phase_end("catalog", sum(catalog_counts.values()))
        except Exception as exc:
            logger.exception("Catalog sync failed")
            await session.rollback()
            await self._update_sync_state(session, workspace_id, "catalog", "error", error=str(exc))
            results["catalog"] = {"error": str(exc)}
            progress.phase_end("catalog", error=str(exc))
        # Commit each domain as it finishes: what is done is visible, and kept
        # even if a later domain fails.
        await session.commit()

        # 2. Job sync
        await self._update_sync_state(session, workspace_id, "jobs", "running")
        try:
            progress.phase_start("jobs", "Pipelines: jobs, tasks, runs and task runs")
            job_sync = JobSync(self._connector, workspace_id, workspace_name, progress)
            job_counts = await job_sync.sync(session, run_limit=run_limit, job_filter=job_filter)
            results["jobs"] = job_counts
            await self._update_sync_state(session, workspace_id, "jobs", "idle", items=sum(job_counts.values()))
            progress.phase_end("jobs", sum(job_counts.values()))
        except Exception as exc:
            logger.exception("Job sync failed")
            await session.rollback()
            await self._update_sync_state(session, workspace_id, "jobs", "error", error=str(exc))
            results["jobs"] = {"error": str(exc)}
            progress.phase_end("jobs", error=str(exc))
        await session.commit()

        # 3. Every other platform object: warehouses, roles, integrations, stages, procedures, policies …
        if hasattr(self._connector, "read_objects"):
            await self._update_sync_state(session, workspace_id, "objects", "running")
            try:
                progress.phase_start("objects", "Objects: integrations, stages, procedures, policies, roles and more")
                from kairos_kb.ingestion.object_sync import ObjectSync

                object_counts = await ObjectSync(self._connector, workspace_id, workspace_name, progress).sync(session)
                results["objects"] = object_counts
                total = sum(v for k, v in object_counts.items() if k != "links")
                await self._update_sync_state(session, workspace_id, "objects", "idle", items=total)
                progress.phase_end("objects", total)
            except Exception as exc:
                logger.exception("Object sync failed")
                await session.rollback()
                await self._update_sync_state(session, workspace_id, "objects", "error", error=str(exc))
                results["objects"] = {"error": str(exc)}
                progress.phase_end("objects", error=str(exc))
            await session.commit()
        else:
            progress.phase_skip("objects", "this platform's objects are covered by the catalog and pipelines phases")

        # 4. Lineage sync
        if not skip_lineage:
            await self._update_sync_state(session, workspace_id, "lineage", "running")
            try:
                progress.phase_start("lineage", "Lineage: table and column data flow from system tables")
                lineage_sync = LineageSync(self._connector, workspace_id, workspace_name, progress)
                lineage_counts = await lineage_sync.sync(
                    session,
                    catalog_filter=catalog_filter[0] if catalog_filter and len(catalog_filter) == 1 else None,
                )
                results["lineage"] = lineage_counts
                await self._update_sync_state(session, workspace_id, "lineage", "idle", items=sum(lineage_counts.values()))
                progress.phase_end("lineage", sum(lineage_counts.values()))
            except Exception as exc:
                logger.exception("Lineage sync failed")
                await session.rollback()
                await self._update_sync_state(session, workspace_id, "lineage", "error", error=str(exc))
                results["lineage"] = {"error": str(exc)}
                progress.phase_end("lineage", error=str(exc))
        else:
            progress.phase_skip("lineage", "skip lineage was selected")

        # What the platform would not let Kairos read (missing grants, edition), kept for the screen.
        notes = getattr(self._connector, "notes", None)
        if notes:
            results["access_notes"] = list(notes)
            for n in notes:
                progress.note(f"Skipped — {n}", level="warning")

        # Update workspace last_synced_at
        self._workspace.last_synced_at = now
        self._workspace.status = "active"
        await session.flush()

        logger.info("Full sync complete for workspace %s: %s", workspace_name, results)
        return results

    async def _update_sync_state(
        self,
        session: AsyncSession,
        workspace_id: uuid.UUID,
        domain: str,
        status: str,
        *,
        items: int = 0,
        error: str | None = None,
    ) -> None:
        """Update the sync state for a domain."""
        result = await session.execute(
            select(SyncState).where(
                SyncState.workspace_id == workspace_id,
                SyncState.domain == domain,
            )
        )
        sync_state = result.scalars().first()

        now = datetime.now(timezone.utc)

        if sync_state:
            sync_state.status = status
            sync_state.last_sync_at = now
            sync_state.items_synced = items
            sync_state.error_message = error
        else:
            sync_state = SyncState(
                workspace_id=workspace_id,
                domain=domain,
                status=status,
                last_sync_at=now,
                items_synced=items,
                error_message=error,
            )
            session.add(sync_state)

        await session.flush()
