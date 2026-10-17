"""Industry knowledge over REST: browse the pack, and review what Kairos bound to the warehouse.

The review loop is the forward deployed engineer's: Kairos proposes "this table
is a 3PL 867 feed" or "this column is an NPI" with its evidence; a person
confirms or rejects. Agents see proposals marked as such, confirmations as
settled, and never see rejections.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.api.v1.context import agent_identity
from kairos_kb.config import get_settings
from kairos_kb.context.access import AgentIdentity
from kairos_kb.db.engine import get_db
from kairos_kb.exceptions import KairosException, NotFoundError
from kairos_kb.knowledge import binding as binding_mod
from kairos_kb.knowledge.loader import load_pack
from kairos_kb.knowledge.search import find_knowledge, get_concept
from kairos_kb.models.knowledge import KnowledgeBinding, KnowledgeConcept, KnowledgePack

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/packs")
async def packs(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(KnowledgePack).order_by(KnowledgePack.name))).scalars().all()
    types = dict((await db.execute(
        select(KnowledgeConcept.type, func.count()).group_by(KnowledgeConcept.type))).all())
    return {"packs": [{"id": str(p.id), "name": p.name, "title": p.title, "version": p.version,
                       "okf_version": p.okf_version, "concepts": p.concept_count,
                       "source_path": p.source_path, "loaded_at": p.loaded_at.isoformat()} for p in rows],
            "concept_types": dict(sorted(types.items(), key=lambda kv: -kv[1]))}


@router.post("/packs/load")
async def load(path: Optional[str] = None, name: Optional[str] = None):
    """Load or refresh the pack from its folder; unchanged concepts keep their embeddings."""
    s = get_settings()
    try:
        return await load_pack(path or s.knowledge_pack_path, name or s.knowledge_pack_name,
                               exclude=[e.strip() for e in s.knowledge_pack_exclude.split(",") if e.strip()])
    except FileNotFoundError as exc:
        raise KairosException(str(exc), status_code=404)


@router.get("/search")
async def search(q: str, types: str = "", limit: int = Query(10, ge=1, le=50), db: AsyncSession = Depends(get_db)):
    return await find_knowledge(db, q, types=[t for t in types.split(",") if t.strip()] or None, limit=limit)


@router.get("/concept")
async def concept(id: str, identity: AgentIdentity = Depends(agent_identity), db: AsyncSession = Depends(get_db)):
    result = await get_concept(db, identity, id)
    if result is None:
        raise NotFoundError("Concept", id)
    return result


@router.post("/classify/{workspace_id}")
async def classify(workspace_id: uuid.UUID):
    """Re-read every table and column in a workspace against the pack. Decisions people made are kept."""
    return await binding_mod.classify_workspace(workspace_id)


def _binding_row(b: KnowledgeBinding, title: Optional[str], ctype: Optional[str]) -> Dict[str, Any]:
    return {"id": str(b.id), "workspace_id": str(b.workspace_id), "entity_id": b.entity_id,
            "concept_id": b.concept_id, "concept_title": title, "concept_type": ctype,
            "predicate": b.predicate, "confidence": b.confidence, "evidence": b.evidence,
            "method": b.method, "status": b.status, "reviewed_by": b.reviewed_by,
            "reviewed_at": b.reviewed_at.isoformat() if b.reviewed_at else None, "note": b.note}


@router.get("/bindings")
async def bindings(
    workspace_id: Optional[uuid.UUID] = None,
    predicate: Optional[str] = None,
    status: Optional[str] = None,
    concept_id: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    where = []
    if workspace_id:
        where.append(KnowledgeBinding.workspace_id == workspace_id)
    if predicate:
        where.append(KnowledgeBinding.predicate == predicate)
    if concept_id:
        where.append(KnowledgeBinding.concept_id == concept_id)
    if q:
        where.append(KnowledgeBinding.entity_id.ilike(f"%{q}%") | KnowledgeBinding.concept_id.ilike(f"%{q}%"))
    # Counts by status ignore the status filter, so the console can show every tab's size.
    counts = dict((await db.execute(
        select(KnowledgeBinding.status, func.count()).where(*where).group_by(KnowledgeBinding.status))).all())
    if status:
        where.append(KnowledgeBinding.status == status)
    total = (await db.execute(select(func.count()).select_from(KnowledgeBinding).where(*where))).scalar() or 0
    rows = (await db.execute(
        select(KnowledgeBinding, KnowledgeConcept.title, KnowledgeConcept.type)
        .outerjoin(KnowledgeConcept, KnowledgeConcept.concept_id == KnowledgeBinding.concept_id)
        .where(*where)
        .order_by(KnowledgeBinding.predicate.desc(), KnowledgeBinding.confidence.desc(), KnowledgeBinding.entity_id)
        .limit(limit).offset(offset)
    )).all()
    return {"total": total, "counts": counts, "bindings": [_binding_row(b, t, ty) for b, t, ty in rows]}


class Review(BaseModel):
    status: str = Field(pattern="^(confirmed|rejected|proposed)$")
    reviewer: str = Field(default="console", max_length=255)
    note: Optional[str] = Field(default=None, max_length=2000)


@router.patch("/bindings/{binding_id}")
async def review(binding_id: uuid.UUID, body: Review):
    row = await binding_mod.review_binding(binding_id, body.status, body.reviewer, body.note)
    if row is None:
        raise NotFoundError("Binding", str(binding_id))
    return _binding_row(row, None, None)


class BindingIn(BaseModel):
    workspace_id: uuid.UUID
    entity_id: str
    concept_id: str
    predicate: str = Field(pattern="^(instance_of|identified_by)$")
    reviewer: str = Field(default="console", max_length=255)
    note: Optional[str] = None


@router.post("/bindings", status_code=201)
async def add_binding(body: BindingIn, db: AsyncSession = Depends(get_db)):
    """A binding a person makes by hand — confirmed from the start."""
    concept = (await db.execute(select(KnowledgeConcept).where(KnowledgeConcept.concept_id == body.concept_id))).scalars().first()
    if concept is None:
        raise NotFoundError("Concept", body.concept_id)
    row = (await db.execute(select(KnowledgeBinding).where(
        KnowledgeBinding.entity_id == body.entity_id, KnowledgeBinding.concept_id == body.concept_id,
        KnowledgeBinding.predicate == body.predicate))).scalars().first()
    if row is None:
        row = KnowledgeBinding(workspace_id=body.workspace_id, entity_id=body.entity_id, concept_id=body.concept_id,
                               predicate=body.predicate, confidence=1.0, evidence={"by": "person"})
        db.add(row)
    row.method, row.status, row.reviewed_by, row.note = "person", "confirmed", body.reviewer, body.note
    row.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    return _binding_row(row, concept.title, concept.type)
