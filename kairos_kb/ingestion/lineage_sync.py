"""Lineage sync — extracts table-level and column-level lineage from Databricks system tables."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.connectors.base import PlatformConnector
from kairos_kb.ingestion.progress import NullProgress, SyncProgress
from kairos_kb.ingestion.change_detector import create_evidence
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.models.table import Table

logger = logging.getLogger(__name__)


class LineageSync:
    """Synchronizes lineage data from Databricks system tables."""

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

    def _entity_id(self, *parts: str) -> str:
        return ":".join(parts)

    async def sync(
        self,
        session: AsyncSession,
        *,
        catalog_filter: Optional[str] = None,
    ) -> Dict[str, int]:
        """Sync table-level and column-level lineage."""
        counts = {"table_edges": 0, "column_edges": 0}

        # Table-level lineage
        logger.info("Syncing table lineage for workspace %s", self._workspace_name)
        progress = self._progress
        try:
            progress.set_step("Querying table lineage from system tables")
            table_lineage = await self._connector.get_table_lineage(catalog_filter=catalog_filter)
            progress.set_step(f"Recording {len(table_lineage):,} table lineage row(s)")
            for raw_edge in table_lineage:
                await self._sync_table_lineage_edge(session, raw_edge)
                counts["table_edges"] += 1
                progress.bump("table_edges")
            progress.note(f"Table lineage: {len(table_lineage):,} row(s)")
        except Exception as exc:
            logger.warning("Failed to sync table lineage: %s", exc)
            progress.note(f"Table lineage failed: {exc}", level="warning")

        # Column-level lineage
        logger.info("Syncing column lineage for workspace %s", self._workspace_name)
        try:
            progress.set_step("Querying column lineage from system tables")
            column_lineage = await self._connector.get_column_lineage(catalog_filter=catalog_filter)
            progress.set_step(f"Recording {len(column_lineage):,} column lineage row(s)")
            for raw_edge in column_lineage:
                await self._sync_column_lineage_edge(session, raw_edge)
                counts["column_edges"] += 1
                progress.bump("column_edges")
            progress.note(f"Column lineage: {len(column_lineage):,} row(s)")
        except Exception as exc:
            logger.warning("Failed to sync column lineage: %s", exc)
            progress.note(f"Column lineage failed: {exc}", level="warning")

        await session.flush()
        logger.info(
            "Lineage sync complete: %d table edges, %d column edges",
            counts["table_edges"], counts["column_edges"],
        )
        return counts

    async def _sync_table_lineage_edge(self, session: AsyncSession, raw: Dict[str, Any]) -> LineageEdge | None:
        """Create a table-level lineage edge."""
        source_catalog = raw.get("source_table_catalog", "")
        source_schema = raw.get("source_table_schema", "")
        source_table = raw.get("source_table_name", "")
        target_catalog = raw.get("target_table_catalog", "")
        target_schema = raw.get("target_table_schema", "")
        target_table = raw.get("target_table_name", "")

        if not all([source_table, target_table]):
            return None

        source_full = f"{source_catalog}.{source_schema}.{source_table}"
        target_full = f"{target_catalog}.{target_schema}.{target_table}"

        source_entity_id = self._entity_id("table", self._workspace_name, source_full)
        target_entity_id = self._entity_id("table", self._workspace_name, target_full)

        now = datetime.now(timezone.utc)

        # Check if edge already exists
        result = await session.execute(
            select(LineageEdge).where(
                LineageEdge.source_entity_id == source_entity_id,
                LineageEdge.target_entity_id == target_entity_id,
                LineageEdge.source_type == "TABLE",
            )
        )
        existing = result.scalars().first()
        if existing:
            existing.observed_at = now
            return existing

        # Look up table UUIDs
        source_table_id = await self._resolve_table_id(session, source_entity_id)
        target_table_id = await self._resolve_table_id(session, target_entity_id)

        edge = LineageEdge(
            workspace_id=self._workspace_id,
            source_type="TABLE",
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            source_table_id=source_table_id,
            target_table_id=target_table_id,
            observed_at=now,
            confidence=1.0,
        )
        session.add(edge)
        return edge

    async def _sync_column_lineage_edge(self, session: AsyncSession, raw: Dict[str, Any]) -> LineageEdge | None:
        """Create a column-level lineage edge."""
        source_catalog = raw.get("source_table_catalog", "")
        source_schema = raw.get("source_table_schema", "")
        source_table = raw.get("source_table_name", "")
        source_col = raw.get("source_column_name", "")
        target_catalog = raw.get("target_table_catalog", "")
        target_schema = raw.get("target_table_schema", "")
        target_table = raw.get("target_table_name", "")
        target_col = raw.get("target_column_name", "")

        if not all([source_col, target_col]):
            return None

        source_full = f"{source_catalog}.{source_schema}.{source_table}.{source_col}"
        target_full = f"{target_catalog}.{target_schema}.{target_table}.{target_col}"

        source_entity_id = self._entity_id("column", self._workspace_name, source_full)
        target_entity_id = self._entity_id("column", self._workspace_name, target_full)

        now = datetime.now(timezone.utc)

        # Check if edge already exists
        result = await session.execute(
            select(LineageEdge).where(
                LineageEdge.source_entity_id == source_entity_id,
                LineageEdge.target_entity_id == target_entity_id,
                LineageEdge.source_type == "COLUMN",
            )
        )
        existing = result.scalars().first()
        if existing:
            existing.observed_at = now
            return existing

        edge = LineageEdge(
            workspace_id=self._workspace_id,
            source_type="COLUMN",
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            observed_at=now,
            confidence=1.0,
        )
        session.add(edge)
        return edge

    async def _resolve_table_id(self, session: AsyncSession, entity_id: str) -> uuid.UUID | None:
        """Look up the internal UUID for a table by entity_id."""
        result = await session.execute(select(Table.id).where(Table.entity_id == entity_id))
        row = result.scalars().first()
        return row if row else None
