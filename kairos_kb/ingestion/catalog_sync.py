"""Catalog sync — extracts catalogs, schemas, tables, and columns from Databricks.

Supports both full sync (all catalogs) and scoped sync (specific catalogs).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.connectors.base import PlatformConnector
from kairos_kb.ingestion.progress import NullProgress, SyncProgress
from kairos_kb.ingestion.change_detector import (
    create_evidence,
    detect_changes,
    record_creation,
    record_removal,
)
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.column import Column
from kairos_kb.models.schema import Schema
from kairos_kb.models.table import Table

logger = logging.getLogger(__name__)


class CatalogSync:
    """Synchronizes Unity Catalog metadata into the Synthetic Warehouse."""

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
        """Build a stable entity ID from parts."""
        return ":".join(parts)

    async def sync(
        self,
        session: AsyncSession,
        *,
        catalog_filter: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """Run a full catalog sync. Returns counts of synced entities.

        Args:
            session: Database session.
            catalog_filter: Optional list of catalog names to sync. If None, syncs all.
        """
        now = datetime.now(timezone.utc)
        counts = {"catalogs": 0, "schemas": 0, "tables": 0, "columns": 0}

        # 1. Extract catalogs
        logger.info("Syncing catalogs for workspace %s", self._workspace_name)
        progress = self._progress
        progress.set_step("Listing catalogs")
        raw_catalogs = await self._connector.list_catalogs()

        if catalog_filter:
            raw_catalogs = [c for c in raw_catalogs if c.get("name") in catalog_filter]
        # Skip system catalogs
        raw_catalogs = [c for c in raw_catalogs if c.get("name", "") not in ("system", "__databricks_internal")]
        names = [c.get("name", "") for c in raw_catalogs]
        progress.note(f"Found {len(names)} catalog(s): " + ", ".join(names[:8]) + (" …" if len(names) > 8 else ""))

        for c_idx, raw_catalog in enumerate(raw_catalogs, 1):
            catalog_name = raw_catalog.get("name", "")

            catalog = await self._sync_catalog(session, raw_catalog, now)
            counts["catalogs"] += 1
            progress.bump("catalogs")

            # 2. Extract schemas for this catalog
            progress.set_step(f"Listing schemas in {catalog_name}", index=c_idx, total=len(raw_catalogs),
                              unit="catalog")
            raw_schemas = [s for s in await self._connector.list_schemas(catalog_name)
                           if s.get("name", "") != "information_schema"]
            for s_idx, raw_schema in enumerate(raw_schemas, 1):
                schema_name = raw_schema.get("name", "")

                schema = await self._sync_schema(session, raw_schema, catalog, now)
                counts["schemas"] += 1
                progress.bump("schemas")

                # 3. Extract tables for this schema
                progress.set_step(f"Reading tables in {catalog_name}.{schema_name}",
                                  index=s_idx, total=len(raw_schemas), unit=f"schema in {catalog_name}")
                try:
                    raw_tables = await self._connector.list_tables(catalog_name, schema_name)
                except Exception as exc:
                    logger.warning("Failed to list tables for %s.%s: %s", catalog_name, schema_name, exc)
                    progress.note(f"Could not list tables in {catalog_name}.{schema_name}: {exc}", level="warning")
                    continue

                schema_columns = 0
                for raw_table in raw_tables:
                    table = await self._sync_table(session, raw_table, schema, now)
                    counts["tables"] += 1
                    progress.bump("tables")

                    # 4. Extract columns from table info
                    columns_data = raw_table.get("columns", [])
                    for idx, raw_col in enumerate(columns_data):
                        await self._sync_column(session, raw_col, table, idx, now)
                        counts["columns"] += 1
                    progress.bump("columns", len(columns_data))
                    schema_columns += len(columns_data)
                progress.note(f"{catalog_name}.{schema_name}: {len(raw_tables)} table(s), {schema_columns:,} column(s)")

        await session.flush()
        logger.info(
            "Catalog sync complete: %d catalogs, %d schemas, %d tables, %d columns",
            counts["catalogs"], counts["schemas"], counts["tables"], counts["columns"],
        )
        return counts

    async def _sync_catalog(
        self, session: AsyncSession, raw: Dict[str, Any], now: datetime
    ) -> Catalog:
        """Upsert a catalog entity."""
        entity_id = self._entity_id("catalog", self._workspace_name, raw["name"])

        result = await session.execute(select(Catalog).where(Catalog.entity_id == entity_id))
        existing = result.scalars().first()

        if existing:
            # Detect changes
            await detect_changes(
                session,
                workspace_id=self._workspace_id,
                entity_id=entity_id,
                entity_type="CATALOG",
                old_values={"comment": existing.comment, "owner": existing.owner},
                new_values={"comment": raw.get("comment"), "owner": raw.get("owner")},
                fields_to_compare=["comment", "owner"],
            )
            existing.last_seen_at = now
            existing.comment = raw.get("comment")
            existing.owner = raw.get("owner")
            existing.properties = raw.get("properties")
            return existing

        # New catalog
        catalog = Catalog(
            entity_id=entity_id,
            workspace_id=self._workspace_id,
            source_native_id=raw.get("name", ""),
            name=raw["name"],
            comment=raw.get("comment"),
            owner=raw.get("owner"),
            catalog_type=raw.get("catalog_type", "MANAGED_CATALOG"),
            isolation_mode=raw.get("isolation_mode"),
            properties=raw.get("properties"),
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(catalog)
        await session.flush()

        await record_creation(session, workspace_id=self._workspace_id, entity_id=entity_id, entity_type="CATALOG")
        await create_evidence(
            session,
            workspace_id=self._workspace_id,
            entity_id=entity_id,
            source_type="API_RESPONSE",
            content=raw,
        )
        return catalog

    async def _sync_schema(
        self, session: AsyncSession, raw: Dict[str, Any], catalog: Catalog, now: datetime
    ) -> Schema:
        """Upsert a schema entity."""
        full_name = raw.get("full_name", f"{catalog.name}.{raw.get('name', '')}")
        entity_id = self._entity_id("schema", self._workspace_name, full_name)

        result = await session.execute(select(Schema).where(Schema.entity_id == entity_id))
        existing = result.scalars().first()

        if existing:
            await detect_changes(
                session,
                workspace_id=self._workspace_id,
                entity_id=entity_id,
                entity_type="SCHEMA",
                old_values={"comment": existing.comment, "owner": existing.owner},
                new_values={"comment": raw.get("comment"), "owner": raw.get("owner")},
                fields_to_compare=["comment", "owner"],
            )
            existing.last_seen_at = now
            existing.comment = raw.get("comment")
            existing.owner = raw.get("owner")
            existing.properties = raw.get("properties")
            return existing

        schema = Schema(
            entity_id=entity_id,
            workspace_id=self._workspace_id,
            catalog_id=catalog.id,
            name=raw.get("name", ""),
            full_name=full_name,
            comment=raw.get("comment"),
            owner=raw.get("owner"),
            properties=raw.get("properties"),
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(schema)
        await session.flush()

        await record_creation(session, workspace_id=self._workspace_id, entity_id=entity_id, entity_type="SCHEMA")
        await create_evidence(
            session, workspace_id=self._workspace_id, entity_id=entity_id, source_type="API_RESPONSE", content=raw,
        )
        return schema

    async def _sync_table(
        self, session: AsyncSession, raw: Dict[str, Any], schema: Schema, now: datetime
    ) -> Table:
        """Upsert a table entity."""
        full_name = raw.get("full_name", f"{schema.full_name}.{raw.get('name', '')}")
        entity_id = self._entity_id("table", self._workspace_name, full_name)

        result = await session.execute(select(Table).where(Table.entity_id == entity_id))
        existing = result.scalars().first()

        if existing:
            await detect_changes(
                session,
                workspace_id=self._workspace_id,
                entity_id=entity_id,
                entity_type="TABLE",
                old_values={
                    "comment": existing.comment,
                    "owner": existing.owner,
                    "table_type": existing.table_type,
                    "data_source_format": existing.data_source_format,
                },
                new_values={
                    "comment": raw.get("comment"),
                    "owner": raw.get("owner"),
                    "table_type": raw.get("table_type", ""),
                    "data_source_format": raw.get("data_source_format"),
                },
                fields_to_compare=["comment", "owner", "table_type", "data_source_format"],
            )
            existing.last_seen_at = now
            existing.comment = raw.get("comment")
            existing.owner = raw.get("owner")
            existing.table_type = raw.get("table_type", existing.table_type)
            existing.data_source_format = raw.get("data_source_format")
            existing.properties = raw.get("properties")
            existing.storage_location = raw.get("storage_location")
            if raw.get("row_count") is not None:
                existing.row_count = raw.get("row_count")
            if raw.get("size_bytes") is not None:
                existing.size_bytes = raw.get("size_bytes")
            return existing

        table = Table(
            entity_id=entity_id,
            workspace_id=self._workspace_id,
            schema_id=schema.id,
            name=raw.get("name", ""),
            full_name=full_name,
            table_type=raw.get("table_type", "MANAGED"),
            data_source_format=raw.get("data_source_format"),
            comment=raw.get("comment"),
            owner=raw.get("owner"),
            properties=raw.get("properties"),
            storage_location=raw.get("storage_location"),
            row_count=raw.get("row_count"),
            size_bytes=raw.get("size_bytes"),
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(table)
        await session.flush()

        await record_creation(session, workspace_id=self._workspace_id, entity_id=entity_id, entity_type="TABLE")
        await create_evidence(
            session, workspace_id=self._workspace_id, entity_id=entity_id, source_type="API_RESPONSE", content=raw,
        )
        return table

    async def _sync_column(
        self, session: AsyncSession, raw: Dict[str, Any], table: Table, ordinal: int, now: datetime
    ) -> Column:
        """Upsert a column entity."""
        col_name = raw.get("name", "")
        full_name = f"{table.full_name}.{col_name}"
        entity_id = self._entity_id("column", self._workspace_name, full_name)

        result = await session.execute(select(Column).where(Column.entity_id == entity_id))
        existing = result.scalars().first()

        if existing:
            await detect_changes(
                session,
                workspace_id=self._workspace_id,
                entity_id=entity_id,
                entity_type="COLUMN",
                old_values={"data_type": existing.data_type, "comment": existing.comment, "is_nullable": existing.is_nullable},
                new_values={"data_type": raw.get("type_name", ""), "comment": raw.get("comment"), "is_nullable": raw.get("nullable", True)},
                fields_to_compare=["data_type", "comment", "is_nullable"],
            )
            existing.last_seen_at = now
            existing.data_type = raw.get("type_name", existing.data_type)
            existing.full_data_type = raw.get("type_text", existing.full_data_type)
            existing.comment = raw.get("comment")
            existing.is_nullable = raw.get("nullable", True)
            existing.is_partition_column = raw.get("partition_index") is not None
            return existing

        column = Column(
            entity_id=entity_id,
            workspace_id=self._workspace_id,
            table_id=table.id,
            name=col_name,
            full_name=full_name,
            data_type=raw.get("type_name", "UNKNOWN"),
            full_data_type=raw.get("type_text", ""),
            ordinal_position=ordinal,
            is_nullable=raw.get("nullable", True),
            comment=raw.get("comment"),
            is_partition_column=raw.get("partition_index") is not None,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(column)
        await session.flush()

        await record_creation(session, workspace_id=self._workspace_id, entity_id=entity_id, entity_type="COLUMN")
        return column
