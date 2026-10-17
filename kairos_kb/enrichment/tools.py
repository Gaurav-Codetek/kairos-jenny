"""Tools the enrichment agent calls while profiling one entity.

Built per entity by :func:`build_tools`, which closes over the run context
so the agent never has to pass bookkeeping identifiers around.

Every tool commits in its own session. Discovered relations are durable the
moment they are asserted, so a run that dies mid-entity keeps what it learned.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from langchain_core.tools import tool
from sqlalchemy import or_, select

from kairos_kb.connectors.databricks import DatabricksConnector
from kairos_kb.connectors.factory import connector_for_workspace_name
from kairos_kb.context.privacy import mask_rows
from kairos_kb.context.query import check_read_only
from kairos_kb.db.engine import async_session_factory
from kairos_kb.ingestion.change_detector import compute_content_hash
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.discovered import DiscoveredEntity, DiscoveredRelation
from kairos_kb.models.evidence import Evidence
from kairos_kb.models.job import Job
from kairos_kb.models.schema import Schema
from kairos_kb.models.table import Table
from kairos_kb.models.task import Task

logger = logging.getLogger(__name__)

# Kind tokens the agent may use as a prefix, whether addressing a real
# entity_id or just labelling a bare reference.
KIND_TOKENS = {
    "workspace", "catalog", "schema", "table", "column", "job", "task", "run",
    "taskrun", "volume", "file", "notebook", "genie_space", "external_connection",
    "dashboard", "pipeline", "cluster", "unknown",
}

# A leading "<token>:" that is not a URL scheme (those are followed by "//").
_LEADING_TOKEN = re.compile(r"^([a-z][a-z0-9_]*):(?!//)")


def _strip_kind_token(reference: str) -> tuple[str, Optional[str]]:
    """Peel a leading kind token off a reference.

    Returns (remaining_reference, kind_or_None). An inline token is a stronger
    signal than the separate target_kind argument — the model writes
    "cluster:0527-..." deliberately, and honouring it keeps the same real
    object from being minted under two different kinds.
    """
    match = _LEADING_TOKEN.match(reference)
    if not match:
        return reference, None
    token = match.group(1)
    if token not in KIND_TOKENS:
        return reference, None
    return reference[len(token) + 1 :].strip(), token


@dataclass
class ToolContext:
    """Everything the tools need about the entity currently being profiled."""

    workspace_id: uuid.UUID
    workspace_name: str
    run_id: uuid.UUID
    entity_id: str
    kind: str
    emit: Callable[..., Awaitable[None]]
    # Live telemetry: tokens, call counts, and the current activity line.
    # Optional so tools and tests can build a context without it.
    telemetry: Optional[Callable[..., Awaitable[None]]] = None
    # Path -> evidence id, so a link can cite the file it was read from.
    read_evidence: Dict[str, uuid.UUID] = field(default_factory=dict)
    profile_fields: Dict[str, Any] = field(default_factory=dict)
    links_made: int = 0
    entities_minted: int = 0
    # Links declined by the vocabulary (containment, guesses, non-flow verbs).
    links_rejected: int = 0


def _normalize_reference(reference: str, kind: str) -> str:
    """Canonicalise a reference so one real object yields one node.

    Two tasks reading the same volume file routinely write it differently —
    ``dbfs:/Volumes/...`` versus ``/Volumes/...``, a trailing slash, wrapping
    quotes or backticks. Without this each spelling mints its own entity and
    the graph shows the same file several times instead of one node with
    several arrows into it.
    """
    ref = reference.strip()

    # Models frequently wrap paths and identifiers in quotes or backticks.
    ref = ref.strip("`'\"").strip()

    # dbfs: is a mount prefix over the same underlying path.
    lowered = ref.lower()
    for prefix in ("dbfs:///", "dbfs://", "dbfs:/"):
        if lowered.startswith(prefix):
            ref = "/" + ref[len(prefix) :].lstrip("/")
            break

    # Collapse repeated slashes in the path portion, leaving any scheme alone.
    if "://" in ref:
        scheme, _, rest = ref.partition("://")
        ref = f"{scheme}://" + re.sub(r"/{2,}", "/", rest)
    else:
        ref = re.sub(r"/{2,}", "/", ref)

    # A directory with and without a trailing slash is the same directory.
    if len(ref) > 1:
        ref = ref.rstrip("/")

    # Unity Catalog identifiers are case-insensitive; paths are not.
    if kind in {"table", "schema", "catalog", "column"}:
        ref = ref.lower()

    return ref


def _infer_kind(reference: str) -> str:
    """Guess the kind of a raw reference found in code or config."""
    ref = reference.strip()
    if ref.startswith("/Volumes/"):
        # A path with a file extension is a file; otherwise treat as a volume.
        tail = ref.rstrip("/").rsplit("/", 1)[-1]
        return "file" if "." in tail else "volume"
    if ref.startswith("/Workspace/") or ref.startswith("/Repos/"):
        return "notebook"
    if ref.startswith(("abfss://", "s3://", "gs://", "dbfs:/", "wasbs://")):
        return "file"
    if ref.count(".") == 2 and " " not in ref:
        return "table"
    return "unknown"


def build_tools(ctx: ToolContext) -> List[Any]:
    """Create the toolset bound to one entity's profiling pass."""

    async def _record_evidence(
        db, *, entity_id: str, source_type: str, content: str, source_id: str | None
    ) -> uuid.UUID:
        evidence = Evidence(
            workspace_id=ctx.workspace_id,
            entity_id=entity_id,
            source_type=source_type,
            source_id=source_id,
            content=content[:200_000],
            content_hash=compute_content_hash(content),
            observed_at=datetime.now(timezone.utc),
            metadata_extra={"run_id": str(ctx.run_id), "profiling": ctx.entity_id},
        )
        db.add(evidence)
        await db.flush()
        return evidence.id

    async def _resolve_or_mint(db, reference: str, kind_hint: str | None, rationale: str) -> str:
        """Turn a raw reference into an addressable entity_id.

        Anything the warehouse already knows resolves to its real entity_id;
        anything else is minted as a discovered entity so the edge is not lost.
        """
        ref = reference.strip()

        # A well-formed id is "<kind>:<workspace>:<name>" — pass it through.
        stripped, token = _strip_kind_token(ref)
        if token and stripped.startswith(f"{ctx.workspace_name}:"):
            return ref

        # Otherwise peel every kind token the model stacked on the front, so
        # "cluster:0527-..." and a bare "0527-..." normalise to the same
        # reference and cannot become two nodes for one real object.
        while token:
            kind_hint = token
            ref = stripped
            stripped, token = _strip_kind_token(ref)

        kind = kind_hint or _infer_kind(ref)
        # Canonicalise before any lookup, so every spelling of the same object
        # resolves to the same node instead of minting a near-duplicate.
        ref = _normalize_reference(ref, kind)

        # Jobs and tasks are usually referenced by their Databricks native id.
        if kind == "job" and ref.isdigit():
            found = (
                await db.execute(select(Job).where(Job.source_native_id == ref))
            ).scalars().first()
            if found:
                return found.entity_id

        # Try to match something already synced.
        if kind == "table":
            found = (
                await db.execute(select(Table).where(Table.full_name == ref))
            ).scalars().first()
            if found:
                return found.entity_id
            found = (
                await db.execute(select(Table).where(Table.full_name.ilike(f"%{ref}%")).limit(2))
            ).scalars().all()
            if len(found) == 1:
                return found[0].entity_id
        elif kind == "schema":
            found = (
                await db.execute(select(Schema).where(Schema.full_name == ref))
            ).scalars().first()
            if found:
                return found.entity_id
        elif kind == "catalog":
            found = (
                await db.execute(select(Catalog).where(Catalog.name == ref))
            ).scalars().first()
            if found:
                return found.entity_id

        # Nothing synced matches — mint it so the relationship still lands.
        entity_id = f"{kind}:{ctx.workspace_name}:{ref}"
        existing = (
            await db.execute(
                select(DiscoveredEntity).where(DiscoveredEntity.entity_id == entity_id)
            )
        ).scalars().first()

        # The same real thing is often referenced with different kind hints on
        # different calls (a cluster id guessed as "external_connection" once
        # and "cluster" the next time). Match on the reference itself so it
        # stays one node instead of splitting into near-duplicates.
        if existing is None:
            existing = (
                await db.execute(
                    select(DiscoveredEntity).where(
                        DiscoveredEntity.workspace_id == ctx.workspace_id,
                        DiscoveredEntity.full_name == ref,
                    )
                )
            ).scalars().first()
            if existing is not None:
                entity_id = existing.entity_id

        now = datetime.now(timezone.utc)

        if existing:
            existing.last_seen_at = now
        else:
            db.add(
                DiscoveredEntity(
                    workspace_id=ctx.workspace_id,
                    entity_id=entity_id,
                    kind=kind,
                    name=ref.rstrip("/").rsplit("/", 1)[-1].split(".")[-1] or ref,
                    full_name=ref,
                    origin="agent_discovered",
                    rationale=rationale,
                    run_id=ctx.run_id,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            ctx.entities_minted += 1
            await ctx.emit(
                "entity_discovered",
                f"Discovered new {kind}: {ref}",
                payload={"entity_id": entity_id, "kind": kind},
            )

        return entity_id

    # ── Reading ──────────────────────────────────────────────────────

    @tool
    async def read_databricks_file(path: str, offset: int = 0, length: int = 60000) -> str:
        """Read a notebook, SQL script, or any text file from Databricks Workspace or Volumes.

        Use this on a task's notebook_path to see what the task actually does.
        Paginate with offset/length for large files.

        Args:
            path: Absolute Databricks path, e.g. /Workspace/... or /Volumes/...
            offset: Character offset to start from.
            length: Maximum characters to return.
        """
        # This run's connection: Databricks reads workspace and Volume files, Snowflake
        # reads code (procedures, tasks, views) with GET_DDL for snowflake:// paths.
        try:
            connector = await connector_for_workspace_name(ctx.workspace_name)
            content = await connector.read_workspace_file(path)
        except Exception as exc:
            await ctx.emit("tool_call", f"Failed to read {path}: {exc}", level="warning")
            return f"ERROR reading {path}: {exc}"

        async with async_session_factory() as db:
            evidence_id = await _record_evidence(
                db,
                entity_id=ctx.entity_id,
                source_type="FILE_CONTENT",
                content=content,
                source_id=path,
            )
            await db.commit()
        ctx.read_evidence[path] = evidence_id

        await ctx.emit("tool_call", f"Read {path} ({len(content)} chars)", payload={"path": path})
        chunk = content[offset : offset + length]
        return f"--- {path} [chars {offset}-{min(offset + length, len(content))} of {len(content)}] ---\n{chunk}"

    @tool
    async def list_databricks_directory(path: str) -> str:
        """List the contents of a Databricks Volume or Workspace directory.

        Useful for discovering what files a volume actually holds.

        Args:
            path: Absolute directory path, e.g. /Volumes/catalog/schema/volume
        """
        try:
            connector = await connector_for_workspace_name(ctx.workspace_name)
            data = await connector._request(  # noqa: SLF001 - no public wrapper yet
                "GET", "/api/2.0/fs/directories" + (path if path.startswith("/") else f"/{path}")
            )
        except Exception as exc:
            return f"ERROR listing {path}: {exc}"

        entries = data.get("contents", []) or []
        await ctx.emit("tool_call", f"Listed {path} ({len(entries)} entries)")
        return json.dumps(
            [
                {"path": e.get("path"), "is_directory": e.get("is_directory"), "size": e.get("file_size")}
                for e in entries[:200]
            ],
            indent=2,
        )

    @tool
    async def query_data_file(path: str, file_format: str = "parquet", sql_query: str = "") -> str:
        """Query a data file in a Volume with Databricks SQL to infer its shape and sample values.

        Args:
            path: Absolute path, e.g. /Volumes/cat/schema/vol/data.parquet
            file_format: parquet, csv, or json.
            sql_query: Optional full SQL. Defaults to SELECT * LIMIT 10.
        """
        statement = sql_query or f"SELECT * FROM {file_format}.`{path}` LIMIT 10"
        refused = check_read_only(statement)
        if refused:
            return f"ERROR: {refused}"
        try:
            connector = await connector_for_workspace_name(ctx.workspace_name)
            result = await connector.execute_query(statement)
            # Sample values go into the model's context: personal columns masked first.
            rows = mask_rows(connector._rows_from_statement_result(result))  # noqa: SLF001
        except Exception as exc:
            return f"ERROR querying {path}: {exc}"

        await ctx.emit("tool_call", f"Queried {path} ({len(rows)} rows)")
        return json.dumps(rows[:20], indent=2, default=str) if rows else "Query returned no rows."

    @tool
    async def find_entity(keyword: str, kinds: str = "") -> str:
        """Search the Synthetic Warehouse for entities whose name matches a keyword.

        Use this to turn a table or job name you saw in code into a real entity_id
        before linking to it.

        Args:
            keyword: Substring to match.
            kinds: Optional comma-separated filter, e.g. "table,job".
        """
        wanted = {k.strip() for k in kinds.split(",") if k.strip()} or {
            "table",
            "schema",
            "catalog",
            "job",
            "task",
        }
        pattern = f"%{keyword}%"
        results: List[Dict[str, str]] = []

        async with async_session_factory() as db:
            if "table" in wanted:
                for row in (
                    await db.execute(select(Table).where(Table.full_name.ilike(pattern)).limit(15))
                ).scalars().all():
                    results.append({"entity_id": row.entity_id, "kind": "table", "name": row.full_name})
            if "schema" in wanted:
                for row in (
                    await db.execute(select(Schema).where(Schema.full_name.ilike(pattern)).limit(10))
                ).scalars().all():
                    results.append({"entity_id": row.entity_id, "kind": "schema", "name": row.full_name})
            if "catalog" in wanted:
                for row in (
                    await db.execute(select(Catalog).where(Catalog.name.ilike(pattern)).limit(10))
                ).scalars().all():
                    results.append({"entity_id": row.entity_id, "kind": "catalog", "name": row.name})
            if "job" in wanted:
                for row in (
                    await db.execute(select(Job).where(Job.name.ilike(pattern)).limit(10))
                ).scalars().all():
                    results.append({"entity_id": row.entity_id, "kind": "job", "name": row.name})
            if "task" in wanted:
                for row in (
                    await db.execute(select(Task).where(Task.task_key.ilike(pattern)).limit(10))
                ).scalars().all():
                    results.append({"entity_id": row.entity_id, "kind": "task", "name": row.task_key})

        if not results:
            return f"No entities match '{keyword}'. If it exists outside the warehouse, link to it anyway — it will be registered as a discovered entity."
        return json.dumps(results, indent=2)

    # ── Connecting the dots ──────────────────────────────────────────

    @tool
    async def link_entities(
        target: str,
        relation_type: str,
        rationale: str,
        confidence: float = 0.8,
        source_ref: str = "",
        target_kind: str = "",
        direction: str = "outgoing",
    ) -> str:
        """Record a relationship between the entity being profiled and another entity.

        This is how the entity map grows. relation_type must be one of:
        READS_TABLE, WRITES_TABLE, READS_FILE, WRITES_FILE, FEEDS, DEPENDS_ON,
        TRIGGERS, RUNS_NOTEBOOK, USES_EXTERNAL, STORED_AT. Containment
        (table in schema, task in job) is already known and is never recorded;
        neither are name-based guesses.

        Only call this when you have seen concrete supporting material such as a
        line of code, a config value, or an API response. Put that in rationale.

        Args:
            target: entity_id, or a raw name/path seen in code (a table full name,
                a /Volumes/... path, a Genie space name). Unknown targets are
                registered automatically.
            relation_type: One verb from the list above.
            rationale: Why you believe this link exists. Required.
            confidence: 0.0-1.0.
            source_ref: Where you saw it, e.g. the file path or config key.
            target_kind: Optional hint: table, volume, file, genie_space,
                external_connection, notebook, dashboard, job, task.
            direction: "outgoing" if this entity acts on the target,
                "incoming" if the target acts on this entity.
        """
        if not rationale or not rationale.strip():
            return "REJECTED: rationale is required. State the concrete material that supports this link."

        from kairos_kb.enrichment.pipeline import canonical_relation

        # A person, or an interactive notebook session from Delta history, is a
        # fact about a table — not an entity. Linking one minted "notebooks"
        # named after e-mail addresses.
        from kairos_kb.enrichment.pipeline import is_person_reference

        if is_person_reference(target):
            ctx.links_rejected += 1
            return ("NOT RECORDED: people and interactive notebook sessions are facts, not entities — "
                    "mention them in creation/operational_notes instead.")

        canonical, flip, reason = canonical_relation(relation_type)
        if canonical is None:
            ctx.links_rejected += 1
            return f"NOT RECORDED: {reason}."
        # A managed table's own storage path (…/tables/<uuid>) is Unity
        # Catalog's internal detail, not a relationship worth a graph edge.
        if canonical == "STORED_AT" and re.search(r"/tables/[0-9a-f-]{36}/?$", target.strip(), re.I):
            ctx.links_rejected += 1
            return "NOT RECORDED: a managed table's own storage location is an internal detail, not a relationship."
        if flip:  # a passive verb ("READ_BY"): store it the active way round
            direction = "outgoing" if direction == "incoming" else "incoming"
        relation_type = canonical

        async with async_session_factory() as db:
            target_id = await _resolve_or_mint(db, target, target_kind or None, rationale)

            if target_id == ctx.entity_id:
                return "REJECTED: an entity cannot be linked to itself."

            source_id, dest_id = (
                (ctx.entity_id, target_id) if direction != "incoming" else (target_id, ctx.entity_id)
            )

            from kairos_kb.enrichment.pipeline import check_link_kinds

            kind_problem = check_link_kinds(relation_type, source_id.split(":", 1)[0], dest_id.split(":", 1)[0])
            if kind_problem:
                ctx.links_rejected += 1
                return f"NOT RECORDED: {kind_problem}. Check the direction and the verb."

            existing = (
                await db.execute(
                    select(DiscoveredRelation).where(
                        DiscoveredRelation.source_entity_id == source_id,
                        DiscoveredRelation.target_entity_id == dest_id,
                        DiscoveredRelation.relation_type == relation_type,
                    )
                )
            ).scalars().first()

            if existing:
                existing.observed_at = datetime.now(timezone.utc)
                existing.confidence = max(existing.confidence, float(confidence))
                await db.commit()
                return f"Already recorded: {source_id} -{relation_type}-> {dest_id}"

            db.add(
                DiscoveredRelation(
                    workspace_id=ctx.workspace_id,
                    source_entity_id=source_id,
                    target_entity_id=dest_id,
                    relation_type=relation_type.strip().upper().replace(" ", "_"),
                    confidence=max(0.0, min(1.0, float(confidence))),
                    rationale=rationale.strip(),
                    source_ref=source_ref or None,
                    evidence_id=ctx.read_evidence.get(source_ref),
                    run_id=ctx.run_id,
                    status="proposed",
                    observed_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        ctx.links_made += 1
        await ctx.emit(
            "relation_found",
            f"{source_id.split(':')[-1]} —{relation_type}→ {dest_id.split(':')[-1]}",
            payload={
                "source": source_id,
                "target": dest_id,
                "relation_type": relation_type,
                "confidence": confidence,
            },
        )
        return f"Linked: {source_id} -{relation_type}-> {dest_id}"

    @tool
    async def register_entity(kind: str, reference: str, rationale: str) -> str:
        """Register an entity that exists in Databricks but not in the warehouse.

        Use for things the connector never synced — volumes, files, Genie spaces,
        external connections, dashboards. Usually you do not need to call this
        directly, since link_entities registers unknown targets automatically.

        Args:
            kind: volume, file, genie_space, external_connection, notebook, dashboard.
            reference: Its name or path.
            rationale: Where you saw it.
        """
        async with async_session_factory() as db:
            entity_id = await _resolve_or_mint(db, reference, kind, rationale)
            await db.commit()
        return f"Registered: {entity_id}"

    # ── Output ───────────────────────────────────────────────────────

    @tool
    async def save_profile(
        summary: str,
        purpose: str = "",
        data_product: str = "",
        semantic_tags: str = "",
        shape_yaml: str = "",
        creation_yaml: str = "",
        operational_notes: str = "",
        open_questions: str = "",
        grain_key: str = "",
        classification_feedback: str = "",
    ) -> str:
        """Save your finished understanding of this entity. Call this exactly once, last.

        Args:
            summary: A few sentences on what this entity is.
            purpose: What it serves — who consumes it and why.
            data_product: The data product or domain it belongs to, if any.
            semantic_tags: Comma-separated tags, e.g. "pii,finance,gold_layer".
            shape_yaml: For tables, a YAML block describing grain and columns
                (name, semantic meaning, tags). For jobs, the task topology.
            creation_yaml: YAML describing how this entity comes into existence —
                which task or notebook writes it, and by what method.
            operational_notes: Scheduling, reliability, recent failure patterns.
            open_questions: Anything you could not determine, one per line.
            grain_key: For tables, the column(s) that uniquely identify one row,
                comma-separated and exactly as named. Kairos verifies it.
            classification_feedback: Only if the given classification is wrong:
                the right role and the evidence, in one sentence.
        """
        tags = [t.strip() for t in semantic_tags.split(",") if t.strip()]

        ctx.profile_fields = {
            "summary": summary.strip(),
            "purpose": purpose.strip() or None,
            "data_product": data_product.strip() or None,
            "semantic_tags": tags or None,
            "shape": _maybe_yaml(shape_yaml),
            "creation": _maybe_yaml(creation_yaml),
            "operational_notes": operational_notes.strip() or None,
            "open_questions": [q.strip() for q in open_questions.splitlines() if q.strip()] or None,
            "grain_key": grain_key.strip() or None,
            "classification_feedback": classification_feedback.strip() or None,
        }
        return "Profile saved. You are done with this entity."

    return [
        read_databricks_file,
        list_databricks_directory,
        query_data_file,
        find_entity,
        link_entities,
        register_entity,
        save_profile,
    ]


def _maybe_yaml(text: str) -> Any:
    """Parse a YAML block the model produced, falling back to raw text.

    Models frequently emit the block as a single-line string with literal
    ``\\n`` escapes. Parsing that yields a useless scalar, so unescape and
    retry before giving up.
    """
    if not text or not text.strip():
        return None

    import yaml

    def _try(candidate: str) -> Any:
        try:
            parsed = yaml.safe_load(candidate)
        except Exception:
            return None
        # A scalar means it did not parse as a structure worth keeping.
        return parsed if isinstance(parsed, (dict, list)) else None

    structured = _try(text)
    if structured is not None:
        return structured

    if "\\n" in text:
        structured = _try(text.replace("\\n", "\n").replace('\\"', '"'))
        if structured is not None:
            return structured

    return text.replace("\\n", "\n").strip()
