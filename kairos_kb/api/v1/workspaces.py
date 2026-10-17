"""Workspace endpoints — register, list, and trigger sync."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.db.engine import async_session_factory, get_db
from kairos_kb.exceptions import KairosException, NotFoundError
from kairos_kb.ingestion import progress as sync_progress
from kairos_kb.ingestion.object_sync import object_count
from kairos_kb.ingestion.sync_manager import SyncManager
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.column import Column
from kairos_kb.models.job import Job
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.models.run import Run
from kairos_kb.models.schema import Schema
from kairos_kb.models.sync_state import SyncState
from kairos_kb.models.table import Table
from kairos_kb.models.task import Task
from kairos_kb.models.task_run import TaskRun
from kairos_kb.models.workspace import Workspace
from kairos_kb.schemas.common import SyncRequest
from kairos_kb.schemas.workspace import WorkspaceCreate, WorkspaceResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(body: WorkspaceCreate, db: AsyncSession = Depends(get_db)):
    """Register a connection: a Databricks workspace or a Snowflake account."""
    from kairos_kb.connectors.factory import PLATFORMS

    platform = (body.platform or "databricks").lower()
    if platform not in PLATFORMS:
        raise KairosException(f"Unknown platform {body.platform}; expected one of {', '.join(PLATFORMS)}.", status_code=400)
    config = dict(body.connection_config or {})
    host = (body.host or "").rstrip("/")
    if platform == "snowflake":
        from kairos_kb.config import get_settings

        account = config.get("account") or get_settings().snowflake_account
        if not account:
            raise KairosException("A Snowflake connection needs an account identifier (or SNOWFLAKE_ACCOUNT in .env).",
                                  status_code=400)
        config["account"] = account
        host = host or f"https://{account}.snowflakecomputing.com"
    elif not host:
        raise KairosException("A Databricks connection needs the workspace URL.", status_code=400)
    workspace = Workspace(
        workspace_id=str(uuid.uuid4())[:8],
        name=body.name,
        host=host,
        platform=platform,
        connection_config=config or None,
        cloud=body.cloud,
        region=body.region,
        status="registered",
        description=body.description,
    )
    db.add(workspace)
    await db.flush()
    await db.refresh(workspace)
    return workspace


@router.get("", response_model=List[WorkspaceResponse])
async def list_workspaces(db: AsyncSession = Depends(get_db)):
    """List all registered workspaces."""
    result = await db.execute(select(Workspace).order_by(Workspace.created_at.desc()))
    return result.scalars().all()


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get workspace details."""
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalars().first()
    if not workspace:
        raise NotFoundError("Workspace", str(workspace_id))
    return workspace


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Remove a connection and everything Kairos mirrored or learned from it.

    Catalog, pipelines, lineage, objects, profiles, discovered links, context
    documents, knowledge bindings, incidents and feedback for this connection
    go with it (the database cascades). Nothing is touched on the platform.
    Agent activity is kept as the audit trail; an agent key limited to this
    connection simply sees nothing of it any more.

    Refused while a sync, an enrichment run or an index rebuild for this
    connection is in progress: stop it first.
    """
    from kairos_kb.api.v1.context import reindex_running
    from kairos_kb.enrichment.runner import is_active
    from kairos_kb.models.enrichment_run import EnrichmentRun

    if not await db.get(Workspace, workspace_id):
        raise NotFoundError("Workspace", str(workspace_id))
    if sync_progress.is_running(workspace_id):
        raise KairosException("A sync is running for this connection. Wait for it to finish, then delete.",
                              status_code=409)
    run_ids = (await db.execute(
        select(EnrichmentRun.id).where(EnrichmentRun.workspace_id == workspace_id,
                                       EnrichmentRun.status.in_(("queued", "running")))
    )).scalars().all()
    if any(is_active(r) for r in run_ids):
        raise KairosException("An enrichment run is working on this connection. Stop it first, then delete.",
                              status_code=409)
    if reindex_running(workspace_id):
        raise KairosException("The search index for this connection is being rebuilt. Try again when it finishes.",
                              status_code=409)

    await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
    sync_progress.forget(workspace_id)
    logger.info("Deleted workspace %s and everything mirrored from it", workspace_id)


async def _run_sync(workspace_id: uuid.UUID, body: SyncRequest, progress: sync_progress.SyncProgress) -> None:
    """The sync itself, in the background with its own session."""
    try:
        async with async_session_factory() as db:
            workspace = await db.get(Workspace, workspace_id)
            workspace.status = "syncing"
            await db.commit()
            results = await SyncManager(workspace, progress).sync_workspace(
                db,
                catalog_filter=body.catalog_filter,
                job_filter=body.job_filter,
                run_limit=body.run_limit,
                skip_lineage=body.skip_lineage,
            )
            await db.commit()
        # Make what was just mirrored findable by agents straight away.
        progress.phase_start("index", "Context index: making every entity searchable by agents")
        try:
            from kairos_kb.context.documents import index_workspace

            counts = await index_workspace(workspace_id, progress)
            results["index"] = counts
            # Then read the tables against the industry knowledge: proposals for a person to review.
            try:
                from kairos_kb.knowledge.binding import classify_workspace

                progress.step = "Industry knowledge: matching tables to dataset types and identifiers"
                results["knowledge"] = await classify_workspace(workspace_id)
            except Exception as exc:  # noqa: BLE001 — optional; the index stands without it
                logger.exception("Knowledge classification failed for workspace %s", workspace_id)
                results["knowledge"] = {"error": str(exc)}
            progress.phase_end("index", counts["indexed"] + counts["unchanged"])
        except Exception as exc:  # noqa: BLE001 — the mirror is committed; indexing can be re-run
            logger.exception("Context indexing failed for workspace %s", workspace_id)
            results["index"] = {"error": str(exc)}
            progress.phase_end("index", error=str(exc))
        progress.finish(results)
        # New data has landed: the living agent takes a look (it waits on what has not settled).
        try:
            from kairos_kb.living import agent as living
            from kairos_kb.models.data_product import DataProduct
            from kairos_kb.models.living import AgentRun

            async with async_session_factory() as db:
                if (await db.execute(select(DataProduct.id).where(DataProduct.workspace_id == workspace_id).limit(1))).first():
                    run = AgentRun(workspace_id=workspace_id, mode="live", status="running")
                    db.add(run)
                    await db.commit()
                    living.start(run.id)
        except Exception:  # noqa: BLE001 — the sync is done either way
            logger.exception("Could not start the living agent after sync")
    except Exception as exc:  # noqa: BLE001 — surfaced in the live panel
        logger.exception("Sync failed for workspace %s", workspace_id)
        progress.fail(str(exc))
        async with async_session_factory() as db:
            workspace = await db.get(Workspace, workspace_id)
            if workspace:
                workspace.status = "error"
                await db.commit()


@router.post("/{workspace_id}/sync", status_code=202)
async def trigger_sync(
    workspace_id: uuid.UUID,
    body: SyncRequest = SyncRequest(),
    db: AsyncSession = Depends(get_db),
):
    """Start a sync in the background. Poll GET /{workspace_id}/sync/live for progress.

    One sync per workspace at a time; a second request while one runs is refused.
    """
    workspace = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalars().first()
    if not workspace:
        raise NotFoundError("Workspace", str(workspace_id))
    if sync_progress.is_running(workspace_id):
        raise KairosException("A sync is already running for this workspace.", status_code=409)

    progress = sync_progress.begin(workspace_id, body.model_dump())
    progress.task = asyncio.create_task(_run_sync(workspace_id, body, progress))
    return progress.snapshot()


@router.get("/{workspace_id}/sync/live")
async def get_sync_live(workspace_id: uuid.UUID):
    """The latest sync for this workspace — running or finished — as it happens.

    Held in this API process: after a restart there is nothing to show until
    the next sync starts.
    """
    progress = sync_progress.latest(workspace_id)
    if not progress:
        return {"status": "none", "workspace_id": str(workspace_id)}
    return progress.snapshot()


@router.get("/{workspace_id}/status")
async def get_workspace_status(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Per-domain sync state plus what the warehouse currently holds.

    This is what the Connections screen renders: whether each domain has ever
    synced, whether it errored, and how much it produced.
    """
    workspace = (
        await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ).scalars().first()
    if not workspace:
        raise NotFoundError("Workspace", str(workspace_id))

    states = (
        await db.execute(select(SyncState).where(SyncState.workspace_id == workspace_id))
    ).scalars().all()
    by_domain = {s.domain: s for s in states}

    async def count(model) -> int:
        return (
            await db.execute(
                select(func.count()).select_from(model).where(model.workspace_id == workspace_id)
            )
        ).scalar() or 0

    counts = {
        "catalogs": await count(Catalog),
        "schemas": await count(Schema),
        "tables": await count(Table),
        "columns": await count(Column),
        "jobs": await count(Job),
        "tasks": await count(Task),
        "runs": await count(Run),
        "task_runs": await count(TaskRun),
        "lineage_edges": await count(LineageEdge),
        # Platform objects: warehouses, roles, integrations, stages, procedures, policies …
        "objects": await object_count(db, workspace_id),
    }

    # The domains a sync run covers, in the order the pipeline executes them.
    domains = []
    for name, produced in (
        ("catalog", counts["catalogs"] + counts["schemas"] + counts["tables"] + counts["columns"]),
        ("jobs", counts["jobs"] + counts["tasks"] + counts["runs"] + counts["task_runs"]),
        ("objects", counts["objects"]),
        ("lineage", counts["lineage_edges"]),
    ):
        state = by_domain.get(name)
        domains.append(
            {
                "domain": name,
                "status": state.status if state else "never_run",
                "last_sync_at": state.last_sync_at.isoformat() if state and state.last_sync_at else None,
                "items_synced": state.items_synced if state else 0,
                "error_message": state.error_message if state else None,
                "entities_in_warehouse": produced,
            }
        )

    return {
        "workspace_id": str(workspace.id),
        "name": workspace.name,
        "platform": workspace.platform,
        "host": workspace.host,
        # "syncing" with no sync alive in this process means the API restarted mid-sync.
        "status": (
            "interrupted"
            if workspace.status == "syncing" and not sync_progress.is_running(workspace_id)
            else workspace.status
        ),
        "last_synced_at": workspace.last_synced_at.isoformat() if workspace.last_synced_at else None,
        "connection_config": workspace.connection_config or {},
        **(await _endpoint(db, workspace)),
        "domains": domains,
        "counts": counts,
    }


async def _endpoint(db: AsyncSession, workspace: Workspace) -> dict:
    """This connection's own MCP endpoint and the tools its platform serves."""
    from kairos_kb.config import get_settings
    from kairos_kb.connectors.factory import slug_of
    from kairos_kb.mcp_server.connections import TOOL_NAMES

    slug = await slug_of(db, workspace)
    base = get_settings().public_api_url.rstrip("/")
    return {"mcp_slug": slug, "mcp_url": f"{base}/mcp/c/{slug}",
            "mcp_tools": TOOL_NAMES.get(workspace.platform or "databricks", [])}


@router.post("/{workspace_id}/test-connection")
async def test_connection(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Test a connection. For Snowflake, also say who Kairos is connected as and what that role can read."""
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalars().first()
    if not workspace:
        raise NotFoundError("Workspace", str(workspace_id))

    from kairos_kb.connectors.factory import connector_for

    connector = connector_for(workspace)
    connected = await connector.test_connection()
    out = {"workspace_id": str(workspace_id), "platform": workspace.platform, "connected": connected}
    if connected and hasattr(connector, "describe_access"):
        try:
            out["access"] = await connector.describe_access()
        except Exception as exc:  # noqa: BLE001 — the connection itself works
            out["access_error"] = str(exc)[:300]
    return out
