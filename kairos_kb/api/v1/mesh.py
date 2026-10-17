"""Kairos Mesh endpoint — the warehouse as dbt-style bundles."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.db.engine import get_db
from kairos_kb.warehouse.mesh import build_mesh

router = APIRouter(prefix="/mesh", tags=["mesh"])


@router.get("")
async def get_mesh(workspace_id: Optional[uuid.UUID] = None, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Every bundle and every relationship between bundles.

    Columns, runs, task runs and volume files are inherited into their bundle
    rather than returned as nodes, which keeps the whole mesh small enough to
    send at once and expand/collapse in the client.
    """
    return await build_mesh(db, str(workspace_id) if workspace_id else None)
