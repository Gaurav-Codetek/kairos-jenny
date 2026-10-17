"""Find industry concepts, and read one in full with where it appears in the warehouse."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sqlalchemy import String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.context.access import AgentIdentity, visible_workspace_filter
from kairos_kb.context.embeddings import embed_query
from kairos_kb.context.search import PER_RETRIEVER, rrf_merge
from kairos_kb.knowledge.context import concept_brief
from kairos_kb.models.knowledge import KnowledgeBinding, KnowledgeConcept, KnowledgePack, KnowledgeRelation


async def find_knowledge(db: AsyncSession, question: str, *, types: Optional[List[str]] = None,
                         limit: int = 8) -> Dict[str, Any]:
    question = (question or "").strip()
    if not question:
        return {"question": question, "results": [], "note": "Ask a question or name a concept."}
    base = []
    if types:
        base.append(func.lower(KnowledgeConcept.type).in_([t.lower() for t in types]))

    rankings: Dict[str, List[str]] = {}
    vector = await embed_query(question)
    if vector is not None:
        rows = (await db.execute(
            select(KnowledgeConcept.concept_id).where(KnowledgeConcept.embedding.is_not(None), *base)
            .order_by(KnowledgeConcept.embedding.cosine_distance(vector)).limit(PER_RETRIEVER)
        )).all()
        rankings["meaning"] = [r[0] for r in rows]
    any_words = " | ".join(re.findall(r"[A-Za-z0-9]{2,}", question)) or question
    tsq = func.to_tsquery("english", any_words)
    rows = (await db.execute(
        select(KnowledgeConcept.concept_id).where(KnowledgeConcept.search_vector.op("@@")(tsq), *base)
        .order_by(func.ts_rank_cd(KnowledgeConcept.search_vector, tsq).desc()).limit(PER_RETRIEVER)
    )).all()
    rankings["keywords"] = [r[0] for r in rows]
    if len(question.split()) <= 4:
        # Fuzzy title matching catches typos, but on a short acronym it confuses
        # neighbours (PDRP ~ PDC), so an exact word in the title or tags comes first.
        sim = func.word_similarity(question, KnowledgeConcept.title)
        word = rf"\m{re.escape(question)}\M"  # Postgres word boundaries
        exact = (KnowledgeConcept.title.op("~*")(word)
                 | func.cast(KnowledgeConcept.tags, String).op("~*")(word))
        rows = (await db.execute(
            select(KnowledgeConcept.concept_id).where((sim > 0.5) | exact, *base)
            .order_by(exact.desc(), sim.desc()).limit(PER_RETRIEVER)
        )).all()
        rankings["titles"] = [r[0] for r in rows]

    merged = rrf_merge({k: v for k, v in rankings.items() if v}, {"titles": 1.2})[:limit]
    ids = [m["entity_id"] for m in merged]  # rrf_merge names every id entity_id
    concepts = {c.concept_id: c for c in (await db.execute(
        select(KnowledgeConcept).where(KnowledgeConcept.concept_id.in_(ids)))).scalars()}
    bound = dict((await db.execute(
        select(KnowledgeBinding.concept_id, func.count()).where(
            KnowledgeBinding.concept_id.in_(ids), KnowledgeBinding.status != "rejected")
        .group_by(KnowledgeBinding.concept_id))).all())
    results = []
    for m in merged:
        c = concepts.get(m["entity_id"])
        if c is None:
            continue
        results.append({"concept_id": c.concept_id, "type": c.type, "title": c.title,
                        "description": c.description, "matched_by": m["matched_by"],
                        "warehouse_entities_bound": bound.get(c.concept_id, 0)})
    return {"question": question, "results": results,
            "note": "Industry knowledge, not facts about this warehouse. get_concept(concept_id) reads one "
                    "in full and lists the warehouse tables and columns bound to it."}


async def get_concept(db: AsyncSession, identity: AgentIdentity, concept_id: str) -> Optional[Dict[str, Any]]:
    cid = concept_id.strip()
    if not cid.startswith("/"):
        cid = "/" + cid
    cid = cid[:-3] if cid.endswith(".md") else cid
    c = (await db.execute(select(KnowledgeConcept).where(KnowledgeConcept.concept_id == cid))).scalars().first()
    if c is None:
        return None
    pack = await db.get(KnowledgePack, c.pack_id)
    rel_rows = (await db.execute(select(KnowledgeRelation).where(
        KnowledgeRelation.pack_id == c.pack_id,
        (KnowledgeRelation.source_concept == cid) | (KnowledgeRelation.target_concept == cid),
    ))).scalars().all()
    other_ids = {r.target_concept if r.source_concept == cid else r.source_concept for r in rel_rows}
    titles = dict((await db.execute(select(KnowledgeConcept.concept_id, KnowledgeConcept.title)
                                    .where(KnowledgeConcept.concept_id.in_(other_ids)))).all())
    bindings = (await db.execute(select(KnowledgeBinding).where(
        KnowledgeBinding.concept_id == cid, KnowledgeBinding.status != "rejected",
        *visible_workspace_filter(identity, KnowledgeBinding.workspace_id),
    ).order_by(KnowledgeBinding.status, KnowledgeBinding.confidence.desc()).limit(60))).scalars().all()

    out = concept_brief(c, full=True)
    out.update({
        "pack": {"name": pack.name, "version": pack.version} if pack else None,
        "tags": c.tags,
        "fields": c.fields,
        "sections": {k: v for k, v in (c.sections or {}).items() if k != "Relationships"},
        "relations": {
            "out": [{"predicate": r.predicate, "concept_id": r.target_concept, "title": titles.get(r.target_concept)}
                    for r in rel_rows if r.source_concept == cid],
            "in": [{"predicate": r.predicate, "concept_id": r.source_concept, "title": titles.get(r.source_concept)}
                   for r in rel_rows if r.target_concept == cid],
        },
        "sources": c.sources,
        "in_this_warehouse": [
            {"entity_id": b.entity_id, "as": b.predicate, "status": b.status, "confidence": b.confidence}
            for b in bindings
        ],
    })
    if not bindings:
        out["in_this_warehouse_note"] = "No table or column in the map is bound to this concept."
    return out


async def knowledge_overview(db: AsyncSession, identity: AgentIdentity) -> Optional[Dict[str, Any]]:
    """For get_overview: which packs are loaded and which dataset types this warehouse holds."""
    packs = (await db.execute(select(KnowledgePack))).scalars().all()
    if not packs:
        return None
    rows = (await db.execute(
        select(KnowledgeBinding.concept_id, KnowledgeConcept.title, func.count())
        .join(KnowledgeConcept, KnowledgeConcept.concept_id == KnowledgeBinding.concept_id)
        .where(KnowledgeBinding.predicate == "instance_of", KnowledgeBinding.status != "rejected",
               *visible_workspace_filter(identity, KnowledgeBinding.workspace_id))
        .group_by(KnowledgeBinding.concept_id, KnowledgeConcept.title)
        .order_by(func.count().desc())
    )).all()
    return {
        "packs": [{"name": p.name, "title": p.title, "version": p.version, "concepts": p.concept_count} for p in packs],
        "dataset_types_in_warehouse": [{"concept_id": cid, "title": t, "tables": n} for cid, t, n in rows],
        "how_to_use": "find_knowledge(question) for industry concepts — dataset types, identifiers, metrics, "
                      "regulations; get_concept(concept_id) for one in full with the tables bound to it.",
    }
