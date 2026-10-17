"""Which connection an RCA investigation is about.

The RCA tools are plain LangChain tools with no context argument, so the
investigation's entry point binds the incident's workspace here, and every tool
asks for its connector through :func:`rca_connector`. The binding lives in a
context variable: one per request (or eval case), never shared between them.
Without a binding (free chat) the tools use the default Databricks settings.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Optional

from kairos_kb.connectors.databricks import DatabricksConnector
from kairos_kb.connectors.factory import connector_for
from kairos_kb.db.engine import async_session_factory
from kairos_kb.models.run import Run
from kairos_kb.models.workspace import Workspace

_WORKSPACE: ContextVar[Optional[Workspace]] = ContextVar("rca_workspace", default=None)


async def bind_incident(run_id: str | uuid.UUID) -> Optional[Workspace]:
    """Point the RCA tools at the connection this failed run belongs to."""
    try:
        key = run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))
    except ValueError:
        _WORKSPACE.set(None)
        return None
    async with async_session_factory() as db:
        run = await db.get(Run, key)
        workspace = await db.get(Workspace, run.workspace_id) if run else None
        if workspace is not None:
            db.expunge(workspace)
    _WORKSPACE.set(workspace)
    return workspace


def rca_connector() -> DatabricksConnector:
    """The connector for the bound incident's workspace.

    The RCA tools speak the Databricks APIs (jobs, workspace files, Delta
    history), so an incident on another platform gets a clear refusal rather
    than a call against the wrong workspace.
    """
    workspace = _WORKSPACE.get()
    if workspace is None:
        return DatabricksConnector()
    if (workspace.platform or "databricks") != "databricks":
        raise RuntimeError(f"RCA tools support Databricks connections only; '{workspace.name}' is "
                           f"{workspace.platform}.")
    return connector_for(workspace)  # type: ignore[return-value]
