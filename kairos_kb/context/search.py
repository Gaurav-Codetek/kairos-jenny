"""Find data by what it means, not only by what it is called.

Three retrievers, each good at something different:
  meaning   embedding similarity — "account level sales by month" finds
            bi_account_sales though no word matches
  keywords  full-text rank over the document — exact business terms, column names
  names     trigram similarity on the entity name — typos and partial names

Their rankings are merged with reciprocal rank fusion, which needs no score
calibration between retrievers: an entity near the top of any list rises.
Every hit says which retrievers found it and how far it can be trusted.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.context.access import AgentIdentity, visible_workspace_filter
from kairos_kb.context.embeddings import embed_query
from kairos_kb.models.context import ContextDocument

RRF_K = 60
PER_RETRIEVER = 40
# A tie-breaker, not a ranking signal: between equally relevant hits, prefer
# what Kairos has verified over what it merely synced.
TRUST_BOOST = {"verified": 0.0008, "profiled": 0.0004, "synced": 0.0}
# An identifier the caller typed that appears in an entity's own name.
EXACT_NAME_BOOST = 0.02
WEIGHTS = {"meaning": 1.0, "keywords": 1.0, "names": 0.8}


def rrf_merge(rankings: Dict[str, Sequence[str]], weights: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """Reciprocal rank fusion: score = Σ weight / (k + rank). Returns ids with their sources."""
    weights = weights or {}
    scores: Dict[str, float] = {}
    found_by: Dict[str, List[str]] = {}
    for source, ids in rankings.items():
        w = weights.get(source, 1.0)
        for rank, entity_id in enumerate(ids, 1):
            scores[entity_id] = scores.get(entity_id, 0.0) + w / (RRF_K + rank)
            found_by.setdefault(entity_id, []).append(source)
    return [
        {"entity_id": e, "score": s, "matched_by": found_by[e]}
        for e, s in sorted(scores.items(), key=lambda kv: -kv[1])
    ]


def _name_query(question: str) -> str:
    """The most name-like part of a question: identifiers win over prose."""
    identifiers = re.findall(r"[A-Za-z0-9]+(?:[_.][A-Za-z0-9]+)+", question)
    return max(identifiers, key=len) if identifiers else question


def looks_like_a_name(question: str) -> bool:
    """Name matching helps with identifiers and short fragments; on prose it only adds noise."""
    if re.search(r"[A-Za-z0-9]+[_.][A-Za-z0-9]+", question):
        return True
    return len(question.split()) <= 2


async def find_data(
    db: AsyncSession,
    question: str,
    identity: AgentIdentity,
    *,
    kinds: Optional[List[str]] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    question = (question or "").strip()
    if not question:
        return {"question": question, "results": [], "note": "Ask a question or give a name to search for."}

    base = [*visible_workspace_filter(identity, ContextDocument.workspace_id)]
    if kinds:
        base.append(ContextDocument.kind.in_(kinds))

    rankings: Dict[str, List[str]] = {}

    vector = await embed_query(question)
    if vector is not None:
        distance = ContextDocument.embedding.cosine_distance(vector)
        rows = (await db.execute(
            select(ContextDocument.entity_id)
            .where(ContextDocument.embedding.is_not(None), *base)
            .order_by(distance)
            .limit(PER_RETRIEVER)
        )).all()
        rankings["meaning"] = [r[0] for r in rows]

    tsquery = func.websearch_to_tsquery("english", question)
    # Also match any word: a natural-language question rarely has every word in one document.
    any_words = " | ".join(re.findall(r"[A-Za-z0-9]{3,}", question)) or question
    tsquery_any = func.to_tsquery("english", any_words)
    rank = func.ts_rank_cd(ContextDocument.search_vector, tsquery_any)
    rows = (await db.execute(
        select(ContextDocument.entity_id)
        .where(ContextDocument.search_vector.op("@@")(tsquery_any), *base)
        .order_by(
            ContextDocument.search_vector.op("@@")(tsquery).desc(),
            rank.desc(),
        )
        .limit(PER_RETRIEVER)
    )).all()
    rankings["keywords"] = [r[0] for r in rows]

    if looks_like_a_name(question):
        # word_similarity scores the query against the best-matching stretch of
        # the name, so "fct_ics" finds nexora.silver.fct_ics_867 despite the prefix.
        name_q = _name_query(question)
        similarity = func.word_similarity(name_q, ContextDocument.name)
        rows = (await db.execute(
            select(ContextDocument.entity_id)
            .where(similarity > 0.3, *base)
            .order_by(ContextDocument.name.ilike(f"%{name_q}%").desc(), similarity.desc(),
                      func.length(ContextDocument.name))
            .limit(PER_RETRIEVER)
        )).all()
        rankings["names"] = [r[0] for r in rows]

    weights = dict(WEIGHTS)
    if re.search(r"[A-Za-z0-9]+[_.][A-Za-z0-9]+", question):
        weights["names"] = 1.5  # an identifier was given: the name is the strongest signal
    merged = rrf_merge({k: v for k, v in rankings.items() if v}, weights)
    ids = [m["entity_id"] for m in merged[: limit * 3]]
    docs = {
        d.entity_id: d
        for d in (await db.execute(select(ContextDocument).where(ContextDocument.entity_id.in_(ids)))).scalars()
    }
    snippets = {}
    if ids:
        snippet_rows = (await db.execute(
            select(
                ContextDocument.entity_id,
                func.ts_headline("english", ContextDocument.text, tsquery_any,
                                 "MaxFragments=2, MaxWords=18, MinWords=6, StartSel=«, StopSel=»"),
            ).where(ContextDocument.entity_id.in_(ids))
        )).all()
        snippets = {e: s for e, s in snippet_rows}

    typed = re.findall(r"[A-Za-z0-9]+(?:[_.][A-Za-z0-9]+)+", question)
    results = []
    for m in merged:
        d = docs.get(m["entity_id"])
        if d is None:
            continue
        results.append({
            "entity_id": d.entity_id,
            "kind": d.kind,
            "name": d.name,
            "what_it_is": d.headline,
            "trust_level": d.trust_level,
            "matched_by": m["matched_by"],
            "relevance": round(m["score"] + TRUST_BOOST.get(d.trust_level, 0.0)
                               + (EXACT_NAME_BOOST if any(t.lower() in d.name.lower() for t in typed) else 0.0), 5),
            "evidence": " ".join((snippets.get(d.entity_id) or "").split())[:400] or None,
        })
    results.sort(key=lambda r: -r["relevance"])
    results = results[:limit]
    note = None
    if vector is None:
        note = "Meaning-based search is unavailable; results come from keywords and names only."
    elif not results:
        note = "Nothing matched. Try other words, or get_overview() to see what this warehouse covers."
    return {
        "question": question,
        "results": results,
        "retrievers": {k: len(v) for k, v in rankings.items()},
        "note": note,
        "next": "Call get_context(entity_id) on the best match for its meaning, trust, grain, columns and how to use it.",
    }
