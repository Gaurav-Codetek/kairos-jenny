"""Deterministic DB tools for the AI agent."""

import logging
from typing import Any, Dict, List

from langchain_core.tools import tool
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.db.engine import async_session_factory
from kairos_kb.models.change_event import ChangeEvent
from kairos_kb.models.discovered import DiscoveredRelation
from kairos_kb.models.entity_profile import EntityProfile
from kairos_kb.models.job import Job
from kairos_kb.models.task import Task
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.models.run import Run
from kairos_kb.models.task_run import TaskRun
from kairos_kb.models.table import Table
from kairos_kb.agent.scope import rca_connector
from kairos_kb.context.privacy import mask_rows
from kairos_kb.context.query import check_read_only
from kairos_kb.warehouse.entity_graph import EntityGraph
from kairos_kb.warehouse.entity_map import RELATIONS

logger = logging.getLogger(__name__)


@tool
async def get_failed_run_details(run_id: str) -> Dict[str, Any]:
    """Get the details and task breakdown of a failed Databricks job run.
    
    Args:
        run_id: The UUID of the run record in the Synthetic Warehouse.
    """
    async with async_session_factory() as db:
        result = await db.execute(select(Run).where(Run.id == run_id))
        run = result.scalars().first()
        
        if not run:
            return {"error": f"Run with ID {run_id} not found."}
            
        task_result = await db.execute(
            select(TaskRun).where(TaskRun.run_id == run_id).order_by(TaskRun.task_key)
        )
        task_runs = task_result.scalars().all()
        
        failed_tasks = [
            {
                "task_key": tr.task_key,
                # Pass this to get_task_context to reach the task definition
                # and its notebook path.
                "taskrun_entity_id": tr.entity_id,
                "source_native_id": tr.source_native_id,
                "error_message": tr.error_message,
                "state": tr.state,
                "result_state": tr.result_state
            }
            for tr in task_runs if tr.result_state == "FAILED"
        ]

        job = (await db.execute(select(Job).where(Job.id == run.job_id))).scalars().first()

        return {
            "run_id": str(run.id),
            "run_entity_id": run.entity_id,
            "job_id": str(run.job_id),
            "job_entity_id": job.entity_id if job else None,
            "job_name": job.name if job else None,
            "state": run.state,
            "result_state": run.result_state,
            "error_message": run.error_message,
            "failed_tasks": failed_tasks,
            # Tasks that did not fail themselves but were blocked, which tells
            # you where in the chain the failure originated.
            "blocked_tasks": [
                {"task_key": tr.task_key, "result_state": tr.result_state}
                for tr in task_runs
                if tr.result_state in ("UPSTREAM_FAILED", "SKIPPED", "CANCELED")
            ],
            "next_step": (
                "Call get_task_context on a failed task's taskrun_entity_id to get its "
                "notebook_path and dependency position, then read that notebook."
            ),
        }


@tool
async def get_table_lineage(entity_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Get the upstream and downstream lineage for a specific table or column.
    
    Args:
        entity_id: The exact entity_id of the table or column (e.g., 'table:workspace_id.catalog.schema.table').
    """
    async with async_session_factory() as db:
        upstream_result = await db.execute(
            select(LineageEdge).where(LineageEdge.target_entity_id == entity_id)
        )
        upstream = upstream_result.scalars().all()
        
        downstream_result = await db.execute(
            select(LineageEdge).where(LineageEdge.source_entity_id == entity_id)
        )
        downstream = downstream_result.scalars().all()
        
        return {
            "upstream": [
                {"source": e.source_entity_id, "transformation": e.transformation} 
                for e in upstream
            ],
            "downstream": [
                {"target": e.target_entity_id, "transformation": e.transformation} 
                for e in downstream
            ]
        }


@tool
async def get_recent_changes(entity_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get recent changes (schema changes, column additions/deletions) for an entity.
    
    Args:
        entity_id: The exact entity_id of the table, schema, catalog, or job.
        limit: Number of recent changes to return.
    """
    async with async_session_factory() as db:
        result = await db.execute(
            select(ChangeEvent)
            .where(ChangeEvent.entity_id == entity_id)
            .order_by(ChangeEvent.detected_at.desc())
            .limit(limit)
        )
        changes = result.scalars().all()
        
        return [
            {
                "change_type": c.change_type,
                "field_name": c.field_name,
                "old_value": c.old_value,
                "new_value": c.new_value,
                "detected_at": c.detected_at.isoformat()
            }
            for c in changes
        ]


@tool
async def search_tables(keyword: str) -> List[Dict[str, str]]:
    """Search for tables by name or full_name in the Synthetic Warehouse.
    
    Args:
        keyword: The string to search for in table names.
    """
    async with async_session_factory() as db:
        result = await db.execute(
            select(Table)
            .where(Table.full_name.ilike(f"%{keyword}%"))
            .limit(20)
        )
        tables = result.scalars().all()
        
        return [
            {
                "entity_id": t.entity_id,
                "full_name": t.full_name,
                "table_type": t.table_type,
                "comment": t.comment
            }
            for t in tables
        ]

@tool
async def get_task_error_trace(source_native_id: str) -> Dict[str, Any]:
    """Get the full error trace and notebook output for a specific failed task run.
    
    Args:
        source_native_id: The native Databricks run ID of the specific failed task, NOT the top-level job run UUID.
    """
    connector = rca_connector()
    try:
        output = await connector.get_run_output(source_native_id)
        return {
            "error": output.get("error"),
            "error_trace": output.get("error_trace")
        }
    except Exception as exc:
        return {"error": str(exc)}


@tool
async def read_databricks_text_file(file_path: str, offset: int = 0, length: int = 5000) -> str:
    """Read a text/code file from Databricks Workspaces or Volumes (e.g. Python, SQL, JSON).
    Use `offset` and `length` to paginate through large files to avoid overflowing your context.
    
    Args:
        file_path: The absolute path in Databricks starting with /Workspace or /Volumes.
        offset: The character offset to start reading from.
        length: The maximum number of characters to read in this chunk.
    """
    connector = rca_connector()
    try:
        content = await connector.read_workspace_file(file_path)
        chunk = content[offset:offset+length]
        total_len = len(content)
        return f"--- File Preview (Chars {offset} to {min(offset+length, total_len)} of {total_len}) ---\n{chunk}"
    except Exception as exc:
        return f"Error reading file: {str(exc)}"


@tool
async def list_databricks_directory(path: str) -> str:
    """List the contents of a Databricks Volume or Workspace directory.

    Use this when you know a volume or folder is involved but not which file.
    Reading a file requires its exact path, and paths mentioned in error traces
    are often directories. Recurse by calling again on a returned directory.

    Args:
        path: Absolute directory path, e.g. /Volumes/<catalog>/<schema>/<volume>
    """
    connector = rca_connector()
    if not path.startswith("/"):
        path = "/" + path
    try:
        data = await connector._request("GET", "/api/2.0/fs/directories" + path)
    except Exception as exc:
        return f"Error listing {path}: {exc}"

    entries = data.get("contents", []) or []
    if not entries:
        return f"{path} is empty."

    lines = [f"--- {path} ({len(entries)} entries) ---"]
    for item in entries[:200]:
        kind = "DIR " if item.get("is_directory") else "FILE"
        size = item.get("file_size")
        lines.append(f"{kind} {item.get('path')}" + (f"  ({size} bytes)" if size else ""))
    if len(entries) > 200:
        lines.append(f"... {len(entries) - 200} more")
    return "\n".join(lines)


@tool
async def query_databricks_data_file(file_path: str, format: str = "parquet", sql_query: str = "") -> str:
    """Query a structured data file (CSV, Parquet, JSON) in a Databricks Volume using Databricks SQL.
    This allows you to inspect data files directly without downloading them.
    
    Args:
        file_path: The absolute path to the file in the volume (e.g., /Volumes/catalog/schema/vol/file.parquet).
        format: The format of the file (e.g., 'csv', 'parquet', 'json').
        sql_query: The SQL query to execute. Example: "SELECT * FROM parquet.`/Volumes/catalog/schema/vol/file.parquet` LIMIT 10"
                   If empty, a default SELECT * LIMIT 10 query will be constructed.
    """
    if not sql_query:
        sql_query = f"SELECT * FROM {format}.`{file_path}` LIMIT 10"
    refused = check_read_only(sql_query)
    if refused:
        return f"Error: {refused}"
    try:
        connector = rca_connector()
        result = await connector.execute_query(sql_query)
        rows = mask_rows(connector._rows_from_statement_result(result))

        if not rows:
            return "Query returned no rows."

        import json
        return f"--- Query Results ---\n{json.dumps(rows, indent=2, default=str)}"
    except Exception as exc:
        return f"Error querying data file: {str(exc)}"


# Group all tools
# ── Entity map tools ─────────────────────────────────────────────────
# These expose the knowledge graph to RCA. Every one returns a compact,
# bounded slice: handing an LLM a raw traversal would dilute its attention
# and cost tokens without adding signal.


@tool
async def get_task_context(entity_id: str) -> Dict[str, Any]:
    """Resolve a failed task or task run to the task definition behind it.

    This is normally the first call after get_failed_run_details: it gives you
    the notebook_path you need for read_databricks_text_file, plus where the
    task sits in the job's dependency chain.

    Args:
        entity_id: A task or taskrun entity_id, e.g.
            'taskrun:<workspace>:<run_native_id>:<task_key>' or
            'task:<workspace>:<job_native_id>:<task_key>'.
    """
    async with async_session_factory() as db:
        graph = EntityGraph(db)
        node = entity_id
        kind = node.split(":", 1)[0]

        # A task run realises a task definition; follow INSTANCE_OF to it.
        if kind == "taskrun":
            edges, _ = await graph.expand(node, relations={"INSTANCE_OF"}, limit=5)
            for edge in edges:
                other = edge["target"] if edge["source"] == node else edge["source"]
                if other.startswith("task:"):
                    node = other
                    break

        task = (await db.execute(select(Task).where(Task.entity_id == node))).scalars().first()
        if not task:
            return {"error": f"No task definition found for {entity_id}."}

        job = (await db.execute(select(Job).where(Job.id == task.job_id))).scalars().first()
        siblings = (
            await db.execute(select(Task).where(Task.job_id == task.job_id))
        ).scalars().all()

        def keys(raw: Any) -> List[str]:
            if not raw:
                return []
            return [i.get("task_key") for i in raw if isinstance(i, dict) and i.get("task_key")]

        return {
            "task_entity_id": task.entity_id,
            "task_key": task.task_key,
            "task_type": task.task_type,
            "notebook_path": task.notebook_path,
            "sql_query": task.sql_query,
            "parameters": task.parameters,
            "job": {"entity_id": job.entity_id if job else None, "name": job.name if job else None},
            "waits_on": keys(task.depends_on),
            "blocks": [s.task_key for s in siblings if task.task_key in keys(s.depends_on)],
        }


@tool
async def get_data_dependencies(entity_id: str) -> Dict[str, Any]:
    """What a task or table reads and writes, from the knowledge graph.

    Answers 'which table was this failed task writing?' — the link that
    classic lineage does not carry. Sources are labelled so you can weigh
    them: 'discovered' means the enrichment agent read it out of the actual
    task code, 'lineage' means Databricks system tables reported it.

    Args:
        entity_id: A task or table entity_id.
    """
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(DiscoveredRelation).where(
                    or_(
                        DiscoveredRelation.source_entity_id == entity_id,
                        DiscoveredRelation.target_entity_id == entity_id,
                    )
                ).limit(60)
            )
        ).scalars().all()

        reads, writes, other = [], [], []
        for row in rows:
            outgoing = row.source_entity_id == entity_id
            peer = row.target_entity_id if outgoing else row.source_entity_id
            item = {
                "entity_id": peer,
                "relation": row.relation_type,
                "confidence": round(row.confidence, 2),
                "why": (row.rationale or "")[:220],
            }
            name = row.relation_type.upper()
            if "READ" in name and outgoing:
                reads.append(item)
            elif "WRITE" in name and outgoing:
                writes.append(item)
            else:
                other.append(item)

        lineage = (
            await db.execute(
                select(LineageEdge).where(
                    or_(
                        LineageEdge.source_entity_id == entity_id,
                        LineageEdge.target_entity_id == entity_id,
                    )
                ).limit(40)
            )
        ).scalars().all()

        return {
            "entity_id": entity_id,
            "reads": reads[:20],
            "writes": writes[:20],
            "other_links": other[:20],
            "lineage_upstream": [
                e.source_entity_id for e in lineage if e.target_entity_id == entity_id
            ][:15],
            "lineage_downstream": [
                e.target_entity_id for e in lineage if e.source_entity_id == entity_id
            ][:15],
            "note": (
                "Empty reads/writes means this entity has not been enriched yet, "
                "not that it touches nothing."
            )
            if not rows
            else None,
        }


@tool
async def get_entity_profile(entity_id: str) -> Dict[str, Any]:
    """The enrichment agent's semantic profile of an entity, if one exists.

    Gives you what a table means, its grain, what it serves and how it is
    produced — context a column list cannot provide. Returns a 'not profiled'
    marker when enrichment has not reached this entity.

    Args:
        entity_id: Any entity_id.
    """
    async with async_session_factory() as db:
        profile = (
            await db.execute(
                select(EntityProfile).where(EntityProfile.entity_id == entity_id)
            )
        ).scalars().first()
        if not profile:
            return {"entity_id": entity_id, "profiled": False}

        return {
            "entity_id": entity_id,
            "profiled": True,
            "kind": profile.kind,
            "summary": profile.summary,
            "purpose": profile.purpose,
            "data_product": profile.data_product,
            "semantic_tags": profile.semantic_tags,
            "generated_at": profile.generated_at.isoformat(),
        }


@tool
async def get_blast_radius(entity_id: str) -> Dict[str, Any]:
    """Who is affected downstream if this table is wrong or missing.

    Use after identifying the table a failure corrupted, to state impact in
    the Lineage & Impact section rather than guessing at it.

    Args:
        entity_id: A table entity_id.
    """
    async with async_session_factory() as db:
        consumers = (
            await db.execute(
                select(DiscoveredRelation).where(
                    DiscoveredRelation.target_entity_id == entity_id
                ).limit(50)
            )
        ).scalars().all()
        produced_by = [
            {"entity_id": r.source_entity_id, "relation": r.relation_type}
            for r in consumers
            if "WRITE" in r.relation_type.upper()
        ]
        read_by = [
            {"entity_id": r.source_entity_id, "relation": r.relation_type}
            for r in consumers
            if "READ" in r.relation_type.upper()
        ]

        downstream = (
            await db.execute(
                select(LineageEdge).where(LineageEdge.source_entity_id == entity_id).limit(40)
            )
        ).scalars().all()

        return {
            "entity_id": entity_id,
            "written_by": produced_by[:15],
            "read_by": read_by[:15],
            "flows_into": [e.target_entity_id for e in downstream][:20],
        }


@tool
async def search_entity_map(keyword: str, kinds: str = "") -> List[Dict[str, str]]:
    """Search every grain of the warehouse, not just tables.

    Args:
        keyword: Substring to match on the entity name.
        kinds: Optional comma-separated filter, e.g. 'task,job,table'.
    """
    async with async_session_factory() as db:
        graph = EntityGraph(db)
        kind_list = [k.strip() for k in kinds.split(",") if k.strip()] or None
        results = await graph.search(keyword, kinds=kind_list, limit=25)
        return [
            {"entity_id": r["id"], "kind": r["kind"], "name": r["label"], "detail": r["sublabel"]}
            for r in results
        ]


@tool
async def explore_entity(entity_id: str, relations: str = "", limit: int = 25) -> Dict[str, Any]:
    """Walk the entity map one hop from ANY node, along ANY relationship.

    This is the general navigation tool. The purpose-built tools cover common
    paths, but this one reaches everything: a table's columns, a schema's
    tables, a catalog's schemas, a job's tasks, an entity's evidence and
    change events, and any relationship the enrichment agent invented.

    Call it with no relation filter first to see what this entity is connected
    by, then call again filtered when one relation has many neighbours.

    Args:
        entity_id: Any node id, e.g. 'table:<ws>:<cat>.<sch>.<tbl>',
            'schema:<ws>:<cat>.<sch>', 'job:<ws>:<id>', 'column:<ws>:<fqn>'.
        relations: Optional comma-separated filter, e.g. 'HAS_COLUMN' or
            'READS_TABLE,WRITES_TABLE'. Empty means every relation.
        limit: Max neighbours per relation.
    """
    async with async_session_factory() as db:
        graph = EntityGraph(db)
        wanted = {r.strip().upper() for r in relations.split(",") if r.strip()}
        # No filter means every relation the map defines, plus the agent's
        # open vocabulary, which is admitted by the DISCOVERED gate.
        allowed = wanted or ({r["name"] for r in RELATIONS} | {"DISCOVERED"})

        edges, truncations = await graph.expand(entity_id, relations=allowed, limit=limit)
        if not edges:
            return {
                "entity_id": entity_id,
                "neighbours": {},
                "note": "No relationships found. Check the entity_id is exact, or widen the filter.",
            }

        grouped: Dict[str, List[Dict[str, str]]] = {}
        for edge in edges:
            outgoing = edge["source"] == entity_id
            peer = edge["target"] if outgoing else edge["source"]
            grouped.setdefault(edge["relation"], []).append(
                {
                    "entity_id": peer,
                    "kind": peer.split(":", 1)[0],
                    "direction": "outgoing" if outgoing else "incoming",
                }
            )

        return {
            "entity_id": entity_id,
            "relation_counts": {k: len(v) for k, v in sorted(grouped.items())},
            "neighbours": {k: v[:limit] for k, v in grouped.items()},
            "truncated": [t["relation"] for t in truncations] or None,
        }


@tool
async def get_entity_details(entity_id: str) -> Dict[str, Any]:
    """Every stored attribute of any entity, plus its exact neighbour counts.

    Use this to inspect a node of any kind — including ones with no dedicated
    tool, such as a schema, a catalog, an evidence record or a change event —
    and to see how many neighbours it has per relation before expanding.

    Args:
        entity_id: Any node id.
    """
    async with async_session_factory() as db:
        graph = EntityGraph(db)
        detail = await graph.entity_detail(entity_id)
        attributes = {
            k: v
            for k, v in (detail.get("attributes") or {}).items()
            if k not in {"id", "workspace_id", "created_at", "updated_at"} and v not in (None, "")
        }
        return {
            "entity_id": detail["id"],
            "kind": detail["kind"],
            "known": detail["known"],
            "attributes": attributes,
            "relations": [
                {"relation": r["relation"], "count": r["count"], "sample": r["sample"][:5]}
                for r in detail.get("relations", [])
            ],
            "note": None
            if detail["known"]
            else "Referenced by other records but never synced into the warehouse.",
        }


DATA_ENGINEER_TOOLS = [
    get_failed_run_details,
    get_table_lineage,
    get_recent_changes,
    search_tables,
    get_task_error_trace,
    read_databricks_text_file,
    list_databricks_directory,
    query_databricks_data_file,
    # Knowledge graph
    get_task_context,
    get_data_dependencies,
    get_entity_profile,
    get_blast_radius,
    search_entity_map,
    explore_entity,
    get_entity_details,
]
