"""Entity endpoints — generic entity lookup, lineage, changes, and evidence."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.db.engine import get_db
from kairos_kb.models.change_event import ChangeEvent
from kairos_kb.models.evidence import Evidence
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.schemas.entities import ChangeEventResponse, EvidenceResponse, LineageEdgeResponse

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get("/{entity_id:path}/upstream", response_model=List[LineageEdgeResponse])
async def get_upstream(entity_id: str, db: AsyncSession = Depends(get_db)):
    """Get upstream lineage edges for an entity (what feeds into it)."""
    result = await db.execute(
        select(LineageEdge)
        .where(LineageEdge.target_entity_id == entity_id)
        .order_by(LineageEdge.observed_at.desc())
    )
    return result.scalars().all()


@router.get("/{entity_id:path}/downstream", response_model=List[LineageEdgeResponse])
async def get_downstream(entity_id: str, db: AsyncSession = Depends(get_db)):
    """Get downstream lineage edges for an entity (what it feeds into)."""
    result = await db.execute(
        select(LineageEdge)
        .where(LineageEdge.source_entity_id == entity_id)
        .order_by(LineageEdge.observed_at.desc())
    )
    return result.scalars().all()


@router.get("/{entity_id:path}/changes", response_model=List[ChangeEventResponse])
async def get_changes(entity_id: str, limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Get change history for an entity."""
    result = await db.execute(
        select(ChangeEvent)
        .where(ChangeEvent.entity_id == entity_id)
        .order_by(ChangeEvent.detected_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{entity_id:path}/evidence", response_model=List[EvidenceResponse])
async def get_evidence(entity_id: str, limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Get evidence records for an entity."""
    result = await db.execute(
        select(Evidence)
        .where(Evidence.entity_id == entity_id)
        .order_by(Evidence.observed_at.desc())
        .limit(limit)
    )
    return result.scalars().all()
