"""Object sync — every platform object beyond tables and pipelines, as entities on the map.

Objects (warehouses, roles, integrations, stages, file formats, procedures, functions, pipes,
policies, tags, alerts, notebooks, apps, models, semantic views, locations …) are stored as
entities with origin "platform": entity_id "<kind>:<workspace>:<full name>", their definition
and properties in attrs. Links read from metadata are stored as verified relations with
source_ref "platform metadata" and replaced on every sync, so they always match the platform.
Code held by objects (procedure and function bodies, alert conditions and actions, semantic
view definitions) is scanned here for the tables it reads and writes, as task code is.
Grants are attached to every object, table, schema and database they cover.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.ingestion.progress import NullProgress, SyncProgress
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.discovered import DiscoveredEntity, DiscoveredRelation
from kairos_kb.models.schema import Schema
from kairos_kb.models.table import Table
from kairos_kb.models.task import Task

logger = logging.getLogger(__name__)

ORIGIN = "platform"
SOURCE_REF = "platform metadata"
# Objects whose code is scanned at sync for the tables it reads and writes.
CODE_KINDS = {"procedure", "function", "alert", "semantic_view", "cortex_search", "dbt_project"}
# How GRANTS_TO_ROLES names each kind of object.
GRANT_ON = {
    "warehouse": "WAREHOUSE", "integration": "INTEGRATION", "stage": "STAGE", "procedure": "PROCEDURE",
    "function": "FUNCTION", "file_format": "FILE_FORMAT", "pipe": "PIPE", "sequence": "SEQUENCE", "tag": "TAG",
    "alert": "ALERT", "notebook": "NOTEBOOK", "streamlit": "STREAMLIT", "model": "MODEL", "secret": "SECRET",
    "network_rule": "NETWORK_RULE", "compute_pool": "COMPUTE_POOL", "application": "APPLICATION",
    "external_volume": "EXTERNAL_VOLUME", "resource_monitor": "RESOURCE_MONITOR", "user": "USER",
    "semantic_view": "SEMANTIC_VIEW", "cortex_search": "CORTEX_SEARCH_SERVICE", "git_repository": "GIT_REPOSITORY",
}
TABLE_GRANT_ON = ("TABLE", "VIEW", "MATERIALIZED_VIEW", "DYNAMIC_TABLE", "STREAM", "EXTERNAL_TABLE",
                  "EVENT_TABLE", "ICEBERG_TABLE")


def _rationale(relation: str, detail: Dict[str, Any]) -> str:
    text = {
        "FEEDS": "loads it with COPY INTO", "LOADS_INTO": "files from here were loaded into it (copy history)",
        "STORED_AT": "keeps its files at this location", "USES_INTEGRATION": "uses this integration",
        "ALLOWS": "allows access to it", "BLOCKS": "blocks access to it", "USES_FORMAT": "parses files with it",
        "PROTECTS": "is protected by this policy", "TAGS": "tags it", "TRACKED_BY": "is tracked by this stream",
        "INHERITS": "inherits this role", "HAS_ROLE": "is granted this role", "RUNS_ON": "runs on this warehouse",
        "LIMITED_BY": "is limited by this resource monitor", "TRIGGERS": "triggers it",
        "READS_FILE": "reads files from it", "WRITES_TABLE": "writes it", "READS_TABLE": "reads it",
        "CALLS": "calls it", "WITHIN": "lies within it", "USES": "uses it",
    }.get(relation, relation.lower().replace("_", " "))
    parts = [f"{k.replace('_', ' ')}: {v}" for k, v in detail.items()]
    return f"Platform metadata: {text}" + (f" ({'; '.join(parts)})" if parts else "") + "."


class ObjectSync:
    def __init__(self, connector, workspace_id: uuid.UUID, workspace_name: str,
                 progress: Optional[SyncProgress] = None) -> None:
        self._connector = connector
        self._workspace_id = workspace_id
        self._workspace_name = workspace_name
        self._progress = progress or NullProgress()

    def _eid(self, kind: str, full_name: str) -> str:
        return f"{kind}:{self._workspace_name}:{full_name}"

    async def sync(self, session: AsyncSession) -> Dict[str, int]:
        if not hasattr(self._connector, "read_objects"):
            return {}
        progress = self._progress
        progress.set_step("Reading every object: warehouses, roles, integrations, stages, procedures, policies…")
        data = await self._connector.read_objects()
        now = datetime.now(timezone.utc)

        # ── Entities ──
        existing = {e.entity_id: e for e in (await session.execute(select(DiscoveredEntity).where(
            DiscoveredEntity.workspace_id == self._workspace_id))).scalars()}
        grants = data.get("grants") or {}
        current = set()
        counts: Dict[str, int] = {}
        for o in data["objects"]:
            eid = self._eid(o["kind"], o["full_name"])
            current.add(eid)
            on = GRANT_ON.get(o["kind"])
            if o["kind"] == "policy":
                on = (o["properties"].get("policy_kind") or "MASKING_POLICY")
            attrs = {"platform": getattr(self._connector, "platform", "snowflake"), "owner": o.get("owner"),
                     "comment": o.get("comment"), "parent": o.get("parent"), "definition": o.get("definition"),
                     "properties": o.get("properties") or {},
                     "grants": grants.get(f"{on}:{o['full_name'].upper()}") if on else None}
            attrs = {k: v for k, v in attrs.items() if v not in (None, {}, [])}
            row = existing.get(eid)
            if row is None:
                row = DiscoveredEntity(workspace_id=self._workspace_id, entity_id=eid, kind=o["kind"],
                                       name=o["name"][:512], full_name=o["full_name"][:1024], origin=ORIGIN,
                                       rationale="Synced from platform metadata.", first_seen_at=now, last_seen_at=now)
                session.add(row)
            elif row.origin != ORIGIN:
                # The agent had minted this entity from code; the platform now describes it.
                row.origin = ORIGIN
            row.kind, row.name, row.attrs, row.last_seen_at = o["kind"], o["name"][:512], attrs, now
            counts[o["kind"]] = counts.get(o["kind"], 0) + 1
            progress.bump("objects")
        stale = [eid for eid, e in existing.items() if e.origin == ORIGIN and eid not in current]
        if stale:
            await session.execute(delete(DiscoveredEntity).where(DiscoveredEntity.entity_id.in_(stale)))
        await session.flush()

        # ── Grants on tables, schemas and databases ──
        await self._attach_table_grants(session, grants)

        # ── Links: replaced wholesale, so they always match the platform ──
        await session.execute(delete(DiscoveredRelation).where(
            DiscoveredRelation.workspace_id == self._workspace_id, DiscoveredRelation.source_ref == SOURCE_REF))
        tables = {fn.upper(): eid for fn, eid in (await session.execute(
            select(Table.full_name, Table.entity_id).where(Table.workspace_id == self._workspace_id))).all()}
        catalogs = {n.upper(): eid for n, eid in (await session.execute(
            select(Catalog.name, Catalog.entity_id).where(Catalog.workspace_id == self._workspace_id))).all()}
        objects = {(k, fn.upper()): eid for k, fn, eid in (await session.execute(
            select(DiscoveredEntity.kind, DiscoveredEntity.full_name, DiscoveredEntity.entity_id)
            .where(DiscoveredEntity.workspace_id == self._workspace_id))).all() if fn}

        def resolve(end: Tuple[str, str]) -> Optional[str]:
            kind, name = end
            if not name:
                return None
            if kind == "task_entity":
                return name
            if kind == "table":
                return tables.get(name.upper())
            if kind == "catalog":
                return catalogs.get(name.upper())
            hit = objects.get((kind, name.upper()))
            if hit is None and kind in ("procedure", "function"):
                # Named without argument types: the first overload.
                hit = next((eid for (k, fn), eid in objects.items()
                            if k == kind and fn.split("(")[0] == name.upper().split("(")[0]), None)
            return hit

        links = list(data["links"]) + self._code_links(data["objects"], tables) + \
            await self._task_links(session, objects)
        taken = {(s, t, r) for s, t, r in (await session.execute(
            select(DiscoveredRelation.source_entity_id, DiscoveredRelation.target_entity_id,
                   DiscoveredRelation.relation_type)
            .where(DiscoveredRelation.workspace_id == self._workspace_id))).all()}
        added = 0
        for link in links:
            src, tgt = resolve(link["source"]), resolve(link["target"])
            if not src or not tgt or src == tgt:
                continue
            key = (src, tgt, link["relation"])
            if key in taken:
                continue
            taken.add(key)
            session.add(DiscoveredRelation(
                workspace_id=self._workspace_id, source_entity_id=src, target_entity_id=tgt,
                relation_type=link["relation"], confidence=1.0, rationale=_rationale(link["relation"], link["detail"]),
                source_ref=SOURCE_REF, status="verified", observed_at=now))
            added += 1
        await session.flush()
        counts["links"] = added
        progress.note(f"Objects: {sum(v for k, v in counts.items() if k != 'links')} across {len(counts) - 1} kinds "
                      f"({', '.join(f'{v} {k}' for k, v in sorted(counts.items()) if k != 'links')}); {added} links")
        return counts

    def _code_links(self, objects, tables: Dict[str, str]):
        """Tables named in object code, by how the code uses them."""
        from kairos_kb.enrichment.pipeline import scan_code

        known = {fn.lower(): eid for fn, eid in tables.items()}
        out = []
        for o in objects:
            if o["kind"] not in CODE_KINDS or not o.get("definition"):
                continue
            for t in scan_code(o["definition"], known).get("tables_in_code") or []:
                modes = set(t.get("modes") or [])
                line = (t.get("lines") or [None])[0]
                rel = "WRITES_TABLE" if "write" in modes else "READS_TABLE"
                out.append({"source": (o["kind"], o["full_name"]), "target": ("table", t["table"].upper()),
                            "relation": rel, "detail": {"code_line": line}})
        return out

    async def _task_links(self, session: AsyncSession, objects: Dict[Tuple[str, str], str]):
        """A task whose code is a CALL: task → procedure."""
        out = []
        rows = (await session.execute(select(Task).where(
            Task.workspace_id == self._workspace_id, Task.notebook_path.like("snowflake://procedure/%")))).scalars()
        for task in rows:
            proc = task.notebook_path.split("snowflake://procedure/", 1)[1]
            out.append({"source": ("task_entity", task.entity_id), "target": ("procedure", proc), "relation": "CALLS",
                        "detail": {}})
        return out

    async def _attach_table_grants(self, session: AsyncSession, grants: Dict[str, Dict[str, list]]) -> None:
        if not grants:
            return
        by_name: Dict[str, Dict[str, list]] = {}
        for key, roles in grants.items():
            on, _, name = key.partition(":")
            if on in TABLE_GRANT_ON:
                by_name.setdefault(name, {}).update(roles)
        for t in (await session.execute(select(Table).where(Table.workspace_id == self._workspace_id))).scalars():
            g = by_name.get(t.full_name.upper())
            if g:
                t.properties = {**(t.properties or {}), "grants": g}
        for model, on in ((Schema, "SCHEMA"), (Catalog, "DATABASE")):
            for row in (await session.execute(select(model).where(model.workspace_id == self._workspace_id))).scalars():
                name = (row.full_name if model is Schema else row.name).upper()
                g = grants.get(f"{on}:{name}")
                if g:
                    row.properties = {**(row.properties or {}), "grants": g}


async def object_count(session: AsyncSession, workspace_id) -> int:
    return (await session.execute(select(func.count()).select_from(DiscoveredEntity).where(
        DiscoveredEntity.workspace_id == workspace_id, DiscoveredEntity.origin == ORIGIN))).scalar() or 0
