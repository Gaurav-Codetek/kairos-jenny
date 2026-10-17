"""Everything an agent needs about one entity, with trust and usage as fields.

A card answers, in order: what is this, how far can I trust that, what does
one row mean, what is in it, where does it come from and go, how do I use
it, and what should I watch out for. Prose sits next to structure; nothing
an agent needs to filter or branch on is buried in a paragraph.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.context.documents import _columns, load_profile, trust_level
from kairos_kb.enrichment.context import gather_context
from kairos_kb.enrichment.pipeline import canonical_relation, profile_digest
from kairos_kb.models.context import ContextDocument, ContextFeedback
from kairos_kb.models.discovered import DiscoveredRelation
from kairos_kb.models.entity_profile import EntityProfile
from kairos_kb.models.job import Job
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.models.run import Run
from kairos_kb.models.task import Task
from kairos_kb.models.task_run import TaskRun
from kairos_kb.models.workspace import Workspace

# What the verification stage reports when a check passes (grain says "holds").
PASSING_RESULTS = {"ok", "holds", "corrected", "repaired", "skipped"}

GENERIC_COLUMNS = {"created_at", "updated_at", "load_date", "load_ts", "ingestion_time", "_rescued_data",
                   "source", "source_file", "file_name", "etl_timestamp", "insert_date", "update_date"}


def _short_name(entity_id: str) -> str:
    # kind:workspace:name — the name may itself hold colons (s3://bucket/path, task ids).
    parts = entity_id.split(":", 2)
    if len(parts) == 3 and parts[0] == "task" and ":" in parts[2]:
        return parts[2].rsplit(":", 1)[-1]
    return parts[-1]


def _pii_columns(columns: List[Dict[str, Any]]) -> List[str]:
    return [c["name"] for c in columns if "pii" in str(c.get("tags") or "").lower()]


def key_columns(profile: Optional[Dict[str, Any]], columns: List[Dict[str, Any]]) -> List[str]:
    """The grain key if stated, else columns that look like identifiers."""
    stated = str((profile or {}).get("grain_key") or "")
    if stated.strip():
        return [k.strip() for k in stated.split(",") if k.strip()]
    ids = []
    for c in columns:
        n = str(c.get("name") or "")
        tags = str(c.get("tags") or "").lower()
        if "id" in tags.split(",") or n.lower().endswith(("_id", "_key", "_vid", "_code")):
            ids.append(n)
    return ids[:6]


def example_sql(full_name: str, columns: List[Dict[str, Any]], keys: List[str]) -> Optional[str]:
    if not full_name or not columns:
        return None
    picked = [k for k in keys if any(c["name"] == k for c in columns)]
    for c in columns:
        if len(picked) >= 8:
            break
        tags = str(c.get("tags") or "").lower()
        if c["name"] not in picked and ("measure" in tags or "time" in tags or "date" in c["name"].lower()):
            picked.append(c["name"])
    for c in columns:
        if len(picked) >= 8:
            break
        if c["name"] not in picked:
            picked.append(c["name"])
    quoted = ".".join(f"`{p}`" for p in full_name.split("."))
    return f"SELECT {', '.join(picked)}\nFROM {quoted}\nLIMIT 100"


def caveats(profile: Optional[Dict[str, Any]], columns: List[Dict[str, Any]], stale: bool,
            feedback: List[Dict[str, Any]]) -> List[str]:
    """What an agent should know before relying on this entity."""
    out: List[str] = []
    p = profile or {}
    if not profile:
        out.append("Not profiled yet: only the platform's own metadata (names, types, comments) is known.")
    for check in (p.get("verification") or {}).get("checks") or []:
        if check.get("result") not in PASSING_RESULTS and check.get("result") is not None:
            out.append(f"Check '{check.get('check')}' {check.get('result')}: {check.get('detail')}")
    facts = p.get("facts") or {}
    if facts.get("is_empty"):
        out.append("The table is empty.")
    classification = p.get("classification") or {}
    if (classification.get("scratch_or_test") or 0) >= 0.6:
        out.append("Looks like a scratch or test table — prefer a curated alternative if one exists.")
    pii = _pii_columns(columns)
    if pii:
        out.append(f"Contains personal data in {len(pii)} column(s): {', '.join(pii[:8])}"
                   + (" …" if len(pii) > 8 else "") + ". Handle under your data policy.")
    if stale:
        out.append("Re-profiling is due: the entity, or Kairos's profiling pipeline, changed after this profile "
                   "was written. The description is likely still right; the checks may be out of date.")
    questions = p.get("open_questions")
    if isinstance(questions, list):
        out += [f"Open question: {q}" for q in questions[:5] if q]
    elif isinstance(questions, str) and questions.strip():
        out.append(f"Open question: {questions.strip()}")
    for f in feedback[:5]:
        out.append(f"Reported by {f['reporter']} ({f['kind']}): {f['message']}")
    return out


async def _open_feedback(db: AsyncSession, entity_id: str) -> List[Dict[str, Any]]:
    rows = (await db.execute(
        select(ContextFeedback).where(ContextFeedback.entity_id == entity_id, ContextFeedback.status == "open")
        .order_by(ContextFeedback.created_at.desc()).limit(10)
    )).scalars().all()
    return [{"id": str(r.id), "kind": r.kind, "reporter": r.reporter, "message": r.message,
             "field": r.field, "suggestion": r.suggestion, "at": r.created_at.isoformat()} for r in rows]


async def _links(db: AsyncSession, entity_id: str) -> List[Dict[str, Any]]:
    """Data-flow links touching this entity, in data-flow direction, with their evidence."""
    rels = (await db.execute(select(DiscoveredRelation).where(
        DiscoveredRelation.status != "contradicted",
        or_(DiscoveredRelation.source_entity_id == entity_id, DiscoveredRelation.target_entity_id == entity_id),
    ))).scalars().all()
    out = []
    for r in rels:
        canonical, flip, _ = canonical_relation(r.relation_type)
        if not canonical:
            continue
        src, dst = (r.target_entity_id, r.source_entity_id) if flip else (r.source_entity_id, r.target_entity_id)
        out.append({
            "source": src, "relation": canonical, "target": dst,
            "evidence": r.source_ref or ("verified" if r.status == "verified" else "discovered by enrichment"),
            "status": r.status, "confidence": round(r.confidence or 0, 2),
        })
    return out


def _entry(entity_id: str, evidence: str, **extra) -> Dict[str, Any]:
    return {"entity_id": entity_id, "name": _short_name(entity_id), "evidence": evidence, **extra}


async def _products_using(db: AsyncSession, entity_id: str) -> List[Dict[str, Any]]:
    from kairos_kb.products.mesh import products_using

    return [{k: x[k] for k in ("product", "id", "role", "status", "health")} for x in await products_using(db, entity_id)]


async def entity_card(db: AsyncSession, entity_id: str, *, max_columns: int = 150) -> Optional[Dict[str, Any]]:
    context_doc = await gather_context(db, entity_id)
    if context_doc is None:
        return None
    profile = await load_profile(db, entity_id)
    stored = (await db.execute(select(EntityProfile).where(EntityProfile.entity_id == entity_id))).scalars().first()
    stale = bool(stored and stored.source_hash != profile_digest(context_doc))
    feedback = await _open_feedback(db, entity_id)
    kind = context_doc.get("kind")
    p = profile or {}
    classification = p.get("classification") or {}
    verification = p.get("verification") or {}

    card: Dict[str, Any] = {
        "entity_id": entity_id,
        "kind": kind,
        "name": context_doc.get("name"),
        "full_name": context_doc.get("full_name"),
        "workspace": entity_id.split(":")[1] if entity_id.count(":") >= 2 else None,
        # The products this entity feeds (data products are entities in the map); the enrichment's
        # free-text domain is kept as "domain".
        "data_products": await _products_using(db, entity_id),
        "domain": p.get("data_product"),
        "summary": p.get("summary") or (context_doc.get("attributes") or {}).get("comment"),
        "purpose": p.get("purpose"),
        "tags": [t for t in p.get("semantic_tags") or [] if isinstance(t, str)],
        "trust": {
            "level": trust_level(profile),
            "profiled_at": p.get("generated_at"),
            "stale": stale,
            "verification_passed": verification.get("passed"),
            "checks": [
                {"check": c.get("check"), "result": c.get("result"), "detail": c.get("detail")}
                for c in verification.get("checks") or []
            ],
            "classification": (
                {"role": classification.get("role"), "layer": classification.get("layer"),
                 "role_confidence": classification.get("role_confidence"),
                 "layer_confidence": classification.get("layer_confidence")}
                if classification.get("status") == "ok" else None
            ),
            "open_feedback": len(feedback),
            "how_to_read": ("verified: profiled and every automated check passed · profiled: described by "
                            "Kairos, some checks failed or were not run · synced: platform metadata only"),
        },
    }

    links = await _links(db, entity_id)

    if kind == "table":
        columns = _columns(context_doc, profile)
        keys = key_columns(profile, columns)
        grain_check = next((c for c in verification.get("checks") or [] if c.get("check") == "grain"), None)
        facts = p.get("facts") or {}
        card["shape"] = {
            "grain": (p.get("shape") or {}).get("grain"),
            "grain_key": keys,
            "grain_key_unique": {"holds": True, "ok": True, "fails": False}.get((grain_check or {}).get("result")),
            "column_count": len(columns),
            "columns": columns[:max_columns],
            "columns_truncated": max(0, len(columns) - max_columns),
        }
        card["facts"] = {k: facts.get(k) for k in ("row_count", "size_bytes", "table_type", "format",
                                                   "last_write", "is_empty") if k in facts} or {
            k: (context_doc.get("attributes") or {}).get(k) for k in ("table_type", "data_source_format")
        }
        produced_by = [_entry(w["entity_id"], "Delta history", operations=w.get("operations"),
                              last_write=w.get("last_write"))
                       for w in facts.get("writers") or [] if w.get("linkable") and w.get("entity_id")]
        seen = {e["entity_id"] for e in produced_by}
        for link in links:
            if link["target"] == entity_id and link["relation"] == "WRITES_TABLE" and link["source"] not in seen:
                produced_by.append(_entry(link["source"], link["evidence"], status=link["status"]))
                seen.add(link["source"])
        read_by = [_entry(l["source"], l["evidence"], status=l["status"]) for l in links
                   if l["target"] == entity_id and l["relation"] == "READS_TABLE"]
        lineage = (await db.execute(select(LineageEdge).where(
            LineageEdge.source_type == "TABLE",
            or_(LineageEdge.source_entity_id == entity_id, LineageEdge.target_entity_id == entity_id),
        ).limit(100))).scalars().all()
        upstream = sorted({e.source_entity_id for e in lineage if e.target_entity_id == entity_id})
        downstream = sorted({e.target_entity_id for e in lineage if e.source_entity_id == entity_id})
        for l in links:
            if l["relation"] == "FEEDS":
                if l["target"] == entity_id and l["source"] not in upstream:
                    upstream.append(l["source"])
                if l["source"] == entity_id and l["target"] not in downstream:
                    downstream.append(l["target"])
        card["flow"] = {
            "produced_by": produced_by,
            "read_by": read_by,
            "upstream_tables": [_entry(e, "Databricks lineage") for e in upstream],
            "downstream_tables": [_entry(e, "Databricks lineage") for e in downstream],
        }
        from kairos_kb.context.joins import suggest_joins

        card["usage"] = {
            "example_sql": example_sql(context_doc.get("full_name") or "", columns, keys),
            "join_candidates": (await suggest_joins(db, entity_id, limit=5)).get("candidates", []),
            "how_it_is_built": _how_built(p.get("creation")),
        }
        card["caveats"] = caveats(profile, columns, stale, feedback)
        # The SQL that defines or builds the table, where the platform keeps it (Snowflake views,
        # dynamic tables, dbt / CTAS build statements, COPY loads).
        from kairos_kb.enrichment.pipeline import table_code

        attrs = context_doc.get("attributes") or {}
        props = attrs.get("properties") or {}
        code = table_code(props, attrs.get("table_type"))
        if code:
            sources = [t["table"] for t in (p.get("facts") or {}).get("tables_in_code") or []
                       if "read" in (t.get("modes") or [])]
            card["code"] = {**code, **({"reads": sources} if sources else {})}
        keys = {k: props[k] for k in ("primary_key", "unique_keys", "foreign_keys") if props.get(k)}
        if keys:
            card["declared_keys"] = keys
        extra = {k: props[k] for k in ("usage", "writes", "clustering_key") if props.get(k)}
        if extra:
            card["facts"] = {**(card.get("facts") or {}), **extra}
        from kairos_kb.knowledge.context import table_knowledge

        industry = await table_knowledge(db, entity_id, [c["name"] for c in columns])
        if industry:
            card["industry"] = industry

    elif kind == "job":
        tasks = context_doc.get("tasks") or []
        task_profiles = {
            r.entity_id: r.summary for r in (await db.execute(select(EntityProfile).where(
                EntityProfile.entity_id.in_([t["entity_id"] for t in tasks])
            ))).scalars()
        }
        card["tasks"] = [
            {"entity_id": t["entity_id"], "task_key": t["task_key"], "depends_on": t.get("depends_on"),
             "summary": task_profiles.get(t["entity_id"])}
            for t in tasks
        ]
        card["schedule"] = (context_doc.get("attributes") or {}).get("schedule")
        card["flow"] = await _pipeline_io(db, [entity_id] + [t["entity_id"] for t in tasks])
        card["health"] = await _run_health(db, entity_id)
        card["caveats"] = caveats(profile, [], stale, feedback)[:6]

    elif kind == "task":
        facts = p.get("facts") or {}
        in_code = facts.get("tables_in_code") or []
        io = await _pipeline_io(db, [entity_id])
        for t in in_code:
            bucket = "writes" if "write" in (t.get("modes") or []) else "reads"
            if not any(e["entity_id"] == t["entity_id"] for e in io[bucket]):
                io[bucket].append(_entry(t["entity_id"], f"code line {(t.get('lines') or ['?'])[0]}"))
        card["flow"] = io
        attrs = context_doc.get("attributes") or {}
        card["code"] = {"notebook_path": attrs.get("notebook_path"), "task_type": attrs.get("task_type"),
                        "depends_on": attrs.get("depends_on")}
        card["health"] = await _task_history(db, entity_id)
        card["caveats"] = caveats(profile, [], stale, feedback)[:6]
    elif context_doc.get("origin") is not None:
        # A platform object: warehouse, role, integration, stage, procedure, policy, location …
        attrs = context_doc.get("attributes") or {}
        card["platform"] = attrs.get("platform")
        card["in"] = attrs.get("parent")
        card["owner"] = attrs.get("owner")
        if attrs.get("comment"):
            card["comment"] = attrs["comment"]
        if context_doc.get("definition"):
            card["definition"] = context_doc["definition"]
        card["properties"] = attrs.get("properties") or {}
        if attrs.get("grants"):
            card["granted_to"] = attrs["grants"]
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for link in context_doc.get("links") or []:
            label = f"{link['relation']} ({'to' if link['direction'] == 'out' else 'from'})"
            grouped.setdefault(label, []).append({"entity_id": link["entity_id"],
                                                  "name": link["entity_id"].split(":", 2)[-1],
                                                  "evidence": link.get("rationale")})
        card["links"] = grouped
        reads = (p.get("facts") or {}).get("tables_in_code") or []
        if reads:
            card["code_touches"] = [{"table": t["table"], "how": t.get("modes"), "lines": t.get("lines")} for t in reads]
        card["caveats"] = caveats(profile, [], stale, feedback)[:6]
        if (card["properties"] or {}).get("describable") is False:
            card["caveats"].insert(0, card["properties"].get("note"))
    else:
        card["children"] = [
            _entry(t["entity_id"], "catalog") for t in (context_doc.get("tables") or context_doc.get("schemas") or [])
            if isinstance(t, dict) and t.get("entity_id")
        ][:100]
        card["caveats"] = caveats(profile, [], stale, feedback)[:4]
        if kind in ("catalog", "schema", "workspace"):
            card["objects"] = await _objects_in(db, entity_id)

    card["feedback"] = feedback
    card["as_of"] = await _as_of(db, entity_id, profile)
    card["next"] = _next_steps(kind)
    await _name_pipelines(db, card)
    await _describe_neighbours(db, card.get("flow") or {})
    return card


async def _objects_in(db: AsyncSession, entity_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """The platform objects a database, schema or workspace holds, by kind."""
    from kairos_kb.enrichment.runner import platform_objects_in
    from kairos_kb.models.discovered import DiscoveredEntity

    ws = (await db.execute(select(Workspace).where(Workspace.name == entity_id.split(":")[1]))).scalars().first()
    if ws is None:
        return {}
    ids = await platform_objects_in(db, ws, entity_id)
    if not ids:
        return {}
    names = dict((await db.execute(select(DiscoveredEntity.entity_id, DiscoveredEntity.full_name)
                                   .where(DiscoveredEntity.entity_id.in_([i for i, _ in ids])))).all())
    out: Dict[str, List[Dict[str, Any]]] = {}
    for eid, k in sorted(ids, key=lambda x: (x[1], x[0])):
        out.setdefault(k, []).append({"entity_id": eid, "name": names.get(eid) or eid.split(":", 2)[-1]})
    return out


async def _describe_neighbours(db: AsyncSession, flow: Dict[str, Any]) -> None:
    """Say what each linked table is, so an agent can tell an output from a log without another call."""
    entries = [e for items in flow.values() if isinstance(items, list) for e in items
               if isinstance(e, dict) and str(e.get("entity_id", "")).startswith("table:")]
    if not entries:
        return
    ids = {e["entity_id"] for e in entries}
    docs = {d.entity_id: d for d in (await db.execute(
        select(ContextDocument).where(ContextDocument.entity_id.in_(ids))
    )).scalars()}
    roles = {}
    for pid, tags in (await db.execute(
        select(EntityProfile.entity_id, EntityProfile.semantic_tags).where(EntityProfile.entity_id.in_(ids))
    )).all():
        role = next((t[5:] for t in tags or [] if isinstance(t, str) and t.startswith("role:")), None)
        if role:
            roles[pid] = role
    for e in entries:
        doc = docs.get(e["entity_id"])
        if doc:
            e["what_it_is"] = doc.headline
            e["trust_level"] = doc.trust_level
        if e["entity_id"] in roles:
            e["role"] = roles[e["entity_id"]]


async def _name_pipelines(db: AsyncSession, value: Any) -> None:
    """A job's entity id ends in its numeric id; show agents its name."""
    entries: List[Dict[str, Any]] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            if str(v.get("entity_id", "")).startswith("job:") and "name" in v:
                entries.append(v)
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(value)
    if not entries:
        return
    names = dict((await db.execute(
        select(Job.entity_id, Job.name).where(Job.entity_id.in_({e["entity_id"] for e in entries}))
    )).all())
    for e in entries:
        e["name"] = names.get(e["entity_id"], e["name"])


async def _pipeline_io(db: AsyncSession, entity_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    rels = (await db.execute(select(DiscoveredRelation).where(
        DiscoveredRelation.status != "contradicted",
        or_(DiscoveredRelation.source_entity_id.in_(entity_ids), DiscoveredRelation.target_entity_id.in_(entity_ids)),
    ))).scalars().all()
    reads: Dict[str, Dict[str, Any]] = {}
    writes: Dict[str, Dict[str, Any]] = {}
    for r in rels:
        canonical, flip, _ = canonical_relation(r.relation_type)
        src, dst = (r.target_entity_id, r.source_entity_id) if flip else (r.source_entity_id, r.target_entity_id)
        if src not in entity_ids or not dst.startswith("table:"):
            continue
        evidence = r.source_ref or ("verified" if r.status == "verified" else "discovered by enrichment")
        if canonical == "WRITES_TABLE":
            writes.setdefault(dst, _entry(dst, evidence, via=_short_name(src), status=r.status))
        elif canonical == "READS_TABLE":
            reads.setdefault(dst, _entry(dst, evidence, via=_short_name(src), status=r.status))
    return {"reads": list(reads.values()), "writes": list(writes.values())}


FAILED_RESULTS = {"FAILED", "TIMEDOUT", "INTERNAL_ERROR"}
RUN_HISTORY = 10
# Characters of a table's SQL in the compact card.
CODE_IN_SUMMARY = 2500
TRACE_IN_CARD = 2500


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _seconds(start, end) -> Optional[float]:
    return round((end - start).total_seconds(), 1) if start and end else None


def task_failure(tr: TaskRun, *, with_trace: bool = False) -> Optional[Dict[str, Any]]:
    """What went wrong in one failed task run, as recorded from its output."""
    if (tr.result_state or "").upper() not in FAILED_RESULTS:
        return None
    detail = tr.error_detail or {}
    out: Dict[str, Any] = {
        "error": detail.get("error") or tr.error_message,
        "location": detail.get("location"),
        "detail_read_at": _iso(tr.output_fetched_at),
    }
    if not tr.output_fetched_at:
        out["note"] = "Only Databricks' status line was recorded for this run; the exact error was not read."
    if with_trace and tr.error_trace:
        trace = tr.error_trace
        out["trace_tail"] = trace if len(trace) <= TRACE_IN_CARD else "…" + trace[-TRACE_IN_CARD:]
    return out


async def _run_health(db: AsyncSession, job_entity_id: str) -> Dict[str, Any]:
    """A pipeline's recent runs, and for each failure which task failed and with what error."""
    job = (await db.execute(select(Job).where(Job.entity_id == job_entity_id))).scalars().first()
    if not job:
        return {}
    runs = (await db.execute(
        select(Run).where(Run.job_id == job.id).order_by(Run.start_time.desc().nulls_last()).limit(RUN_HISTORY)
    )).scalars().all()
    states = Counter((r.result_state or r.state or "UNKNOWN") for r in runs)
    failed_tasks: Dict[Any, List[TaskRun]] = {}
    if runs:
        for tr in (await db.execute(select(TaskRun).where(
            TaskRun.run_id.in_([r.id for r in runs]), TaskRun.result_state.in_(FAILED_RESULTS)
        ))).scalars():
            failed_tasks.setdefault(tr.run_id, []).append(tr)
    history = []
    for r in runs:
        entry: Dict[str, Any] = {
            "started_at": _iso(r.start_time),
            "result": r.result_state or r.state,
            "duration_s": round(r.execution_duration_ms / 1000, 1) if r.execution_duration_ms else None,
        }
        fails = failed_tasks.get(r.id, [])
        if fails:
            entry["failed_tasks"] = [{"task_key": t.task_key, **(task_failure(t) or {})} for t in fails]
        history.append(entry)
    return {
        "recent_runs": len(runs),
        "by_result": dict(states),
        "last_run_at": history[0]["started_at"] if history else None,
        "runs": history,
    }


async def _task_history(db: AsyncSession, task_entity_id: str) -> Dict[str, Any]:
    """A task's recent runs; the latest failure comes with its traceback."""
    task = (await db.execute(select(Task).where(Task.entity_id == task_entity_id))).scalars().first()
    if not task:
        return {}
    trs = (await db.execute(
        select(TaskRun).where(TaskRun.task_id == task.id)
        .order_by(TaskRun.start_time.desc().nulls_last()).limit(RUN_HISTORY)
    )).scalars().all()
    runs, traced = [], False
    for tr in trs:
        failure = task_failure(tr, with_trace=not traced)
        traced = traced or bool(failure)
        runs.append({
            "started_at": _iso(tr.start_time),
            "result": tr.result_state or tr.state,
            "duration_s": _seconds(tr.start_time, tr.end_time),
            "attempt": tr.attempt_number,
            **({"failure": failure} if failure else {}),
        })
    states = Counter(r["result"] or "UNKNOWN" for r in runs)
    return {"recent_runs": len(runs), "by_result": dict(states), "runs": runs}


async def _as_of(db: AsyncSession, entity_id: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """How old each part of this card is, so an agent can judge whether it is current."""
    name = entity_id.split(":")[1] if entity_id.count(":") >= 2 else None
    synced = None
    if name:
        synced = (await db.execute(select(Workspace.last_synced_at).where(Workspace.name == name))).scalar()
    return {
        "platform_synced_at": _iso(synced),
        "profiled_at": (profile or {}).get("generated_at"),
        "note": "Runs, schemas and links are as of the last sync; anything after it is not in the map yet.",
    }


def _next_steps(kind: Optional[str]) -> List[str]:
    if kind == "table":
        return ["find_join_path(this, other_table) before joining it to anything",
                "explore_entity(entity_id) to walk further along lineage",
                "report_context_issue(entity_id, ...) if anything here turns out to be wrong"]
    if kind in ("job", "task"):
        return ["get_context(table_entity_id) on the tables it reads or writes",
                "health lists recent runs; a failure shows the exact error, notebook cell and line"]
    return ["find_data(question) to search within it"]


async def context_counts(db: AsyncSession) -> Dict[str, int]:
    return dict((await db.execute(select(EntityProfile.kind, func.count()).group_by(EntityProfile.kind))).all())


# ── selective cards ──────────────────────────────────────────────────

SUMMARY_COLUMNS = 20
SUMMARY_RUNS = 5
SUMMARY_LIST = 8
TEXT_CHARS = 160


def _how_built(creation: Any) -> Any:
    """The profile's creation section. It should be an object with source_inputs, but model-written
    profiles sometimes hold a list of {label: text} pairs instead. Accept both."""
    if isinstance(creation, dict):
        return creation.get("source_inputs") or {k: v for k, v in creation.items() if v} or None
    if isinstance(creation, list):
        return [item for item in creation if item] or None
    return creation or None


def _short(value: Any, n: int = TEXT_CHARS) -> Any:
    if isinstance(value, str) and len(value) > n:
        return value[: n - 1].rstrip() + "…"
    return value


def summarize_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """A compact card: what an agent needs to decide and query, not everything Kairos holds.

    Kept whole: identity, summary, purpose, trust and checks, grain, caveats.
    Cut down: columns (keys, personal data and the first few, plus every
    column's name), lists of neighbours, run history (latest runs, no
    tracebacks). get_context(entity_id, detail="full") returns the rest.
    """
    out = dict(card)
    trust = dict(out.get("trust") or {})
    trust.pop("how_to_read", None)
    out["trust"] = trust

    shape = out.get("shape")
    if shape and shape.get("columns"):
        cols = shape["columns"]
        keys = {k.lower() for k in shape.get("grain_key") or []}
        pinned = [c for c in cols if c["name"].lower() in keys or "pii" in str(c.get("tags") or "").lower()]
        rest = [c for c in cols if c not in pinned]
        chosen = (pinned + rest)[: max(SUMMARY_COLUMNS, len(pinned))]
        order = {c["name"]: i for i, c in enumerate(cols)}
        chosen.sort(key=lambda c: order[c["name"]])
        out["shape"] = {
            **{k: v for k, v in shape.items() if k not in ("columns", "columns_truncated")},
            "columns": [{**c, "meaning": _short(c.get("meaning"), 120)} for c in chosen],
            "all_column_names": [c["name"] for c in cols],
            "columns_described": f"{len(chosen)} of {shape.get('column_count', len(cols))}",
        }

    flow = out.get("flow")
    if isinstance(flow, dict):
        out["flow"] = {
            k: [{**e, "what_it_is": _short(e.get("what_it_is"), 100)} if isinstance(e, dict) else e
                for e in v[:SUMMARY_LIST]] + ([{"more": len(v) - SUMMARY_LIST}] if len(v) > SUMMARY_LIST else [])
            if isinstance(v, list) else v
            for k, v in flow.items()
        }

    usage = out.get("usage")
    if isinstance(usage, dict):
        out["usage"] = {**usage, "join_candidates": (usage.get("join_candidates") or [])[:3]}

    if out.get("tasks"):
        out["tasks"] = [{**t, "summary": _short(t.get("summary"))} for t in out["tasks"]]

    health = out.get("health")
    if isinstance(health, dict) and health.get("runs"):
        runs = []
        for r in health["runs"][:SUMMARY_RUNS]:
            r = dict(r)
            if isinstance(r.get("failure"), dict):
                f = {k: v for k, v in r["failure"].items() if k != "trace_tail"}
                f["error"] = _short((f.get("error") or "").splitlines()[0] if f.get("error") else None, 200)
                r["failure"] = f
            if r.get("failed_tasks"):
                r["failed_tasks"] = [{**t, "error": _short((t.get("error") or "").splitlines()[0] if t.get("error") else None, 200)}
                                     for t in r["failed_tasks"]]
            runs.append(r)
        out["health"] = {**health, "runs": runs}

    out["caveats"] = [_short(c, 240) for c in (out.get("caveats") or [])[:6]]
    if isinstance(out.get("definition"), str) and len(out["definition"]) > CODE_IN_SUMMARY:
        out["definition"] = out["definition"][:CODE_IN_SUMMARY] + "\n-- …truncated; detail=\"full\" has all of it"
    if isinstance(out.get("links"), dict):
        out["links"] = {k: v[:SUMMARY_LIST] + ([{"more": len(v) - SUMMARY_LIST}] if len(v) > SUMMARY_LIST else [])
                        for k, v in out["links"].items()}
    if isinstance(out.get("objects"), dict):
        out["objects"] = {k: v[:SUMMARY_LIST] + ([{"more": len(v) - SUMMARY_LIST}] if len(v) > SUMMARY_LIST else [])
                          for k, v in out["objects"].items()}
    code = out.get("code")
    if isinstance(code, dict) and code.get("sql") and len(code["sql"]) > CODE_IN_SUMMARY:
        out["code"] = {**code, "sql": code["sql"][:CODE_IN_SUMMARY] + "\n-- …truncated; detail=\"full\" has all of it",
                       "sql_chars": len(code["sql"])}
    industry = out.get("industry")
    if isinstance(industry, dict):
        out["industry"] = {**industry, "dataset_type": [
            {k: (_short(v, 400) if k in ("pitfalls", "typical_uses") else v) for k, v in t.items()}
            for t in industry.get("dataset_type") or []]}
    out["detail"] = "summary — get_context(entity_id, detail=\"full\") adds every column, all runs and tracebacks"
    return out
