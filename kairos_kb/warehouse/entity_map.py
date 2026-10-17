"""The Synthetic Warehouse entity map.

This is the declarative description of *what exists* in the warehouse and
*how the grains connect*. It is served to agents so they can plan a
traversal before issuing one, and it drives the generic traversal engine
in :mod:`kairos_kb.warehouse.entity_graph`.

Node IDs reuse the ``<kind>:<workspace>:<fqn>`` entity_id convention that
the ingestion layer already writes. Entities that carry no natural entity_id
(workspace, evidence, change events, sync state) get a synthetic ID in the
same shape so every node in the graph is addressable by a single string.
"""

from __future__ import annotations

from typing import Any, Dict, List

# ── Entity kinds ─────────────────────────────────────────────────────

ENTITY_KINDS: Dict[str, Dict[str, Any]] = {
    "workspace": {
        "label": "Workspace",
        "table": "workspaces",
        "grain": "One connected Databricks workspace.",
        "id_format": "workspace:<workspace_name>",
        "natural_entity_id": False,
    },
    "catalog": {
        "label": "Catalog",
        "table": "catalogs",
        "grain": "Unity Catalog catalog.",
        "id_format": "catalog:<workspace>:<catalog>",
        "natural_entity_id": True,
    },
    "schema": {
        "label": "Schema",
        "table": "schemas",
        "grain": "Unity Catalog schema (database).",
        "id_format": "schema:<workspace>:<catalog>.<schema>",
        "natural_entity_id": True,
    },
    "table": {
        "label": "Table",
        "table": "tables",
        "grain": "Unity Catalog table or view.",
        "id_format": "table:<workspace>:<catalog>.<schema>.<table>",
        "natural_entity_id": True,
    },
    "column": {
        "label": "Column",
        "table": "columns",
        "grain": "A single column of a table. Finest structural grain.",
        "id_format": "column:<workspace>:<catalog>.<schema>.<table>.<column>",
        "natural_entity_id": True,
    },
    "job": {
        "label": "Job",
        "table": "jobs",
        "grain": "Databricks job definition.",
        "id_format": "job:<workspace>:<job_native_id>",
        "natural_entity_id": True,
    },
    "task": {
        "label": "Task",
        "table": "tasks",
        "grain": "A task inside a job definition.",
        "id_format": "task:<workspace>:<job_native_id>:<task_key>",
        "natural_entity_id": True,
    },
    "run": {
        "label": "Run",
        "table": "runs",
        "grain": "One execution of a job. Carries result_state and error_message.",
        "id_format": "run:<workspace>:<job_native_id>:<run_native_id>",
        "natural_entity_id": True,
    },
    "taskrun": {
        "label": "TaskRun",
        "table": "task_runs",
        "grain": "One execution of one task. Finest operational grain; where failures surface.",
        "id_format": "taskrun:<workspace>:<run_native_id>:<task_key>",
        "natural_entity_id": True,
    },
    "evidence": {
        "label": "Evidence",
        "table": "evidence",
        "grain": "A raw observation backing a claim about some entity.",
        "id_format": "evidence:<uuid>",
        "natural_entity_id": False,
    },
    "change": {
        "label": "ChangeEvent",
        "table": "change_events",
        "grain": "A detected change on some entity. The temporal grain.",
        "id_format": "change:<uuid>",
        "natural_entity_id": False,
    },
    "syncstate": {
        "label": "SyncState",
        "table": "sync_states",
        "grain": "Ingestion progress for one workspace/domain pair.",
        "id_format": "syncstate:<uuid>",
        "natural_entity_id": False,
    },
}


# ── Relationships ────────────────────────────────────────────────────
# ``group`` drives both the default traversal set and the UI legend.

RELATIONS: List[Dict[str, Any]] = [
    # Structural containment
    {
        "name": "CONTAINS",
        "source": "workspace",
        "target": "catalog",
        "group": "structural",
        "via": "catalogs.workspace_id",
        "description": "Workspace contains catalogs.",
    },
    {
        "name": "CONTAINS",
        "source": "catalog",
        "target": "schema",
        "group": "structural",
        "via": "schemas.catalog_id",
        "description": "Catalog contains schemas.",
    },
    {
        "name": "CONTAINS",
        "source": "schema",
        "target": "table",
        "group": "structural",
        "via": "tables.schema_id",
        "description": "Schema contains tables.",
    },
    {
        "name": "HAS_COLUMN",
        "source": "table",
        "target": "column",
        "group": "structural",
        "via": "columns.table_id",
        "description": "Table has columns.",
    },
    # Pipeline definition
    {
        "name": "CONTAINS",
        "source": "workspace",
        "target": "job",
        "group": "pipeline",
        "via": "jobs.workspace_id",
        "description": "Workspace contains jobs.",
    },
    {
        "name": "HAS_TASK",
        "source": "job",
        "target": "task",
        "group": "pipeline",
        "via": "tasks.job_id",
        "description": "Job defines tasks.",
    },
    {
        "name": "DEPENDS_ON",
        "source": "task",
        "target": "task",
        "group": "pipeline",
        "via": "tasks.depends_on",
        "description": "Task waits on sibling tasks within the same job.",
    },
    # Execution
    {
        "name": "HAS_RUN",
        "source": "job",
        "target": "run",
        "group": "operational",
        "via": "runs.job_id",
        "description": "Job has executions.",
    },
    {
        "name": "HAS_TASK_RUN",
        "source": "run",
        "target": "taskrun",
        "group": "operational",
        "via": "task_runs.run_id",
        "description": "Run has per-task executions.",
    },
    {
        "name": "INSTANCE_OF",
        "source": "taskrun",
        "target": "task",
        "group": "operational",
        "via": "task_runs.task_id, falling back to (job_id, task_key)",
        "description": "A task execution realises a task definition.",
    },
    # Data flow
    {
        "name": "FLOWS_TO",
        "source": "table",
        "target": "table",
        "group": "lineage",
        "via": "lineage_edges (source_type=TABLE)",
        "description": "Table-level lineage.",
    },
    {
        "name": "FLOWS_TO",
        "source": "column",
        "target": "column",
        "group": "lineage",
        "via": "lineage_edges (source_type=COLUMN)",
        "description": "Column-level lineage.",
    },
    # Provenance and time
    {
        "name": "EVIDENCED_BY",
        "source": "*",
        "target": "evidence",
        "group": "provenance",
        "via": "evidence.entity_id",
        "description": "Any entity may be backed by raw observations.",
    },
    {
        "name": "CHANGED_BY",
        "source": "*",
        "target": "change",
        "group": "provenance",
        "via": "change_events.entity_id",
        "description": "Any entity may have detected changes.",
    },
    {
        "name": "SUPPORTED_BY",
        "source": "change",
        "target": "evidence",
        "group": "provenance",
        "via": "change_events.evidence_id",
        "description": "A change event may cite the evidence that revealed it.",
    },
    {
        "name": "HAS_SYNC_STATE",
        "source": "workspace",
        "target": "syncstate",
        "group": "operational",
        "via": "sync_states.workspace_id",
        "description": "Per-domain ingestion progress.",
    },
    # Agent-discovered. The relation_type is open vocabulary, so this single
    # entry is a gate for the whole group rather than a description of one edge.
    {
        "name": "DISCOVERED",
        "source": "*",
        "target": "*",
        "group": "discovered",
        "via": "discovered_relations",
        "description": (
            "Relationships the enrichment agent found by reading code, config, "
            "and data. relation_type is free-form; every row carries a rationale "
            "and, where available, the evidence it was read from."
        ),
    },
]

RELATION_GROUPS = ["structural", "pipeline", "operational", "lineage", "provenance", "discovered"]

# Provenance fans out enormously (8k+ change events on columns alone), so it
# is reachable but never auto-expanded during a traversal.
DEFAULT_RELATION_GROUPS = ["structural", "pipeline", "operational", "lineage", "discovered"]


def relation_names_for_groups(groups: List[str]) -> set[str]:
    """Relation names belonging to any of the given groups."""
    return {r["name"] for r in RELATIONS if r["group"] in groups}


def entity_map_document() -> Dict[str, Any]:
    """The full entity map, as served to agents."""
    return {
        "kinds": [{"kind": kind, **meta} for kind, meta in ENTITY_KINDS.items()],
        "relations": RELATIONS,
        "relation_groups": RELATION_GROUPS,
        "default_relation_groups": DEFAULT_RELATION_GROUPS,
        "id_convention": (
            "Every node is addressed by a single string id of the form "
            "'<kind>:<workspace>:<fully.qualified.name>'. Synthetic kinds "
            "(workspace, evidence, change, syncstate) follow the same shape."
        ),
    }
