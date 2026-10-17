"""The staged enrichment pipeline around the enrichment agent.

  Stage 0  FACTS     code, no LLM — what Databricks and Kairos already know:
                     writers from Delta history (recorded as verified links),
                     table statistics, emptiness, existing relationships.
  Stage 1  CLASSIFY  Jev — layer, role and flags for a table. The role picks a
                     template: which fields the profile must have, and how
                     deep to investigate (a scratch table gets a light pass).
  Stage 2  PROFILE   the enrichment agent, given facts + class + template.
  Stage 3  VERIFY    code — the profile's format, column coverage, a grain
                     check with COUNT DISTINCT, and consistency with the facts.

Facts and verification are written into the profile by code, so prose can
never contradict them. The relationship vocabulary is fixed here too: the
agent may only record links from a small set of verbs, never containment
(the sync already knows it) and never name-based guesses.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_, select

from kairos_kb.connectors.databricks import DatabricksConnector
from kairos_kb.db.engine import async_session_factory
from kairos_kb.models.discovered import DiscoveredRelation
from kairos_kb.models.job import Job
from kairos_kb.models.lineage_edge import LineageEdge

logger = logging.getLogger(__name__)

# Bump when a change to the stages would produce materially different
# profiles. Profiles written by an older version are then re-profiled
# instead of skipped as unchanged.
PIPELINE_VERSION = "staged-2026.09.2"

# Parts of an entity's context that move without the entity changing: who
# reached it this run, its latest runs, its change log.
_VOLATILE_CONTEXT = ("parent_context", "recent_runs", "change_events")


def profile_digest(context_doc: Dict[str, Any]) -> str:
    """What a profile was built from: the entity's stable source plus the pipeline version.

    Unchanged digest → the profile still describes the entity. A changed one
    means the entity changed, or Kairos learned to profile it better.
    """
    import hashlib

    stable = {k: v for k, v in context_doc.items() if k not in _VOLATILE_CONTEXT}
    payload = json.dumps(stable, sort_keys=True, default=str)
    return hashlib.sha256(f"{PIPELINE_VERSION}\n{payload}".encode("utf-8")).hexdigest()


# ── Relationship vocabulary ──────────────────────────────────────────

CANONICAL_RELATIONS = {
    "READS_TABLE": "this entity reads the target table",
    "WRITES_TABLE": "this entity writes (creates, inserts, merges into) the target table",
    "READS_FILE": "this entity reads a file or directory in a volume or cloud path",
    "WRITES_FILE": "this entity writes a file or directory in a volume or cloud path",
    "FEEDS": "data flows from this entity into the target (table to table)",
    "DEPENDS_ON": "this task or job runs only after the target",
    "TRIGGERS": "this entity starts the target job or task",
    "RUNS_NOTEBOOK": "this task or job executes the target notebook",
    "USES_EXTERNAL": "this entity calls an external API, connection or service",
    "STORED_AT": "this table's data lives at the target location",
}

_CONTAINMENT = re.compile(r"CONTAIN|BELONG|IN_CATALOG|IN_SCHEMA|PART_OF|MEMBER_OF|CHILD_OF|PARENT|HAS_TASK|HAS_TABLE")
_SPECULATIVE = re.compile(r"NAME_|POSSIBL|POTENTIAL|LIKELY|SIBLING|SIMILAR|VARIANT|RELATED|ASSOCIAT|CANDIDATE|EQUIVALENT|COPY|MAYBE|GUESS|SHARE|SAME_")
# Real, but not data flow: say it in the profile text, not as a graph edge.
_NOT_FLOW = re.compile(r"LOGS_FOR|MENTION|STATUS_FOR|GATES|SERVES|OWNED|OWNS|MONITOR|DOCUMENT|DESCRIB|CLUSTER")

# (pattern, canonical, flip). flip=True: the verb is passive ("READ_BY"), so the
# stored direction is reversed to keep every edge in data-flow order.
# Order matters: passive forms first, then files, then derivation, then the
# notebook verbs, and only then the generic read/write catch-alls.
_RULES: List[Tuple[re.Pattern, str, bool]] = [
    (re.compile(r"(READ|CONSUM)\w*_BY"), "READS_TABLE", True),
    (re.compile(r"(WRIT|CREAT|GENERAT|PRODUC|LOADED|IMPLEMENTED)\w*_BY"), "WRITES_TABLE", True),
    (re.compile(r"READ\w*(VOLUME|FILE|PATH|DIRECTOR)"), "READS_FILE", False),
    (re.compile(r"WRIT\w*(VOLUME|FILE|PATH|DIRECTOR)"), "WRITES_FILE", False),
    (re.compile(r"DERIVE"), "FEEDS", True),
    (re.compile(r"FEED|CONTRIBUT|TRANSFORMS_TO|FLOWS_TO"), "FEEDS", False),
    (re.compile(r"(RUN|EXECUT|USES|CALLS|INVOK)\w*NOTEBOOK"), "RUNS_NOTEBOOK", False),
    (re.compile(r"READ|CONSUM|USES_TABLE|QUER"), "READS_TABLE", False),
    (re.compile(r"WRIT|CREAT|PRODUC|LOAD|MERGE|INSERT|UPSERT|OVERWRIT"), "WRITES_TABLE", False),
    (re.compile(r"BLOCKS|UPSTREAM_OF"), "DEPENDS_ON", True),
    (re.compile(r"DEPENDS|WAITS|DOWNSTREAM_OF"), "DEPENDS_ON", False),
    (re.compile(r"TRIGGER|STARTS|LAUNCH"), "TRIGGERS", False),
    (re.compile(r"EXTERNAL|API|CONNECTION|ENDPOINT|SERVICE"), "USES_EXTERNAL", False),
    (re.compile(r"STORE|LOCATION"), "STORED_AT", False),
]


def canonical_relation(verb: str) -> Tuple[Optional[str], bool, str]:
    """Map a free-form verb onto the vocabulary. Returns (canonical, flip, reason).

    canonical is None when the link must not be recorded; reason says why, so
    the agent can correct itself rather than retry the same thing.
    """
    v = re.sub(r"[^A-Z_]", "_", (verb or "").strip().upper())
    if not v:
        return None, False, "relation_type is empty"
    if v in CANONICAL_RELATIONS:
        return v, False, "canonical"
    if _CONTAINMENT.search(v):
        return None, False, "containment (catalog/schema/table, job/task) is already known from the sync — not recorded"
    if _SPECULATIVE.search(v):
        return None, False, "speculative or name-based links are not recorded — put the suspicion in open_questions"
    if _NOT_FLOW.search(v):
        return None, False, "not a data-flow relationship — describe it in the profile text instead"
    for pattern, canonical, flip in _RULES:
        if pattern.search(v):
            return canonical, flip, f"normalised {v} → {canonical}"
    return None, False, "not in the vocabulary: use one of " + ", ".join(CANONICAL_RELATIONS)


# Which kinds each verb may connect, source → target. Only kinds Kairos knows
# for certain are judged; open-vocabulary kinds the agent mints (genie_space,
# dashboard, …) are let through, since the list of those is not closed.
_ACTORS = {"job", "task", "notebook", "query", "dashboard", "pipeline", "alert", "app", "genie_space"}
_TABLES = {"table", "view"}
_FILES = {"volume", "file", "path", "location", "external_location"}
_KNOWN_KINDS = {"workspace", "catalog", "schema", "table", "column", "job", "task", "run", "task_run",
                "notebook", "volume", "file"}
VERB_KINDS: Dict[str, Tuple[Optional[set], Optional[set]]] = {
    "READS_TABLE": (_ACTORS, _TABLES),
    "WRITES_TABLE": (_ACTORS, _TABLES),
    "READS_FILE": (_ACTORS | _TABLES, _FILES),
    "WRITES_FILE": (_ACTORS, _FILES),
    "FEEDS": (_TABLES | _FILES, _TABLES),
    "DEPENDS_ON": (_ACTORS, _ACTORS),
    "TRIGGERS": (_ACTORS, _ACTORS),
    "RUNS_NOTEBOOK": ({"job", "task"}, {"notebook"}),
    "USES_EXTERNAL": (_ACTORS | _TABLES, None),
    "STORED_AT": (_TABLES | {"volume"}, _FILES),
}


def check_link_kinds(canonical: str, source_kind: str, target_kind: str) -> Optional[str]:
    """Why this verb cannot join these kinds, or None if it can."""
    allowed = VERB_KINDS.get(canonical)
    if not allowed:
        return None
    for role, kind, kinds in (("source", source_kind, allowed[0]), ("target", target_kind, allowed[1])):
        if kinds is None or kind not in _KNOWN_KINDS:
            continue
        if kind not in kinds:
            return (f"{canonical} cannot have a {kind} as its {role} "
                    f"(expected {', '.join(sorted(k for k in kinds if k in _KNOWN_KINDS or k in _ACTORS))})")
    if canonical == "USES_EXTERNAL" and target_kind in _TABLES | {"schema", "catalog", "column"}:
        return "USES_EXTERNAL is for external services and connections, not warehouse objects — use READS_TABLE"
    return None


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def is_person_reference(target: str) -> bool:
    """A person or an interactive notebook session — a fact, never a graph entity.

    Workspace paths contain e-mail addresses too (/Workspace/Users/a@b.com/nb),
    so a reference with a path is not a person.
    """
    t = (target or "").strip()
    if t.lower().startswith(("interactive notebook", "user:")):
        return True
    return bool(_EMAIL.search(t)) and "/" not in t


# ── Stage 0: facts ───────────────────────────────────────────────────


def _q(full_name: str) -> str:
    return ".".join(f"`{p}`" for p in full_name.split("."))


def _stat(properties: Any, key: str) -> Optional[int]:
    try:
        return int((properties or {}).get(key))
    except (TypeError, ValueError):
        return None


async def gather_facts(context_doc: Dict[str, Any], workspace_name: str, workspace_id=None) -> Dict[str, Any]:
    """Everything code can establish before an LLM is involved."""
    entity_id = context_doc["entity_id"]
    kind = context_doc.get("kind")
    facts: Dict[str, Any] = {"known_relationships": await _known_relationships(entity_id)}
    if kind == "task" and workspace_id is not None:
        facts.update(await task_code_facts(context_doc, workspace_id))
    if context_doc.get("origin") is not None:
        facts.update(await object_facts(context_doc, workspace_id))
    if kind != "table":
        return facts

    attrs = context_doc.get("attributes") or {}
    props = attrs.get("properties") or {}
    rows = attrs.get("row_count")
    if rows is None:
        rows = _stat(props, "spark.sql.statistics.numRows")
    size = attrs.get("size_bytes") or _stat(props, "spark.sql.statistics.totalSize")
    columns = context_doc.get("columns") or []
    facts.update({
        "row_count": rows,
        "size_bytes": size,
        "column_count": len(columns),
        "is_empty": rows == 0,
        "table_type": attrs.get("table_type"),
        "format": attrs.get("data_source_format"),
    })
    facts.update(await _history_facts(context_doc["full_name"], workspace_name))
    facts.update(await table_code_facts(context_doc, workspace_id))
    return facts


async def object_facts(context_doc: Dict[str, Any], workspace_id) -> Dict[str, Any]:
    """A platform object: what the platform says about it, its links, and its code scanned for tables."""
    attrs = context_doc.get("attributes") or {}
    facts: Dict[str, Any] = {
        "object_kind": context_doc.get("kind"),
        "platform_properties": attrs.get("properties"),
        "grants": attrs.get("grants"),
        "platform_links": [f"{l['direction']} {l['relation']} {l['entity_id'].split(':', 2)[-1]}"
                           for l in context_doc.get("links") or []][:60],
    }
    code = context_doc.get("definition")
    if code and workspace_id is not None:
        from kairos_kb.models.table import Table

        async with async_session_factory() as db:
            known = {fn.lower(): eid for fn, eid in (await db.execute(
                select(Table.full_name, Table.entity_id).where(Table.workspace_id == workspace_id))).all()}
        scan = scan_code(code, known)
        kind = str(context_doc.get("kind") or "object").replace("_", " ").upper()
        facts.update({"code_available": True, "code_source": f"{kind.lower()} definition", "code_chars": len(code),
                      **scan, "_code": code, "code_label": f"THE {kind}'S DEFINITION"})
    return {k: v for k, v in facts.items() if v not in (None, [], {})}


def table_code(props: Dict[str, Any], table_type: Optional[str]) -> Optional[Dict[str, Any]]:
    """The SQL that defines or builds a table, when the platform keeps it, with where it came from.

    Snowflake: a view's or dynamic table's definition; for tables, the latest CREATE … AS SELECT /
    MERGE / INSERT from query history (dbt models, CTAS jobs) and the latest COPY INTO that loads it.
    """
    props = props or {}
    parts, origin = [], {}
    if props.get("definition"):
        kind = "dynamic table definition" if (table_type or "").upper() == "DYNAMIC_TABLE" else "view definition"
        parts.append(props["definition"])
        origin = {"kind": kind}
    if props.get("build_sql"):
        b = props.get("build") or {}
        parts.append(props["build_sql"])
        origin = origin or {"kind": f"build statement ({(b.get('statement_type') or 'SQL').replace('_', ' ').lower()})",
                            **{k: b.get(k) for k in ("at", "by", "role", "dbt_model", "query_id", "rows") if b.get(k)}}
    if props.get("load_sql"):
        parts.append(props["load_sql"])
        origin.setdefault("kind", "load statement (copy into)")
        origin["loaded_by"] = "COPY INTO"
    if not parts:
        return None
    return {"sql": "\n\n".join(parts), **origin}


async def table_code_facts(context_doc: Dict[str, Any], workspace_id) -> Dict[str, Any]:
    """Scan a table's own SQL the way task code is scanned: the tables it reads, by line."""
    attrs = context_doc.get("attributes") or {}
    code = table_code(attrs.get("properties") or {}, attrs.get("table_type"))
    if not code:
        return {}
    from kairos_kb.models.table import Table

    async with async_session_factory() as db:
        known = {fn.lower(): eid for fn, eid in (await db.execute(
            select(Table.full_name, Table.entity_id).where(Table.workspace_id == workspace_id)
        )).all()}
    scan = scan_code(code["sql"], known)
    own = (context_doc.get("full_name") or "").lower()
    scan["tables_in_code"] = [t for t in scan.get("tables_in_code") or [] if t["table"] != own]
    # A definition's FROM tables are its sources even where the scanner could not tell read from write.
    for t in scan["tables_in_code"]:
        if not t.get("modes") or t["modes"] == ["named"]:
            t["modes"] = ["read"]
    origin = {k: v for k, v in code.items() if k != "sql"}
    return {"code_available": True, "code_source": origin.get("kind"), "code_origin": origin,
            "code_chars": len(code["sql"]), **scan, "_code": code["sql"],
            "code_label": f"THE TABLE'S {str(origin.get('kind') or 'SQL').upper()}"}


async def record_code_sources(facts: Dict[str, Any], table_entity_id: str, workspace_id, run_id) -> int:
    """A table's definition or build statement names its sources exactly: record each as a verified FEEDS link."""
    if not facts.get("code_available") or not facts.get("code_origin"):
        return 0
    origin = facts["code_origin"]
    recorded = 0
    async with async_session_factory() as db:
        for t in facts.get("tables_in_code") or []:
            if "read" not in (t.get("modes") or []):
                continue
            line = (t.get("lines") or [None])[0]
            rationale = (f"The {origin.get('kind')} of this table reads {t['table']}"
                         + (f" (line {line})" if line else "")
                         + (f"; dbt model {origin['dbt_model']}" if origin.get("dbt_model") else "")
                         + (f"; last run {origin['at']} by {origin.get('by')}" if origin.get("at") else "") + ".")
            exists = (await db.execute(select(DiscoveredRelation).where(
                DiscoveredRelation.source_entity_id == t["entity_id"],
                DiscoveredRelation.target_entity_id == table_entity_id,
                DiscoveredRelation.relation_type == "FEEDS",
            ))).scalars().first()
            if exists:
                exists.status, exists.confidence, exists.rationale = "verified", 1.0, rationale
                exists.observed_at = datetime.now(timezone.utc)
            else:
                db.add(DiscoveredRelation(
                    workspace_id=workspace_id, source_entity_id=t["entity_id"], target_entity_id=table_entity_id,
                    relation_type="FEEDS", confidence=1.0, rationale=rationale,
                    source_ref=origin.get("query_id") or origin.get("kind"), run_id=run_id, status="verified",
                    observed_at=datetime.now(timezone.utc),
                ))
                recorded += 1
        await db.commit()
    return recorded


async def _known_relationships(entity_id: str) -> List[Dict[str, Any]]:
    """Links Kairos already holds for this entity — so the agent neither repeats nor contradicts them."""
    async with async_session_factory() as db:
        rels = (await db.execute(
            select(DiscoveredRelation).where(or_(
                DiscoveredRelation.source_entity_id == entity_id,
                DiscoveredRelation.target_entity_id == entity_id,
            ))
        )).scalars().all()
        lineage = (await db.execute(
            select(LineageEdge).where(or_(
                LineageEdge.source_entity_id == entity_id, LineageEdge.target_entity_id == entity_id,
            )).limit(50)
        )).scalars().all()
    out = []
    for r in rels:
        if r.status == "contradicted":
            continue  # history says otherwise
        canonical, flip, _ = canonical_relation(r.relation_type)
        if not canonical:
            continue  # containment and guesses are noise to the agent
        src, dst = (r.target_entity_id, r.source_entity_id) if flip else (r.source_entity_id, r.target_entity_id)
        out.append({"source": src, "relation": canonical, "target": dst, "confidence": round(r.confidence, 2),
                    "origin": "verified" if r.status == "verified" else "discovered"})
    for e in lineage:
        out.append({"source": e.source_entity_id, "relation": "FEEDS", "target": e.target_entity_id,
                    "confidence": 1.0, "origin": "databricks_lineage"})
    # Deduplicate, strongest first.
    seen, unique = set(), []
    for r in sorted(out, key=lambda x: -x["confidence"]):
        key = (r["source"], r["relation"], r["target"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique[:60]


async def _platform_connector(workspace_name: str):
    """The connector for a workspace's platform (Databricks or Snowflake). Tests replace this."""
    from kairos_kb.connectors.factory import connector_for_workspace_name

    return await connector_for_workspace_name(workspace_name)


async def _history_facts(full_name: str, workspace_name: str) -> Dict[str, Any]:
    """Who writes the table: Delta history on Databricks, access history on Snowflake."""
    from kairos_kb.connectors.factory import sql_dialect

    try:
        connector = await _platform_connector(workspace_name)
        if sql_dialect(connector) == "snowflake":
            history = await connector.write_history(full_name)
        else:
            result = await connector.execute_query(f"DESCRIBE HISTORY {_q(full_name)} LIMIT 50")
            history = DatabricksConnector._rows_from_statement_result(result)
    except Exception as exc:  # noqa: BLE001 — views and non-Delta tables have no history
        return {"history_available": False, "history_error": str(exc)[:160]}

    writers: Dict[str, Dict[str, Any]] = {}
    for h in history:
        op = h.get("operation") or ""
        if op.upper() in ("COMPUTE STATS", "OPTIMIZE", "VACUUM START", "VACUUM END", "SET TBLPROPERTIES", "ANALYZE"):
            continue  # maintenance, not a writer of the data
        job = _parse_json(h.get("job"))
        if job and job.get("jobId"):
            key = f"job:{job['jobId']}"
            label = job.get("jobName") or f"job {job['jobId']}"
            kind = "job"
        elif h.get("notebook"):
            nb = _parse_json(h.get("notebook")) or {}
            key = f"notebook:{nb.get('notebookId') or h.get('userName')}"
            label = f"interactive notebook session by {h.get('userName') or 'an unknown user'}"
            kind = "notebook_session"
        else:
            key = f"user:{h.get('userName')}"
            label = h.get("userName") or "unknown"
            kind = "user"
        w = writers.setdefault(key, {"writer": label, "kind": kind, "operations": set(), "last_write": None,
                                     "job_id": (job or {}).get("jobId"), "writes": 0,
                                     # A person or an interactive session is a fact about the
                                     # table, not an entity to add to the graph.
                                     "linkable": kind == "job"})
        w["operations"].add(op)
        w["writes"] += 1
        ts = str(h.get("timestamp") or "")
        if ts and (w["last_write"] is None or ts > w["last_write"]):
            w["last_write"] = ts

    for w in writers.values():
        w["operations"] = sorted(w["operations"])
        if w["job_id"]:
            w["entity_id"] = f"job:{workspace_name}:{w['job_id']}"
    return {
        "history_available": True,
        "writers": sorted(writers.values(), key=lambda w: w["last_write"] or "", reverse=True),
        "last_write": max((w["last_write"] for w in writers.values() if w["last_write"]), default=None),
        "history_versions_seen": len(history),
    }


def _parse_json(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if not value:
        return None
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, ValueError):
        return None


async def record_history_writers(facts: Dict[str, Any], table_entity_id: str, workspace_id, run_id) -> int:
    """Delta history names the job that writes a table: record it as a verified link."""
    recorded = 0
    async with async_session_factory() as db:
        for w in facts.get("writers") or []:
            job_entity = w.get("entity_id")
            if not job_entity:
                continue
            if not (await db.execute(select(Job.id).where(Job.entity_id == job_entity))).first():
                continue  # a job outside the synced workspace
            exists = (await db.execute(select(DiscoveredRelation).where(
                DiscoveredRelation.source_entity_id == job_entity,
                DiscoveredRelation.target_entity_id == table_entity_id,
                DiscoveredRelation.relation_type == "WRITES_TABLE",
            ))).scalars().first()
            rationale = (f"Delta history: {', '.join(w['operations'])} by job '{w['writer']}' "
                         f"({w['writes']} version(s), last {w['last_write']}).")
            if exists:
                exists.status, exists.confidence, exists.rationale = "verified", 1.0, rationale
                exists.observed_at = datetime.now(timezone.utc)
            else:
                db.add(DiscoveredRelation(
                    workspace_id=workspace_id, source_entity_id=job_entity, target_entity_id=table_entity_id,
                    relation_type="WRITES_TABLE", confidence=1.0, rationale=rationale,
                    source_ref="DESCRIBE HISTORY", run_id=run_id, status="verified",
                    observed_at=datetime.now(timezone.utc),
                ))
                recorded += 1
        await db.commit()
    return recorded


def pipeline_job_id(entity_id: str) -> Optional[str]:
    """The Databricks job id behind a job or task entity (job:<ws>:<id>, task:<ws>:<id>:<key>)."""
    parts = entity_id.split(":")
    if parts[0] in ("job", "task") and len(parts) >= 3:
        return parts[2]
    return None


def contradicted_writes(rels: List[Any], facts: Dict[str, Any], table_entity_id: str) -> List[Any]:
    """Stored "X writes this table" links that Delta history contradicts.

    Only unverified links from a job or task are judged, and only when history
    was actually read. A link is contradicted when its pipeline's job id is not
    among the jobs history shows writing the table. Retiring is reversible:
    should that job write the table later, record_history_writers verifies it.
    """
    if not facts.get("history_available"):
        return []
    writer_jobs = {str(w["job_id"]) for w in facts.get("writers") or [] if w.get("job_id")}
    out = []
    for r in rels:
        if r.status in ("verified", "contradicted"):
            continue
        canonical, flip, _ = canonical_relation(r.relation_type)
        if canonical != "WRITES_TABLE":
            continue
        writer, written = (r.target_entity_id, r.source_entity_id) if flip else (r.source_entity_id, r.target_entity_id)
        if written != table_entity_id:
            continue
        job_id = pipeline_job_id(writer)
        if job_id and job_id not in writer_jobs:
            out.append(r)
    return out


async def retire_contradicted_writes(facts: Dict[str, Any], table_entity_id: str) -> List[str]:
    """Mark contradicted writer links; returns the writers retired."""
    async with async_session_factory() as db:
        rels = (await db.execute(select(DiscoveredRelation).where(or_(
            DiscoveredRelation.source_entity_id == table_entity_id,
            DiscoveredRelation.target_entity_id == table_entity_id,
        )))).scalars().all()
        retired = []
        seen = facts.get("history_versions_seen")
        for r in contradicted_writes(rels, facts, table_entity_id):
            writer = r.target_entity_id if r.target_entity_id != table_entity_id else r.source_entity_id
            r.status = "contradicted"
            r.rationale = (f"Contradicted by Delta history: job {pipeline_job_id(writer)} is not among the "
                           f"writers of the last {seen} version(s). Was: {r.rationale or ''}")[:4000]
            retired.append(writer)
        await db.commit()
    return retired


def facts_summary(facts: Dict[str, Any]) -> str:
    """One line for the live feed."""
    parts = []
    if facts.get("row_count") is not None:
        parts.append(f"{facts['row_count']:,} rows")
    if facts.get("column_count"):
        parts.append(f"{facts['column_count']} columns")
    writers = [w["writer"] for w in facts.get("writers") or []]
    if writers:
        parts.append("written by " + ", ".join(writers[:2]) + (" …" if len(writers) > 2 else ""))
    elif facts.get("history_available") is False:
        parts.append("no Delta history")
    parts.append(f"{len(facts.get('known_relationships') or [])} known links")
    return " · ".join(parts)


# ── Stage 1: classification (Jev) ────────────────────────────────────

LAYERS = {
    "RAW_LANDING": "Raw data landed as-is from files or source systems, before any cleaning; often all-string columns plus file or ingestion metadata.",
    "BRONZE_STAGING": "Lightly cleaned or typed copies of raw data, staged for transformation; still close to the source shape.",
    "SILVER_CURATED": "Cleaned, conformed and integrated data: facts and dimensions joined and validated for reuse.",
    "GOLD_SERVING": "Business-ready outputs for reporting, BI or applications: marts, aggregates, KPIs.",
    "OPERATIONAL": "Not business data: pipeline logs, run status, configuration, data-quality or profiling output.",
    "OTHER": "None of the above, or not enough information to tell.",
}

ROLES = {
    "FACT_EVENT": "Records individual business events or transactions (a sale line, a call, a claim, a shipment), usually with an event or transaction id, a timestamp and raw measures; one row per event.",
    "DIMENSION_MASTER": "Describes business entities (customers, providers, organisations, products): one row per entity, identified by a key, with descriptive attributes.",
    "MAPPING_CROSSWALK": "Links identifiers from two systems or entity types, for example NPI to HCO or product code to drug class; mostly pairs of keys.",
    "AGGREGATE_MART": "Pre-summarised measures grouped by an entity and/or a period, such as totals per organisation per day; columns look like an entity key, a date and TOTAL_ / SUM_ / COUNT_ / AVG_ measures, with no event id.",
    "RAW_FILE_INGEST": "A raw load of a source file or feed kept close to the file's shape, with ingestion columns such as file path or insert date.",
    "LOG_AUDIT": "Records runs, loads, statuses or errors of a pipeline or process; one row per run or event of the process.",
    "PROFILING_SNAPSHOT": "Statistics about other data: column profiles, null rates, distinct counts, row counts, quality metrics.",
    "CONFIG_CONTROL": "Settings or metadata that drive a pipeline's behaviour: file-to-table mappings, schema mappings, parameters.",
    "SCRATCH_TEST": "A temporary, experimental, test or one-off analysis table not part of a maintained pipeline (names like test, tmp, sample, my_, percentages).",
    "OTHER": "None of the above, or not enough information to tell.",
}

# Per role: what the profile must contain, and what code will verify.
ROLE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "FACT_EVENT": {"grain_key": "required", "light": False, "must": [
        "grain: exactly what one row represents (one event / line item)",
        "grain_key: the column(s) that identify one row — Kairos will verify they are unique",
        "the time column(s) and the measures, with units",
        "the dimensions it references (keys to other tables)"]},
    "DIMENSION_MASTER": {"grain_key": "required", "light": False, "must": [
        "the business key as grain_key — Kairos will verify it is unique",
        "descriptive attributes and which ones hold personal data",
        "which facts or mappings reference this dimension, if seen"]},
    "MAPPING_CROSSWALK": {"grain_key": "required", "light": False, "must": [
        "the two identifiers being mapped, and their source systems",
        "grain_key: the pair (or single key) that should be unique — Kairos will verify",
        "the cardinality (one-to-one, one-to-many) as observed"]},
    "AGGREGATE_MART": {"grain_key": "required", "light": False, "must": [
        "grain_key: the group-by columns — Kairos will verify they are unique",
        "each measure and how it is aggregated",
        "the source table(s) it is built from, if seen"]},
    "RAW_FILE_INGEST": {"grain_key": "optional", "light": False, "must": [
        "the source file, feed or system and how it lands (the writer is in the facts)",
        "the ingestion metadata columns (file path, insert date, …)",
        "which downstream table consumes it, if seen"]},
    "LOG_AUDIT": {"grain_key": "optional", "light": False, "must": [
        "which process writes it (see facts) and what one row records",
        "the status / outcome columns and how to read them"]},
    "PROFILING_SNAPSHOT": {"grain_key": "optional", "light": False, "must": [
        "which dataset it profiles, and what one row measures",
        "each metric column"]},
    "CONFIG_CONTROL": {"grain_key": "optional", "light": False, "must": [
        "which pipeline reads it and which keys change its behaviour",
        "each setting column"]},
    "SCRATCH_TEST": {"grain_key": "skip", "light": True, "must": [
        "a short summary of what it seems to be and who created it (facts)",
        "whether anything depends on it — if nothing does, say it looks safe to ignore"]},
    "OTHER": {"grain_key": "optional", "light": False, "must": [
        "grain, columns, and how it is produced and consumed"]},
}


def _classification_state(context_doc: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, Any]:
    attrs = context_doc.get("attributes") or {}
    return {
        "table": context_doc.get("full_name"),
        "comment": attrs.get("comment"),
        "table_type": attrs.get("table_type"),
        "columns": [f"{c.get('name')} ({c.get('data_type')})" for c in (context_doc.get("columns") or [])][:120],
        "row_count": facts.get("row_count"),
        "is_empty": facts.get("is_empty"),
        "written_by": [f"{w['writer']}: {', '.join(w['operations'])}" for w in facts.get("writers") or []][:5],
    }


async def classify_table(context_doc: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, Any]:
    """Jev: layer, role and flags. Never raises; unconfigured or failed → status says so."""
    from kairos_kb.agent.jev_rca import _jev_client  # shared client construction

    client, err = _jev_client()
    if err:
        return {**err, "role": "OTHER", "layer": "OTHER"}
    from typesafe_sdk import Choice, Noul

    started = time.perf_counter()
    try:
        response = await client.system_one(
            state=_classification_state(context_doc, facts),
            questions={
                "layer": Choice(instructions="Which layer of a lakehouse does this table belong to?", criteria=LAYERS),
                "role": Choice(instructions="What role does this table play? Judge from its columns, name, comment, size and who writes it.", criteria=ROLES),
                "scratch_or_test": Noul(instructions="The table is temporary, experimental, a test, or a one-off analysis rather than part of a maintained pipeline."),
                "personal_data": Noul(instructions="The columns hold information about individual people, such as names, NPI or DEA numbers of individual providers, addresses or dates of birth."),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}", "role": "OTHER", "layer": "OTHER"}
    finally:
        await client.aclose()

    from kairos_kb.config import get_settings

    threshold = get_settings().jev_rca_confidence_threshold
    a = response.answers
    role, layer = a["role"], a["layer"]
    return {
        "status": "ok",
        # Below the threshold the class does not drive a template.
        "role": role.choice if role.confidence >= threshold else "OTHER",
        "role_raw": role.choice,
        "role_confidence": round(role.confidence, 3),
        "role_top": [[k, round(v, 3)] for k, v in sorted(role.probabilities.items(), key=lambda kv: -kv[1])[:3]],
        "layer": layer.choice if layer.confidence >= threshold else "OTHER",
        "layer_confidence": round(layer.confidence, 3),
        "scratch_or_test": round(a["scratch_or_test"].noul, 3),
        "personal_data": round(a["personal_data"].noul, 3),
        "model": response.model,
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }


def role_brief(kind: str, classification: Optional[Dict[str, Any]], facts: Dict[str, Any]) -> Tuple[str, bool]:
    """The template text for the agent, and whether this is a light pass."""
    known = facts.get("known_relationships") or []
    shown = {k: v for k, v in facts.items() if k not in ("known_relationships", "_code", "code_label")}
    lines = [
        "FACTS established by code (authoritative — do not contradict them; do not re-derive them):",
        json.dumps(shown, default=str, indent=1)[:4000],
        "Writers with linkable=false are people or interactive sessions: mention them, never link them.",
        "",
        f"KNOWN RELATIONSHIPS ({len(known)}) — already recorded; do not link them again:",
        json.dumps(known[:40], default=str, indent=1)[:4000],
    ]
    if facts.get("_code"):
        lines += [
            "",
            f"{facts.get('code_label') or 'THE TASK' + chr(39) + 'S CODE'} (already read for you — do not read it "
            "again unless it is truncated):",
            facts["_code"][:MAX_CODE_IN_BRIEF] + ("\n…[truncated]" if len(facts["_code"]) > MAX_CODE_IN_BRIEF else ""),
            "tables_in_code lists every warehouse table the code names, with read/write/named from the "
            "surrounding code; confirm each against the code before linking it.",
        ]
        if kind == "table":
            lines.append("For a table, its sources from this SQL are already recorded as verified FEEDS links. Use "
                         "the SQL for meaning: how each column is derived, filters, joins, aggregation and grain.")
    light = False
    if kind == "table" and classification:
        role, template = effective_template(classification)
        light = template["light"] or bool(facts.get("is_empty"))
        lines += [
            "",
            f"CLASSIFICATION (a hypothesis from a fast classifier): role={role}, layer={classification.get('layer')}"
            + (f" (confidence {classification.get('role_confidence')})" if classification.get("role_confidence") else ""),
            "If the evidence clearly contradicts it, say so in save_profile's classification_feedback.",
            f"TEMPLATE for {role} — the profile MUST cover:",
            *[f"  - {m}" for m in template["must"]],
        ]
        if template["grain_key"] == "required":
            lines.append("  - pass grain_key to save_profile: the unique column(s), comma-separated, exactly as named.")
        if light:
            lines.append("LIGHT PASS: this table is empty or a scratch/test table. Do not investigate code; "
                         "write a brief profile from the facts and save it within a few turns.")
    if kind == "table":
        lines.append("COLUMNS: shape.columns must list EVERY column, one entry per column name — never group names.")
    if kind in OBJECT_BRIEF:
        lines += ["", f"TEMPLATE for a {kind.replace('_', ' ')} — the profile MUST cover:",
                  *[f"  - {m}" for m in OBJECT_BRIEF[kind]],
                  "Its platform properties, grants and links are in FACTS; explain them, do not just repeat them. "
                  "Put what the platform does not tell you in open_questions."]
    return "\n".join(lines), light


# What a profile must cover for each kind of platform object.
OBJECT_BRIEF: Dict[str, List[str]] = {
    "location": ["which cloud store and path this is", "which integrations allow it and which stages read it",
                 "which tables are loaded from it, how much and how recently"],
    "integration": ["what it connects to (provider, account, allowed and blocked locations or hosts)",
                    "which stages, pipes, functions or repositories use it", "its security implications"],
    "external_volume": ["where Iceberg data is stored", "which tables use it"],
    "warehouse": ["size, scaling and auto-suspend behaviour", "what runs on it (tasks, alerts, apps) and its credit use",
                  "any resource monitor limiting it"],
    "compute_pool": ["what it is for and its size", "what services run on it"],
    "resource_monitor": ["the quota, frequency and actions", "which warehouses it governs"],
    "role": ["what the role is for", "which roles it inherits and who holds it", "the privileges it grants, by object"],
    "database_role": ["what it is for and which database it governs", "who holds it"],
    "user": ["whether it is a person or service account", "its default role and warehouse", "the roles it holds"],
    "network_policy": ["what traffic it allows or blocks", "who it applies to"],
    "share": ["what is shared, in which direction and with whom"],
    "application": ["what the application does and who provides it"],
    "stage": ["where its files live (bucket and path) and through which integration",
              "the file format and copy options", "which tables are loaded from it, with paths and volumes"],
    "file_format": ["how it parses files (type, delimiter, header, nulls, compression)", "which stages and loads use it"],
    "sequence": ["what it numbers and which tables use it"],
    "tag": ["what it classifies and its allowed values", "which tables and columns carry it"],
    "policy": ["what it protects and how (the rule in its body, in plain words)", "which tables and columns it applies to",
               "who is exempt"],
    "secret": ["what it is for (never its value)", "which integrations or functions use it"],
    "network_rule": ["which hosts or addresses it allows or blocks", "which integrations use it"],
    "procedure": ["what the procedure does, step by step, from its code", "the tables it reads and writes",
                  "its arguments and return value", "which tasks call it"],
    "function": ["what it computes, from its code", "its inputs and output", "any external service it calls"],
    "pipe": ["what it loads, from which stage and path, into which table", "auto-ingest and its notification channel",
             "recent load health"],
    "alert": ["the condition it checks and the action it takes", "its schedule and warehouse"],
    "semantic_view": ["the business entities, dimensions and metrics it defines", "the tables behind it and how they join"],
    "cortex_search": ["what it searches and which columns", "the source data and refresh lag"],
    "notebook": ["what it is for", "its warehouse"], "streamlit": ["what the app shows and to whom", "its warehouse"],
    "model": ["what the model predicts and its versions"], "git_repository": ["which repository and what it holds"],
    "dbt_project": ["the dbt project, its models and where it runs"],
}


# ── Stage 3: verification ────────────────────────────────────────────

_UNKNOWN_WRITER = re.compile(r"(no (job|notebook|writer|pipeline)[^.]{0,60}(found|discovered)|writer[^.]{0,20}unknown|created_by: unknown|unknown[^.]{0,30}(job|writer|creator))", re.I)


def normalise_shape(shape: Any) -> Tuple[Any, List[str]]:
    """Coerce the shape block into a mapping with one entry per column."""
    notes: List[str] = []
    if isinstance(shape, str):
        from kairos_kb.enrichment.tools import _maybe_yaml

        parsed = _maybe_yaml(shape)
        if isinstance(parsed, dict):
            shape = parsed
            notes.append("shape was text; parsed into a structure")
        else:
            return {"notes": shape}, ["shape was unstructured text; kept as notes"]
    if not isinstance(shape, dict):
        return shape, notes
    cols = shape.get("columns")
    if isinstance(cols, dict):  # {name: meaning}
        cols = [{"name": k, "meaning": v} for k, v in cols.items()]
    if isinstance(cols, list):
        out = []
        for c in cols:
            if isinstance(c, str):  # "NAME: type; meaning"
                name, _, rest = c.partition(":")
                c = {"name": name.strip(), "meaning": rest.strip() or None}
            if not isinstance(c, dict):
                continue
            names = [n.strip() for n in str(c.get("name", "")).split(",") if n.strip()]
            if len(names) > 1:
                notes.append(f"split grouped column entry '{c.get('name')}'")
            for n in names or [""]:
                out.append({**c, "name": n})
        # One entry per column: the agent sometimes lists a column twice.
        seen: Dict[str, Dict[str, Any]] = {}
        for c in out:
            key = str(c.get("name", "")).lower()
            if key not in seen or (not seen[key].get("meaning") and c.get("meaning")):
                seen[key] = c
        if len(seen) < len(out):
            notes.append(f"merged {len(out) - len(seen)} duplicate column entries")
        shape["columns"] = list(seen.values())
    return shape, notes


def _align_to_real_columns(listed: List[Dict[str, Any]], real: List[str]) -> Tuple[List[Dict[str, Any]], str]:
    """Make every listed column name a real one.

    The agent sometimes annotates a name ("INVOICE_ITEM (as bigint if
    normalized)"): the annotation is folded into the real column's entry. A
    name that matches no real column at all is removed.
    """
    by_lower = {n.lower(): n for n in real if n}
    kept: Dict[str, Dict[str, Any]] = {}
    folded = removed = 0
    for c in listed:
        name = str(c.get("name", "")).strip().strip("`")
        key = name.lower()
        if key not in by_lower:
            base = re.split(r"\s*[\(\[:]|\s+-\s+|\s+as\s+", name, maxsplit=1)[0].strip().strip("`").lower()
            if base in by_lower:
                note = name[len(base):].strip(" ()[]:-")
                c = {**c, "name": by_lower[base], "note": "; ".join(filter(None, [c.get("note"), note]))}
                key = base
                folded += 1
            else:
                removed += 1
                continue
        else:
            c = {**c, "name": by_lower[key]}
        if key in kept:  # merge into the entry already there
            merged = kept[key]
            for k, v in c.items():
                if v and not merged.get(k):
                    merged[k] = v
            if c.get("note") and c.get("note") != merged.get("note"):
                merged["note"] = "; ".join(filter(None, [merged.get("note"), c["note"]]))
        else:
            kept[key] = c
    parts = []
    if folded:
        parts.append(f"folded {folded} annotated column name(s) into the real column")
    if removed:
        parts.append(f"removed {removed} listed column(s) that do not exist")
    return list(kept.values()), "; ".join(parts)


async def verify_profile(
    fields: Dict[str, Any],
    context_doc: Dict[str, Any],
    facts: Dict[str, Any],
    classification: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Check and repair the profile against the facts. Returns (fields, verification)."""
    checks: List[Dict[str, Any]] = []
    kind = context_doc.get("kind")

    # 1. Format.
    shape, notes = normalise_shape(fields.get("shape"))
    fields["shape"] = shape
    checks.append({"check": "profile_format", "result": "repaired" if notes else "ok", "detail": "; ".join(notes) or None})

    if kind == "table":
        # 2. Column coverage: every real column present, one entry each.
        real = [c.get("name") for c in context_doc.get("columns") or []]
        if isinstance(shape, dict):
            listed = shape.get("columns") if isinstance(shape.get("columns"), list) else []
            listed, fixed = _align_to_real_columns(listed, real)
            if fixed:
                checks[0]["result"] = "repaired"
                checks[0]["detail"] = "; ".join(filter(None, [checks[0].get("detail"), fixed]))
            described = {str(c.get("name", "")).lower() for c in listed}
            missing = [n for n in real if n and n.lower() not in described]
            real_types = {c.get("name"): c.get("data_type") for c in context_doc.get("columns") or []}
            for n in missing:
                listed.append({"name": n, "type": real_types.get(n), "meaning": None, "undocumented": True})
            shape["columns"] = listed
            documented = len(real) - len(missing)
            checks.append({"check": "column_coverage", "result": "ok" if not missing else "incomplete",
                           "detail": f"{documented} of {len(real)} columns described"
                           + (f"; {len(missing)} listed as undocumented" if missing else "")})

        # 3. Grain.
        checks.append(await _check_grain(fields.get("grain_key"), context_doc, facts, classification))

        # 4. Writer consistency: prose may not say "unknown" when history knows.
        writers = [w["writer"] for w in facts.get("writers") or []]
        creation = fields.get("creation")
        text = json.dumps(creation, default=str) if creation is not None else ""
        if writers:
            if not isinstance(creation, dict):
                creation = {"notes": creation} if creation else {}
            creation["writers_from_delta_history"] = writers
            fields["creation"] = creation
            contradicted = bool(_UNKNOWN_WRITER.search(text))
            checks.append({"check": "writer_consistency", "result": "corrected" if contradicted else "ok",
                           "detail": ("the profile said the writer was unknown; Delta history names "
                                      if contradicted else "writers from Delta history: ") + ", ".join(writers)})

    failed = [c for c in checks if c["result"] in ("fails", "incomplete")]
    verification = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "passed": not failed,
        "checks": checks,
    }
    if any(c["check"] == "grain" and c["result"] == "fails" for c in checks):
        q = [c for c in checks if c["check"] == "grain"][0]["detail"]
        fields["open_questions"] = (fields.get("open_questions") or []) + [f"Grain claim does not hold: {q}"]
    return fields, verification


async def _check_grain(grain_key: Any, context_doc: Dict[str, Any], facts: Dict[str, Any],
                       classification: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    role, template = effective_template(classification)
    requirement = template["grain_key"]
    keys = [k.strip().strip("`") for k in str(grain_key or "").split(",") if k.strip()]
    if not keys:
        result = "missing" if requirement == "required" else "skipped"
        return {"check": "grain", "result": result,
                "detail": "no grain_key given" + (f" (required for {role})" if requirement == "required" else "")}
    if facts.get("is_empty"):
        return {"check": "grain", "result": "skipped", "detail": "table is empty"}
    real = {c.get("name", "").lower(): c.get("name") for c in context_doc.get("columns") or []}
    unknown = [k for k in keys if k.lower() not in real]
    if unknown:
        return {"check": "grain", "result": "fails", "detail": f"grain_key names columns that do not exist: {unknown}"}
    from kairos_kb.connectors.factory import quote_column, quote_table, sql_dialect

    connector = await _platform_connector(context_doc["entity_id"].split(":")[1])
    if sql_dialect(connector) == "snowflake":
        cols = ", ".join(quote_column(connector, real[k.lower()]) for k in keys)
        table = quote_table(connector, context_doc["full_name"])
        sql = f"SELECT COUNT(*) AS n, (SELECT COUNT(*) FROM (SELECT DISTINCT {cols} FROM {table})) AS k FROM {table}"
    else:
        cols = ", ".join(f"`{real[k.lower()]}`" for k in keys)
        sql = f"SELECT COUNT(*) AS n, COUNT(DISTINCT struct({cols})) AS k FROM {_q(context_doc['full_name'])}"
    try:
        rows = DatabricksConnector._rows_from_statement_result(await connector.execute_query(sql))
        low = {key.lower(): v for key, v in rows[0].items()}
        n, k = int(low["n"]), int(low["k"])
    except Exception as exc:  # noqa: BLE001
        return {"check": "grain", "result": "error", "detail": f"could not run the check: {str(exc)[:120]}"}
    key_text = " + ".join(real[k.lower()] for k in keys)
    if n == k:
        return {"check": "grain", "result": "holds", "detail": f"{key_text} is unique across {n:,} rows", "key": keys}
    return {"check": "grain", "result": "fails", "key": keys,
            "detail": f"{key_text} is not unique: {n - k:,} duplicate rows out of {n:,}"}


def verification_summary(verification: Dict[str, Any]) -> str:
    parts = [f"{c['check'].replace('_', ' ')}: {c['result']}" for c in verification.get("checks", [])]
    return " · ".join(parts)


# ── Stage 0 for tasks: what the code names ───────────────────────────
#
# A deterministic scan, not an interpretation: every catalog.schema.table the
# code mentions that the warehouse knows, every /Volumes path, and whether the
# surrounding code writes, reads, or merely names it. The agent confirms and
# links; it no longer spends turns finding the names.

_THREE_PART = re.compile(r"(?<![\w.`-])`?([A-Za-z0-9_-]+)`?\.`?([A-Za-z0-9_-]+)`?\.`?([A-Za-z0-9_-]+)`?(?![\w-])")
_VOLUME = re.compile(r"/Volumes/[A-Za-z0-9_./-]+")
_WRITE_CUE = re.compile(r"saveAsTable|insertInto|INSERT\s+(INTO|OVERWRITE)|MERGE\s+INTO|CREATE\s+(OR\s+REPLACE\s+)?TABLE|\.write\b|\.save\(|overwrite|DELETE\s+FROM|UPDATE\s+", re.I)
_READ_CUE = re.compile(r"spark\.table|spark\.read|\bFROM\b|\bJOIN\b|read_files|\.load\(|USING\b", re.I)
_ASSIGN_CUE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*=\s*[fbr]?[\"']$")

MAX_CODE_IN_BRIEF = 20000


_ASSIGN_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[fF]?([\"'])(.*?)\2\s*(#.*)?$")
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
# f"{catalog}.bronze.comm_table_log" where the catalog comes from a widget or
# a config the code never spells out.
_CATALOG_PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}\.`?([A-Za-z0-9_-]+)`?\.`?([A-Za-z0-9_-]+)`?(?![\w-])")


def _by_schema_table(known_tables: Dict[str, str]) -> Dict[str, Optional[str]]:
    """schema.table → full name, when exactly one catalog has it (None when ambiguous)."""
    out: Dict[str, Optional[str]] = {}
    for full in known_tables:
        parts = full.split(".")
        if len(parts) == 3:
            key = f"{parts[1]}.{parts[2]}"
            out[key] = None if key in out else full
    return out


def _resolve_string_variables(code: str) -> Dict[str, str]:
    """NAME = "…" and NAME = f"…{OTHER}…" assignments, with f-string parts filled in.

    Pipelines build table names from pieces (CATALOG, SCHEMA, table) far more
    often than they write them out, so literal matching alone misses them.
    """
    raw: Dict[str, str] = {}
    for line in code.splitlines():
        m = _ASSIGN_LINE.match(line)
        if m and len(m.group(3)) < 300:
            raw[m.group(1)] = m.group(3)
    resolved = dict(raw)
    for _ in range(4):  # nested f-strings a few levels deep
        changed = False
        for name, value in resolved.items():
            new = _PLACEHOLDER.sub(lambda p: resolved.get(p.group(1), p.group(0)), value)
            if new != value:
                resolved[name], changed = new, True
        if not changed:
            break
    return resolved


def _line_at(code: str, pos: int) -> str:
    start = code.rfind("\n", 0, pos) + 1
    end = code.find("\n", pos)
    return code[start: end if end != -1 else len(code)]


def _mode_at(code: str, pos: int) -> str:
    """read / write / named, from the code just before a reference."""
    before = code[max(0, pos - 160): pos]
    if _ASSIGN_CUE.search(before.rstrip()[-80:]):
        return "named"
    if _WRITE_CUE.search(before[-120:]):
        return "write"
    if _READ_CUE.search(before[-120:]):
        return "read"
    return "named"


def scan_code(code: str, known_tables: Dict[str, str]) -> Dict[str, Any]:
    """Tables and volume paths named in code, each with how the code uses it.

    known_tables: lower-case full name → table entity_id.
    """
    tables: Dict[str, Dict[str, Any]] = {}
    by_schema_table = _by_schema_table(known_tables)

    def resolve(name: str) -> Optional[str]:
        """A known full name, or {catalog}.schema.table matched on its unique schema.table."""
        name = name.strip("`").replace("`", "").lower()
        if name in known_tables:
            return name
        m = _CATALOG_PLACEHOLDER.fullmatch(name)
        return by_schema_table.get(f"{m.group(1)}.{m.group(2)}") if m else None

    def add(full: str, mode: str, pos: int, via: Optional[str] = None) -> None:
        entry = tables.setdefault(full, {"table": full, "entity_id": known_tables[full], "modes": set(), "lines": []})
        entry["modes"].add(mode)
        if via:
            entry.setdefault("via_variables", set()).add(via)
        line_no = code.count("\n", 0, pos) + 1
        if len(entry["lines"]) < 6 and line_no not in entry["lines"]:
            entry["lines"].append(line_no)

    # Names held in variables: classify every place the variable is used.
    for var, value in _resolve_string_variables(code).items():
        full = resolve(value)
        if not full:
            continue
        uses = [u for u in re.finditer(rf"(\{{{var}\}}|\b{var}\b)", code)
                if not _ASSIGN_LINE.match(_line_at(code, u.start()))]
        for u in uses:
            add(full, _mode_at(code, u.start()), u.start(), via=var)
        if not uses:
            add(full, "named", code.find(var), via=var)

    for m in _THREE_PART.finditer(code):
        full = ".".join(m.groups()).lower()
        if full not in known_tables:
            continue
        # A literal assigned to a variable was already classified by its uses.
        if _mode_at(code, m.start()) == "named" and "via_variables" in tables.get(full, {}):
            continue
        add(full, _mode_at(code, m.start()), m.start())
    for m in _CATALOG_PLACEHOLDER.finditer(code):
        full = resolve(m.group(0))
        # Skip a template that is only a variable's value — its uses were classified above.
        if not full or _ASSIGN_LINE.match(_line_at(code, m.start())):
            continue
        add(full, _mode_at(code, m.start()), m.start())
    volumes = sorted({v.rstrip("/.") for v in _VOLUME.findall(code)})[:30]
    out = []
    for e in tables.values():
        # "named" only matters when the code never shows how the table is used.
        if len(e["modes"]) > 1:
            e["modes"].discard("named")
        e["modes"] = sorted(e["modes"])
        if "via_variables" in e:
            e["via_variables"] = sorted(e["via_variables"])
        out.append(e)
    return {"tables_in_code": sorted(out, key=lambda e: e["table"]), "volume_paths_in_code": volumes}


async def task_code_facts(context_doc: Dict[str, Any], workspace_id) -> Dict[str, Any]:
    """Read a task's notebook or SQL once, and scan it."""
    attrs = context_doc.get("attributes") or {}
    code, source = attrs.get("sql_query"), "sql_query"
    if not code and attrs.get("notebook_path"):
        try:
            connector = await _platform_connector(context_doc["entity_id"].split(":")[1])
            code = await connector.read_workspace_file(attrs["notebook_path"])
            source = attrs["notebook_path"]
        except Exception as exc:  # noqa: BLE001
            return {"code_available": False, "code_error": str(exc)[:160]}
    if not code:
        return {"code_available": False}
    from kairos_kb.models.table import Table

    async with async_session_factory() as db:
        known = {fn.lower(): eid for fn, eid in (await db.execute(
            select(Table.full_name, Table.entity_id).where(Table.workspace_id == workspace_id)
        )).all()}
    scan = scan_code(code, known)
    # "_code" is handed to the agent in its brief, never written into the profile.
    return {"code_available": True, "code_source": source, "code_chars": len(code), **scan, "_code": code}


# ── Stage 4: propagate column meaning along 1:1 column lineage ───────


async def propagate_column_docs(fields: Dict[str, Any], context_doc: Dict[str, Any]) -> int:
    """Fill undocumented columns from a documented upstream column.

    Only a pass-through qualifies: exactly one upstream column with the same
    name. A derived column (l_infinity_distance from count) does not inherit a
    meaning it may not have.
    """
    from kairos_kb.models.entity_profile import EntityProfile

    shape = fields.get("shape")
    if not isinstance(shape, dict) or not isinstance(shape.get("columns"), list):
        return 0
    undocumented = {str(c.get("name", "")).lower(): c for c in shape["columns"] if c.get("undocumented")}
    if not undocumented:
        return 0
    _, ws, fqn = context_doc["entity_id"].split(":", 2)
    targets = [f"column:{ws}:{fqn}.{c['name']}" for c in undocumented.values()]
    filled = 0
    async with async_session_factory() as db:
        edges = (await db.execute(select(LineageEdge).where(
            LineageEdge.source_type != "TABLE", LineageEdge.target_entity_id.in_(targets)
        ))).scalars().all()
        upstream_by_target: Dict[str, List[str]] = {}
        for e in edges:
            if e.source_entity_id != e.target_entity_id:
                upstream_by_target.setdefault(e.target_entity_id, []).append(e.source_entity_id)
        profile_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        for target, sources in upstream_by_target.items():
            if len(set(sources)) != 1:
                continue
            src = sources[0]
            src_table, _, src_col = src.rpartition(".")
            tgt_col = target.rpartition(".")[2]
            if src_col.lower() != tgt_col.lower():
                continue
            table_id = "table:" + src_table.split(":", 1)[1]
            if table_id not in profile_cache:
                row = (await db.execute(select(EntityProfile).where(EntityProfile.entity_id == table_id))).scalars().first()
                profile_cache[table_id] = await load_upstream_profile(db, table_id) if row else None
            doc = profile_cache[table_id]
            upstream_cols = ((doc or {}).get("shape") or {}).get("columns") or []
            match = next((c for c in upstream_cols if isinstance(c, dict)
                          and str(c.get("name", "")).lower() == src_col.lower()
                          and c.get("meaning") and not c.get("undocumented")), None)
            if match:
                col = undocumented[tgt_col.lower()]
                col.update({"meaning": match["meaning"], "tags": match.get("tags"),
                            "propagated_from": f"{src_table.split(':', 2)[-1]}.{src_col}"})
                col.pop("undocumented", None)
                filled += 1
    return filled


async def load_upstream_profile(db, table_id: str) -> Optional[Dict[str, Any]]:
    """An upstream table's profile document, or None."""
    import yaml

    from kairos_kb.enrichment.profile_writer import load_profile_yaml

    try:
        text = await load_profile_yaml(db, table_id)  # the YAML document as text
        doc = yaml.safe_load(text) if text else None
    except Exception:  # noqa: BLE001
        return None
    return doc if isinstance(doc, dict) else None


# ── Stage 2b: describe the columns the agent left out, in batches ────

COLUMN_BATCH = 40


async def describe_missing_columns(fields: Dict[str, Any], context_doc: Dict[str, Any], telemetry=None) -> int:
    """One LLM call per batch of undocumented columns, with a few sample values."""
    from pydantic import BaseModel, Field

    from kairos_kb.enrichment.agent import _build_llm

    shape = fields.get("shape")
    if not isinstance(shape, dict) or not isinstance(shape.get("columns"), list):
        return 0
    missing = [c for c in shape["columns"] if c.get("undocumented")]
    if not missing:
        return 0
    llm = _build_llm()
    if llm is None:
        return 0

    samples: Dict[str, List[str]] = {}
    try:  # a handful of values per column; read-only
        from kairos_kb.connectors.factory import quote_table, sql_dialect
        from kairos_kb.context.files import redact_values
        from kairos_kb.context.privacy import is_masked, tagged_personal

        # Personal columns (tagged by the profile, or named so) give the model no values at all.
        tagged = tagged_personal(shape["columns"])
        connector = await _platform_connector(context_doc["entity_id"].split(":")[1])
        name = (quote_table(connector, context_doc["full_name"]) if sql_dialect(connector) == "snowflake"
                else _q(context_doc["full_name"]))
        result = await connector.execute_query(f"SELECT * FROM {name} LIMIT 5")
        for row in DatabricksConnector._rows_from_statement_result(result):
            for k, v in row.items():
                if v in (None, "") or is_masked(str(k), tagged):
                    continue
                if len(samples.setdefault(k, [])) < 3:
                    samples[k].append(redact_values(str(v))[:40])
    except Exception:  # noqa: BLE001 — descriptions can still come from names alone
        pass

    class ColumnDoc(BaseModel):
        name: str
        meaning: str = Field(description="What the column holds, in one short phrase. Say 'unclear' if it is.")
        tags: List[str] = Field(default_factory=list, description="e.g. identifier, date, measure, personal_data")

    class ColumnDocs(BaseModel):
        columns: List[ColumnDoc]

    comments = {c.get("name"): c.get("comment") for c in context_doc.get("columns") or []}
    structured = llm.with_structured_output(ColumnDocs, include_raw=True)
    filled = 0
    for i in range(0, len(missing), COLUMN_BATCH):
        batch = missing[i:i + COLUMN_BATCH]
        listing = "\n".join(
            f"- {c['name']} ({c.get('type')})"
            + (f" comment: {comments.get(c['name'])}" if comments.get(c["name"]) else "")
            + (f" samples: {samples.get(c['name'])}" if samples.get(c["name"]) else "")
            for c in batch
        )
        if telemetry:
            await telemetry(activity=f"Stage 2b · describing columns {i + 1}–{i + len(batch)} of {len(missing)}")
        try:
            out = await structured.ainvoke([
                ("system", "You document table columns. Use the table's summary and grain for context. Be specific "
                           "and brief. Do not invent business meaning the names and samples do not support."),
                ("human", f"Table: {context_doc.get('full_name')}\nSummary: {fields.get('summary')}\n"
                          f"Grain: {shape.get('grain')}\n\nDescribe each column:\n{listing}"),
            ])
        except Exception:  # noqa: BLE001
            logger.exception("Column batch failed for %s", context_doc.get("full_name"))
            continue
        await _usage(telemetry, out.get("raw"))
        parsed = out.get("parsed")
        docs = {d.name.lower(): d for d in (parsed.columns if parsed else [])}
        for c in batch:
            d = docs.get(str(c["name"]).lower())
            if d and d.meaning and d.meaning.strip().lower() != "unclear":
                c.update({"meaning": d.meaning, "tags": d.tags or None, "described_by": "column_pass"})
                c.pop("undocumented", None)
                filled += 1
            elif d:
                # Tried: neither the name nor the sample values say what it is.
                c["meaning_unclear"] = True
    return filled


async def _usage(telemetry, raw) -> None:
    if not telemetry:
        return
    usage = getattr(raw, "usage_metadata", None) or {}
    await telemetry(input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0), llm_calls=1)


def refresh_column_coverage(fields: Dict[str, Any], verification: Dict[str, Any], propagated: int, described: int) -> None:
    """Recompute the coverage check after propagation and the column pass."""
    shape = fields.get("shape")
    cols = shape.get("columns") if isinstance(shape, dict) else None
    if not isinstance(cols, list):
        return
    remaining = sum(1 for c in cols if c.get("undocumented"))
    for check in verification.get("checks", []):
        if check["check"] == "column_coverage":
            check["result"] = "ok" if not remaining else "incomplete"
            parts = [f"{len(cols) - remaining} of {len(cols)} columns described"]
            if propagated:
                parts.append(f"{propagated} propagated from upstream columns")
            if described:
                parts.append(f"{described} by the column pass")
            if remaining:
                unclear = sum(1 for c in cols if c.get("undocumented") and c.get("meaning_unclear"))
                parts.append(f"{remaining} still undocumented"
                             + (f" ({unclear} unclear from their names and sample values)" if unclear else ""))
            check["detail"] = "; ".join(parts)
    verification["passed"] = not any(c["result"] in ("fails", "incomplete") for c in verification.get("checks", []))


# ── Reconcile: the profile's words must agree with what was verified ──


async def reconcile_with_verification(fields: Dict[str, Any], verification: Dict[str, Any], telemetry=None) -> bool:
    """Rewrite open questions and the grain statement in light of the checks.

    The agent writes before verification runs, so it asks things Kairos has
    since answered ("please confirm the distinct count"). One small call fixes
    that. Skipped when no check produced a definite answer.
    """
    from pydantic import BaseModel, Field

    from kairos_kb.enrichment.agent import _build_llm

    definite = [c for c in verification.get("checks", []) if c["result"] in ("holds", "fails", "corrected")]
    if not definite:
        return False
    llm = _build_llm()
    if llm is None:
        return False

    class Reconciled(BaseModel):
        grain: str = Field(description="The grain statement, corrected to agree with the checks.")
        open_questions: List[str] = Field(description="The open questions, minus any the checks answered, "
                                          "plus any new question a failed check raises.")

    shape = fields.get("shape") if isinstance(fields.get("shape"), dict) else {}
    try:
        out = await llm.with_structured_output(Reconciled, include_raw=True).ainvoke([
            ("system", "A data profile was written before automated checks ran. Make its grain statement and open "
                       "questions agree with the checks. Keep everything else the same wording where possible."),
            ("human", json.dumps({"grain": shape.get("grain"), "grain_key": fields.get("grain_key"),
                                  "open_questions": fields.get("open_questions") or [],
                                  "checks": definite}, default=str)),
        ])
    except Exception:  # noqa: BLE001
        logger.exception("Reconcile failed")
        return False
    await _usage(telemetry, out.get("raw"))
    parsed = out.get("parsed")
    if not parsed:
        return False
    if isinstance(fields.get("shape"), dict):
        fields["shape"]["grain"] = parsed.grain
    fields["open_questions"] = parsed.open_questions or None
    return True


# ── Classification fallback: two close roles blend their templates ───


def effective_template(classification: Optional[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """The role label and template to use, blending the top two when neither is confident."""
    if not classification:
        return "OTHER", ROLE_TEMPLATES["OTHER"]
    role = classification.get("role", "OTHER")
    if role != "OTHER":
        return role, ROLE_TEMPLATES.get(role, ROLE_TEMPLATES["OTHER"])
    top = classification.get("role_top") or []
    if len(top) >= 2 and top[0][0] != "OTHER" and top[1][0] != "OTHER" and top[0][1] + top[1][1] >= 0.75:
        a, b = ROLE_TEMPLATES[top[0][0]], ROLE_TEMPLATES[top[1][0]]
        levels = ["required", "optional", "skip"]
        grain = min(a["grain_key"], b["grain_key"], key=levels.index)
        blended = {"grain_key": grain, "light": a["light"] and b["light"],
                   "must": [f"(it is {top[0][0]} or {top[1][0]} — decide which from the evidence)"]
                   + list(dict.fromkeys(a["must"] + b["must"]))}
        return f"{top[0][0]} or {top[1][0]}", blended
    return "OTHER", ROLE_TEMPLATES["OTHER"]
