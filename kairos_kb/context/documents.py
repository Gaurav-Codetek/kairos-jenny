"""One searchable document per entity, and the index that keeps them current.

A document is everything an agent might search for, flattened to text: the
name, what the entity is and is for, its data product, its grain, every
column with its meaning, what produces and reads it. Entities that were
synced but never enriched are indexed too — from names, types and comments —
so search covers the whole warehouse, and trust_level says how much is known.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import yaml
from sqlalchemy import delete, select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.db.engine import async_session_factory
from kairos_kb.enrichment.context import gather_context
from kairos_kb.enrichment.profile_writer import load_profile_yaml
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.context import ContextDocument
from kairos_kb.models.job import Job
from kairos_kb.models.schema import Schema
from kairos_kb.models.table import Table
from kairos_kb.models.task import Task

logger = logging.getLogger(__name__)

INDEXED_KINDS = {"catalog": Catalog, "schema": Schema, "table": Table, "job": Job, "task": Task}
CHUNK = 48


# ── reading what Kairos knows ────────────────────────────────────────


async def load_profile(db: AsyncSession, entity_id: str) -> Optional[Dict[str, Any]]:
    """The enriched profile as a dict, or None if the entity was never profiled."""
    raw = await load_profile_yaml(db, entity_id)
    if not raw:
        return None
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def trust_level(profile: Optional[Dict[str, Any]]) -> str:
    """verified: profiled and every check passed · profiled · synced: metadata only."""
    if profile is None:
        return "synced"
    verification = profile.get("verification") or {}
    return "verified" if verification.get("passed") is True else "profiled"


def first_sentence(value: Optional[str], limit: int = 240) -> str:
    text = " ".join((value or "").split())
    if not text:
        return ""
    match = re.search(r"(?<=[.!?])\s", text)
    sentence = text[: match.start()] if match and match.start() < limit else text[:limit]
    return sentence if len(sentence) < limit else sentence.rstrip() + "…"


def name_words(name: str) -> str:
    """fct_ics_867 → "fct ics 867": so keyword search finds names by their parts."""
    return re.sub(r"[_.:\-/]+", " ", name or "").strip()


def _columns(context_doc: Dict[str, Any], profile: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Real columns (from the sync) with the meaning the profile gave each."""
    described = {}
    for c in ((profile or {}).get("shape") or {}).get("columns") or []:
        if isinstance(c, dict) and c.get("name"):
            described[str(c["name"]).lower()] = c
    out = []
    for c in context_doc.get("columns") or []:
        d = described.get(str(c.get("name", "")).lower(), {})
        out.append({
            "name": c.get("name"),
            "type": c.get("data_type"),
            "meaning": d.get("meaning") or c.get("comment"),
            "tags": d.get("tags"),
            "unit": d.get("unit"),
        })
    return out


def compose(context_doc: Dict[str, Any], profile: Optional[Dict[str, Any]],
            extra_lines: Optional[List[str]] = None) -> Dict[str, Any]:
    """The document for one entity: name, headline, searchable text, trust level.

    extra_lines carry facts gathered outside the profile — a pipeline's recent
    failures, for instance — so they are searchable too.
    """
    kind = context_doc.get("kind") or context_doc["entity_id"].split(":", 1)[0]
    name = context_doc.get("name") or context_doc["entity_id"].split(":")[-1]
    full_name = context_doc.get("full_name") or name
    attrs = context_doc.get("attributes") or {}
    p = profile or {}

    headline = first_sentence(p.get("summary")) or first_sentence(attrs.get("comment")) or f"{kind} {full_name}"

    lines = [f"{kind}: {full_name}", f"name: {name} ({name_words(full_name)})"]
    # The enrichment's free-text domain; data products proper are entities of their own (kind "product").
    for label, key in (("domain", "data_product"), ("summary", "summary"), ("purpose", "purpose"),
                       ("operational notes", "operational_notes")):
        if p.get(key):
            lines.append(f"{label}: {' '.join(str(p[key]).split())}")
    if attrs.get("comment"):
        lines.append(f"comment: {attrs['comment']}")
    tags = [t for t in p.get("semantic_tags") or [] if isinstance(t, str)]
    if tags:
        lines.append("tags: " + ", ".join(tags))
    classification = p.get("classification") or {}
    if classification.get("status") == "ok":
        lines.append(f"role: {classification.get('role')} · layer: {classification.get('layer')}")
    shape = p.get("shape") or {}
    if shape.get("grain"):
        lines.append(f"grain: {' '.join(str(shape['grain']).split())}")

    if kind == "table":
        cols = _columns(context_doc, profile)
        if cols:
            lines.append(f"columns ({len(cols)}):")
            for c in cols:
                meaning = f": {c['meaning']}" if c.get("meaning") else ""
                lines.append(f"- {c['name']} ({c.get('type') or '?'}){meaning}")
        # Its SQL, where kept: "which table computes cancel_rate" should find the table that does.
        from kairos_kb.enrichment.pipeline import table_code

        code = table_code(attrs.get("properties") or {}, attrs.get("table_type"))
        if code:
            lines.append(f"{code.get('kind')}" + (f" (dbt {code['dbt_model']})" if code.get("dbt_model") else "") + ":")
            lines.append(" ".join(code["sql"].split())[:4000])
        facts = p.get("facts") or {}
        writers = [w.get("writer") for w in facts.get("writers") or [] if w.get("linkable")]
        if writers:
            lines.append("written by: " + ", ".join(writers))
        others = sorted({e["other"].split(":")[-1] for e in context_doc.get("known_lineage") or []
                         if e.get("level") == "TABLE"})
        if others:
            lines.append("lineage neighbours: " + ", ".join(others[:30]))
    elif kind == "job":
        tasks = [t.get("task_key") for t in context_doc.get("tasks") or []]
        if tasks:
            lines.append("tasks: " + ", ".join(t for t in tasks if t))
    elif kind == "task":
        facts = p.get("facts") or {}
        for t in facts.get("tables_in_code") or []:
            modes = "/".join(t.get("modes") or [])
            lines.append(f"{modes or 'uses'}: {t.get('table')}")
        if attrs.get("notebook_path"):
            lines.append(f"notebook: {attrs['notebook_path']}")
    elif kind == "product":
        # A data product: a business concept served as one unit — what it measures, by what, from where.
        lines.append(f"data product{' · ' + attrs['domain'] if attrs.get('domain') else ''} · {attrs.get('status') or 'draft'}")
        if attrs.get("purpose"):
            lines.append(f"purpose: {attrs['purpose']}")
        for m in attrs.get("metrics") or []:
            lines.append(f"metric {m.get('name')}: {m.get('label') or ''} — {m.get('description') or ''}"
                         + (f" ({m['unit']})" if m.get("unit") else ""))
        dims = [d.get("label") or d.get("name") for d in attrs.get("dimensions") or []]
        if dims:
            lines.append("sliced by: " + ", ".join(dims))
        for g in attrs.get("glossary") or []:
            lines.append(f"term {g.get('term')}: {g.get('meaning')}")
        if attrs.get("tools"):
            lines.append("tools: " + ", ".join(attrs["tools"]))
        inputs = [l["entity_id"].split(":", 2)[-1] for l in context_doc.get("links") or [] if l["direction"] == "out"]
        if inputs:
            lines.append("built from: " + ", ".join(inputs))
    elif context_doc.get("origin") is not None:
        # A platform object: what the platform says, its links and its code.
        lines.append(f"{kind.replace('_', ' ')} on {attrs.get('platform') or 'the platform'}"
                     + (f", in {attrs['parent']}" if attrs.get("parent") else ""))
        props = attrs.get("properties") or {}
        flat = []
        for k, v in props.items():
            if isinstance(v, dict):
                flat += [f"{k}.{k2}: {v2}" for k2, v2 in v.items() if not isinstance(v2, (dict, list))]
            elif not isinstance(v, list):
                flat.append(f"{k}: {v}")
        if flat:
            lines.append("properties: " + "; ".join(flat)[:2500])
        if attrs.get("grants"):
            lines.append("granted to: " + ", ".join(f"{r} ({', '.join(p)})" for r, p in list(attrs["grants"].items())[:20]))
        for l in (context_doc.get("links") or [])[:60]:
            arrow = "→" if l["direction"] == "out" else "←"
            lines.append(f"{l['relation'].lower().replace('_', ' ')} {arrow} {l['entity_id'].split(':', 2)[-1]}")
        if context_doc.get("definition"):
            lines.append("definition: " + " ".join(str(context_doc["definition"]).split())[:4000])
    lines += extra_lines or []
    text = "\n".join(lines)
    # A product is checked by code and confirmed by a person, not profiled by enrichment.
    trust = (("verified" if attrs.get("status") == "confirmed" else "profiled") if kind == "product"
             else trust_level(profile))
    return {
        "kind": kind,
        "name": full_name if kind in ("table", "schema", "catalog") else name,
        "headline": headline,
        "text": text,
        "trust_level": trust,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


# ── the index ────────────────────────────────────────────────────────


FAILED_RESULTS = ("FAILED", "TIMEDOUT", "INTERNAL_ERROR")


def failure_line(task_key: str, started, detail: Optional[Dict[str, Any]], status_line: Optional[str]) -> str:
    """One searchable line for a failed task run: when, which task, the error, where."""
    detail = detail or {}
    loc = detail.get("location") or {}
    where = ", ".join(x for x in (
        f"cell {loc['cell']}" if loc.get("cell") else None,
        f"line {loc['line']}" if loc.get("line") else None,
        loc.get("function"),
    ) if x)
    error = (detail.get("error") or status_line or "no error recorded").splitlines()[0][:200]
    when = started.date().isoformat() if started else "unknown date"
    return f"failure ({when}): task {task_key} run failed: {error}" + (f" [{where}]" if where else "")


async def failure_lines(db: AsyncSession, entity_id: str, limit: int = 3) -> List[str]:
    """Recent failures of a task or pipeline, so agents can find them by their error."""
    from kairos_kb.models.run import Run
    from kairos_kb.models.task_run import TaskRun

    kind = entity_id.split(":", 1)[0]
    query = select(TaskRun).where(TaskRun.result_state.in_(FAILED_RESULTS))
    if kind == "task":
        task_id = (await db.execute(select(Task.id).where(Task.entity_id == entity_id))).scalar()
        if task_id is None:
            return []
        query = query.where(TaskRun.task_id == task_id)
    elif kind == "job":
        job_id = (await db.execute(select(Job.id).where(Job.entity_id == entity_id))).scalar()
        if job_id is None:
            return []
        query = query.join(Run, Run.id == TaskRun.run_id).where(Run.job_id == job_id)
    else:
        return []
    rows = (await db.execute(query.order_by(TaskRun.start_time.desc().nulls_last()).limit(limit))).scalars()
    return [failure_line(tr.task_key, tr.start_time, tr.error_detail, tr.error_message) for tr in rows]


def _indexable(entity_id: str) -> bool:
    from kairos_kb.enrichment.context import OBJECT_KINDS

    kind = entity_id.split(":", 1)[0]
    return kind in INDEXED_KINDS or kind in OBJECT_KINDS or kind == "product"


async def _workspace_of(db: AsyncSession, entity_id: str):
    model = INDEXED_KINDS.get(entity_id.split(":", 1)[0])
    if model is None:
        from kairos_kb.models.discovered import DiscoveredEntity

        model = DiscoveredEntity
    return (await db.execute(select(model.workspace_id).where(model.entity_id == entity_id))).scalar()


_SEARCH_VECTOR_SQL = sql_text(
    """
    UPDATE context_documents SET search_vector =
        setweight(to_tsvector('english', coalesce(:words, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(headline, '')), 'B') ||
        setweight(to_tsvector('english', text), 'C')
    WHERE entity_id = :entity_id
    """
)


async def index_entities(entity_ids: Iterable[str], *, force: bool = False) -> Dict[str, int]:
    """Build or refresh the documents for these entities. Unchanged ones are skipped."""
    ids = [e for e in dict.fromkeys(entity_ids) if _indexable(e)]
    counts = {"indexed": 0, "unchanged": 0, "missing": 0, "embedded": 0}
    from kairos_kb.context.embeddings import embed_texts

    for start in range(0, len(ids), CHUNK):
        chunk = ids[start:start + CHUNK]
        async with async_session_factory() as db:
            pending = []
            for entity_id in chunk:
                context_doc = await gather_context(db, entity_id)
                if context_doc is None:
                    counts["missing"] += 1
                    await db.execute(delete(ContextDocument).where(ContextDocument.entity_id == entity_id))
                    continue
                extra = await failure_lines(db, entity_id)
                from kairos_kb.products.mesh import products_using

                feeds = await products_using(db, entity_id)
                if feeds:
                    extra.append("data products: " + ", ".join(
                        f"{x['product']} ({x['role'] or 'input'})" for x in feeds))
                doc = compose(context_doc, await load_profile(db, entity_id), extra)
                existing = (await db.execute(
                    select(ContextDocument).where(ContextDocument.entity_id == entity_id)
                )).scalars().first()
                if (existing and not force and existing.content_hash == doc["content_hash"]
                        and existing.embedding is not None):
                    counts["unchanged"] += 1
                    continue
                pending.append((entity_id, doc, existing))

            vectors = await embed_texts([d["text"] for _, d, _ in pending]) if pending else None
            now = datetime.now(timezone.utc)
            for i, (entity_id, doc, existing) in enumerate(pending):
                row = existing
                if row is None:
                    workspace_id = await _workspace_of(db, entity_id)
                    if workspace_id is None:
                        counts["missing"] += 1
                        continue
                    row = ContextDocument(entity_id=entity_id, workspace_id=workspace_id)
                    db.add(row)
                row.kind, row.name, row.headline = doc["kind"], doc["name"], doc["headline"]
                row.text, row.trust_level, row.content_hash = doc["text"], doc["trust_level"], doc["content_hash"]
                row.embedding = vectors[i] if vectors else None
                row.indexed_at = now
                await db.flush()
                await db.execute(_SEARCH_VECTOR_SQL, {"entity_id": entity_id, "words": name_words(doc["name"])})
                counts["indexed"] += 1
                counts["embedded"] += 1 if vectors else 0
            await db.commit()
    return counts


async def workspace_entity_ids(db: AsyncSession, workspace_id) -> List[str]:
    from kairos_kb.models.discovered import DiscoveredEntity

    ids: List[str] = []
    for model in INDEXED_KINDS.values():
        ids += [r[0] for r in (await db.execute(
            select(model.entity_id).where(model.workspace_id == workspace_id)
        )).all()]
    # Platform objects: warehouses, roles, integrations, stages, procedures, policies …
    ids += [r[0] for r in (await db.execute(select(DiscoveredEntity.entity_id).where(
        DiscoveredEntity.workspace_id == workspace_id, DiscoveredEntity.origin.in_(("platform", "product"))))).all()]
    return ids


async def index_workspace(workspace_id, progress=None) -> Dict[str, int]:
    """Index every entity in a workspace, and drop documents for entities that are gone."""
    async with async_session_factory() as db:
        ids = await workspace_entity_ids(db, workspace_id)
        gone = await db.execute(
            delete(ContextDocument).where(
                ContextDocument.workspace_id == workspace_id, ContextDocument.entity_id.not_in(ids)
            )
        )
        await db.commit()
    totals = {"indexed": 0, "unchanged": 0, "missing": 0, "embedded": 0, "removed": gone.rowcount or 0}
    for start in range(0, len(ids), CHUNK):
        chunk = ids[start:start + CHUNK]
        if progress:
            progress.set_step(f"Indexing entities for agents ({start + len(chunk)} of {len(ids)})",
                              index=start + len(chunk), total=len(ids), unit="entity")
        counts = await index_entities(chunk)
        for k, v in counts.items():
            totals[k] += v
        if progress:
            progress.bump("documents", counts["indexed"] + counts["unchanged"])
    return totals
