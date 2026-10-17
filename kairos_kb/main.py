"""Main FastAPI application module."""

from __future__ import annotations

import logging
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from kairos_kb.api.v1.router import v1_router
from kairos_kb.config import get_settings
from kairos_kb.exceptions import KairosException
from kairos_kb.logging import setup_logging

logger = logging.getLogger(__name__)


async def _reconcile_interrupted_runs() -> None:
    """Mark runs orphaned by a restart as paused.

    Enrichment runs live as in-process asyncio tasks, so a container restart
    kills them while the row still says "running". Left alone the UI would
    report a live run forever. They are deliberately NOT auto-resumed —
    resuming spends LLM budget, so it stays an explicit user action via
    POST /api/v1/enrichment/runs/{id}/resume.
    """
    from sqlalchemy import select

    from kairos_kb.db.engine import async_session_factory
    from kairos_kb.models.enrichment_run import EnrichmentRun

    try:
        async with async_session_factory() as db:
            stranded = (
                await db.execute(
                    select(EnrichmentRun).where(EnrichmentRun.status.in_(["running", "queued"]))
                )
            ).scalars().all()
            for run in stranded:
                run.status = "paused"
                run.current_entity_id = None
            if stranded:
                await db.commit()
                logger.warning(
                    "Paused %d enrichment run(s) interrupted by restart; resume them explicitly.",
                    len(stranded),
                )
    except Exception:
        # Never let bookkeeping stop the API from coming up.
        logger.exception("Could not reconcile interrupted enrichment runs")


def _build_mcp(module: str = "kairos_kb.mcp_server.server", server=None):
    """Create an MCP sub-app, or None if it cannot be built.

    MCP is an additional surface; a failure here must never stop the REST API
    from serving.
    """
    try:
        import importlib

        mcp_server = server if server is not None else importlib.import_module(module).server

        from mcp.server.transport_security import TransportSecuritySettings

        # Keep DNS-rebinding protection on, and list exactly which hostnames
        # may reach MCP: local ones, plus any public route (tunnel, domain).
        extra = [h.strip() for h in get_settings().mcp_allowed_hosts.split(",") if h.strip()]
        hosts = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "[::1]:*"]
        for h in extra:
            hosts += [h, f"{h}:*"]
        origins = ["http://localhost:*", "http://127.0.0.1:*", "https://claude.ai"] + [f"https://{h}" for h in extra]
        sub_app = mcp_server.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            # Each call answered as one plain JSON response, not an event stream: tools here
            # return one result, and proxies and tunnels (dev tunnels, gateways) pass plain
            # responses reliably where they buffer or drop streams.
            json_response=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins
            ),
        )
        return mcp_server, sub_app
    except Exception:  # noqa: BLE001
        logger.exception("Could not build MCP server %s; REST API is unaffected", module)
        return None, None


mcp_server, mcp_app = _build_mcp()
# v2: the same map through fewer, non-overlapping tools, side by side with v1 for comparison.
mcp_v2_server, mcp_v2_app = _build_mcp("kairos_kb.mcp_server.server_v2")


def _build_connection_servers():
    """One server per platform; every connection's /mcp/c/<slug> endpoint is served by its platform's."""
    try:
        from kairos_kb.mcp_server.connections import SERVERS
    except Exception:  # noqa: BLE001
        logger.exception("Could not build the per-connection MCP servers; REST API is unaffected")
        return {}, {}
    servers, apps = {}, {}
    for platform, srv in SERVERS.items():
        built, sub = _build_mcp(f"connections:{platform}", server=srv)
        if built is not None:
            servers[platform], apps[platform] = built, sub
    return servers, apps


connection_servers, connection_apps = _build_connection_servers()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle hooks."""
    settings = get_settings()
    setup_logging(level="DEBUG" if settings.debug else "INFO")
    logger.info("Starting %s v%s in %s environment", settings.app_name, settings.app_version, settings.app_env)

    await _reconcile_interrupted_runs()
    try:
        from kairos_kb.evals.connector_eval import reconcile_interrupted

        await reconcile_interrupted()
    except Exception:  # noqa: BLE001 — bookkeeping must never stop the API
        logger.exception("Could not reconcile interrupted evaluation runs")

    # A mounted sub-app does not get its lifespan run by the parent, and the
    # streamable-HTTP transport needs its session manager started or every
    # request fails with "Task group is not initialized".
    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        for name, srv in (("v1", mcp_server), ("v2", mcp_v2_server),
                          *((f"connection:{p}", s) for p, s in connection_servers.items())):
            if srv is not None:
                await stack.enter_async_context(srv.session_manager.run())
                logger.info("MCP %s session manager started", name)
        # The companion's heartbeat: it looks at live connections by itself.
        from kairos_kb.companion import scheduler as companion_scheduler

        companion_scheduler.start()
        # Reports agents file about data products: triaged, fixed where the warehouse allows, and proven.
        from kairos_kb.products import fixes as product_fixes

        product_fixes.start()
        # Jenny's everyday phrases, made ahead in her own voice (in the background; live phrases go first).
        from kairos_kb.companion import voice as companion_voice

        asyncio.create_task(companion_voice.warm(companion_voice.COMMON))
        from kairos_kb.companion import smart_turn

        asyncio.create_task(smart_turn.warm())
        yield
        companion_scheduler.stop()

    logger.info("Shutting down %s", settings.app_name)


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Router
app.include_router(v1_router)


# MCP server, mounted so external agents reach it on the same host and port
# as the REST API. Its session manager is started in the lifespan above.
if mcp_app is not None:
    from kairos_kb.context.access import AgentAuthMiddleware

    # Every MCP request is tied to an agent (or refused) before the protocol runs.
    app.mount("/mcp", AgentAuthMiddleware(mcp_app, channel="mcp"))
    logger.info("MCP server mounted at /mcp (agent auth: %s)", settings.agent_auth_mode)

if mcp_v2_app is not None:
    from kairos_kb.context.access import AgentAuthMiddleware

    app.mount("/mcp-v2", AgentAuthMiddleware(mcp_v2_app, channel="mcp-v2"))
    logger.info("MCP v2 server mounted at /mcp-v2")


class _McpNoRedirect:
    """Serve /mcp (and /mcp-v2) as /mcp/ instead of redirecting.

    Starlette answers the bare mount path with a 307 to the trailing-slash
    form, and some hosted MCP clients do not carry a protocol exchange across
    a redirect. Connector URLs are usually entered without the slash.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") in ("/mcp", "/mcp-v2"):
            path = scope["path"] + "/"
            scope = dict(scope, path=path, raw_path=path.encode())
        await self.app(scope, receive, send)


app.add_middleware(_McpNoRedirect)

# Per-connection endpoints, /mcp/c/<connection>. Outermost, so it sees these paths before the /mcp mount.
if connection_apps:
    from kairos_kb.mcp_server.connections import ConnectionEndpoints

    app.add_middleware(ConnectionEndpoints, platform_apps=connection_apps)
    logger.info("Per-connection MCP endpoints at /mcp/c/<connection> for: %s", ", ".join(connection_apps))


# Global Exception Handler
@app.exception_handler(KairosException)
async def kairos_exception_handler(request: Request, exc: KairosException) -> JSONResponse:
    logger.error("Kairos exception: %s (status=%d)", exc.message, exc.status_code)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message, "status_code": exc.status_code},
    )


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    """Basic health check endpoint."""
    return {"status": "ok", "version": settings.app_version}
