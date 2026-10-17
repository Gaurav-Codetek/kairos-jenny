"""Which connector serves a workspace, an entity or a query.

Everything that talks to a platform asks here instead of constructing a
Databricks connector itself, so a Snowflake table is read, sampled and queried
on Snowflake. Entity ids carry their workspace's name (``table:<workspace>:…``),
which is how a table, task or job is traced back to its platform.
"""

from __future__ import annotations

import time
from typing import Dict, Iterable, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.connectors.base import PlatformConnector
from kairos_kb.models.workspace import Workspace

PLATFORMS = ("databricks", "snowflake")
_PLATFORM_BY_NAME: Dict[str, Tuple[float, str, Optional[dict], str]] = {}
_TTL = 60.0


def connector_for(workspace: Optional[Workspace]) -> PlatformConnector:
    """The connector for a workspace; Databricks when there is none (the original single-workspace setup)."""
    platform = (workspace.platform if workspace else "databricks") or "databricks"
    if platform == "snowflake":
        from kairos_kb.connectors.snowflake import SnowflakeConnector

        return SnowflakeConnector(config=workspace.connection_config or {})
    from kairos_kb.connectors.databricks import DatabricksConnector

    return DatabricksConnector(host=workspace.host) if workspace else DatabricksConnector()


def workspace_name_of(entity_id: str) -> Optional[str]:
    parts = (entity_id or "").split(":")
    return parts[1] if len(parts) >= 3 else None


async def _workspace_by_name(db: AsyncSession, name: Optional[str]) -> Optional[Workspace]:
    if not name:
        return None
    return (await db.execute(select(Workspace).where(Workspace.name == name))).scalars().first()


async def platform_of(db: AsyncSession, entity_id: str) -> str:
    """'databricks' or 'snowflake' for an entity, cached briefly."""
    name = workspace_name_of(entity_id)
    if not name:
        return "databricks"
    hit = _PLATFORM_BY_NAME.get(name)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    ws = await _workspace_by_name(db, name)
    platform = (ws.platform if ws else "databricks") or "databricks"
    _PLATFORM_BY_NAME[name] = (time.time(), platform, ws.connection_config if ws else None, ws.host if ws else "")
    return platform


async def connector_for_workspace_name(name: Optional[str]) -> PlatformConnector:
    """For code without a database session at hand (enrichment): opens its own."""
    from kairos_kb.db.engine import async_session_factory

    async with async_session_factory() as db:
        return connector_for(await _workspace_by_name(db, name))


async def connector_for_entity(db: AsyncSession, entity_id: str) -> PlatformConnector:
    return connector_for(await _workspace_by_name(db, workspace_name_of(entity_id)))


async def connector_for_tables(db: AsyncSession, full_names: Iterable[str]
                               ) -> Tuple[Optional[PlatformConnector], Optional[str]]:
    """The one connector that can run a query over these tables, or (None, reason) when they span platforms."""
    from kairos_kb.models.table import Table

    names = [n.lower() for n in full_names]
    if not names:
        return connector_for(None), None
    # A subquery, not DISTINCT: Postgres cannot compare the JSON connection_config column.
    rows = (await db.execute(
        select(Workspace).where(Workspace.id.in_(
            select(Table.workspace_id).where(func.lower(Table.full_name).in_(names))))
    )).scalars().all()
    platforms = {(w.platform or "databricks") for w in rows}
    if len(platforms) > 1:
        return None, ("These tables live on different platforms (" + ", ".join(sorted(platforms)) +
                      "); one query can only read one platform. Query each separately.")
    return connector_for(rows[0] if rows else None), None


def sql_dialect(connector: PlatformConnector) -> str:
    return getattr(connector, "platform", "databricks")


def quote_table(connector: PlatformConnector, full_name: str) -> str:
    """A table name quoted the way its platform needs."""
    if sql_dialect(connector) == "snowflake":
        from kairos_kb.connectors.snowflake import quote_name

        return quote_name(full_name)
    return ".".join(f"`{p}`" for p in full_name.split("."))


def quote_column(connector: PlatformConnector, name: str) -> str:
    if sql_dialect(connector) == "snowflake":
        from kairos_kb.connectors.snowflake import quote_ident

        return quote_ident(name)
    return f"`{name}`"


# ── Per-connection endpoints ─────────────────────────────────────────

import re as _re

_SLUGS: Tuple[float, Dict[str, Workspace]] = (0.0, {})
_SLUG_TTL = 20.0


def connection_slug(name: str) -> str:
    """'ICS Sales Warehouse' → 'ics-sales-warehouse': the connection's part of its MCP URL."""
    return _re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "connection"


async def connections_by_slug(db: AsyncSession, *, fresh: bool = False) -> Dict[str, Workspace]:
    """Every connection by its URL slug; a clash gets the short workspace id appended. Cached briefly."""
    global _SLUGS
    if not fresh and time.time() - _SLUGS[0] < _SLUG_TTL:
        return _SLUGS[1]
    rows = (await db.execute(select(Workspace).order_by(Workspace.created_at))).scalars().all()
    out: Dict[str, Workspace] = {}
    for ws in rows:
        slug = connection_slug(ws.name)
        if slug in out:
            slug = f"{slug}-{ws.workspace_id}"
        out[slug] = ws
    _SLUGS = (time.time(), out)
    return out


async def slug_of(db: AsyncSession, workspace: Workspace) -> str:
    for slug, ws in (await connections_by_slug(db, fresh=True)).items():
        if ws.id == workspace.id:
            return slug
    return connection_slug(workspace.name)
