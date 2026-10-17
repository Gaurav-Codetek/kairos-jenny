"""The Kairos Mesh — the warehouse as bundles, dbt-manifest style.

A bundle is one addressable unit of the platform with its sub-grains folded
in, so the mesh stays readable:

  catalog   ← its own bundle
  schema    ← its own bundle
  table     ← its own bundle; columns are inherited (not separate bundles)
  volume    ← its own bundle; files under it are inherited
  pipeline  ← its own bundle (a Databricks job); runs are inherited
  task      ← its own bundle; task runs are inherited

Every bundle has a ``unique_id`` (``<resource_type>.<workspace>.<fqn>``, as in
a dbt manifest) and every relationship between two bundles a
``relationship_id``. Relationships are normalised to data-flow direction so
the mesh reads left → right like a dbt DAG: a dataset flows into the task
that reads it, and a task flows into the dataset it writes.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.models.catalog import Catalog
from kairos_kb.models.column import Column
from kairos_kb.models.discovered import DiscoveredEntity, DiscoveredRelation
from kairos_kb.models.job import Job
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.models.run import Run
from kairos_kb.models.schema import Schema
from kairos_kb.models.table import Table
from kairos_kb.models.task import Task
from kairos_kb.models.task_run import TaskRun
from kairos_kb.models.workspace import Workspace

FAILED_STATES = {"FAILED", "TIMEDOUT", "INTERNAL_ERROR", "UPSTREAM_FAILED", "MAXIMUM_CONCURRENT_RUNS_REACHED"}
RECENT_RUNS = 5
_VOLUME_PATH = re.compile(r"^/Volumes/([^/]+)/([^/]+)/([^/]+)(/.*)?$")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _rel_id(group: str, source: str, target: str) -> str:
    return "rel." + hashlib.sha1(f"{group}|{source}|{target}".encode()).hexdigest()[:12]


def _depends_on_keys(raw: Any) -> List[str]:
    if not raw:
        return []
    keys = []
    for item in raw:
        if isinstance(item, str):
            keys.append(item)
        elif isinstance(item, dict) and item.get("task_key"):
            keys.append(item["task_key"])
    return keys


def _flow(verb: str, s_type: str, t_type: str) -> Optional[Tuple[bool, str]]:
    """How a discovered relation reads as data flow.

    Returns (reverse, group): ``reverse`` flips source/target so the edge runs
    in data-flow direction. None means the relation is not flow (containment
    duplicates, log mentions, variants) and stays out of the mesh.
    """
    v = verb.upper()
    processors, datasets = {"pipeline", "task", "product"}, {"table", "volume"}

    if {s_type, t_type} <= processors:
        if "DEPENDS_ON" in v:
            return True, "depends_on"   # s depends on t → t runs first
        return None

    if (s_type in processors) != (t_type in processors) and {s_type, t_type} <= processors | datasets:
        dataset_is_source = s_type in datasets
        if any(w in v for w in ("READ", "CONSUM", "USES")):
            return (not dataset_is_source), "flow"      # dataset → processor
        if any(w in v for w in ("WRIT", "CREATED", "INCOMING", "PRODUC", "LOAD")):
            return dataset_is_source, "flow"            # processor → dataset
        return None

    if {s_type, t_type} <= datasets:
        if "STORE" in v:
            return (s_type == "table"), "storage"       # volume → table it backs
        if any(w in v for w in ("DERIVES_FROM", "READS", "USES_TABLE", "ASSOCIATED_SOURCE")):
            return True, "flow"                          # s built from t → t → s
        if any(w in v for w in ("FEEDS", "CONTRIBUTES", "TRANSFORMS_TO", "CONSUMED_BY")):
            return False, "flow"
    return None


class MeshBuilder:
    def __init__(self) -> None:
        self.bundles: Dict[str, Dict[str, Any]] = {}
        self.by_entity: Dict[str, str] = {}   # entity_id → bundle unique_id
        self.rels: Dict[str, Dict[str, Any]] = {}

    def add(self, resource_type: str, ws: str, fqn: List[str], *, name: str, entity_id: Optional[str],
            parent: Optional[str], **extra: Any) -> str:
        uid = ".".join([resource_type, ws, *[_slug(p) or "_" for p in fqn]])
        self.bundles[uid] = {
            "unique_id": uid,
            "resource_type": resource_type,
            "name": name,
            "fqn": fqn,
            "entity_id": entity_id,
            "parent": parent,
            "inherited": {},
            **extra,
        }
        if entity_id:
            self.by_entity[entity_id] = uid
        return uid

    def relate(self, group: str, rel_type: str, source: str, target: str, origin: str,
               confidence: Optional[float] = None) -> None:
        if source == target or source not in self.bundles or target not in self.bundles:
            return
        rid = _rel_id(group, source, target)
        rel = self.rels.get(rid)
        if not rel:
            rel = self.rels[rid] = {
                "relationship_id": rid, "group": group, "source": source, "target": target,
                "types": [], "origins": [], "confidence": confidence,
            }
        if rel_type not in rel["types"]:
            rel["types"].append(rel_type)
        if origin not in rel["origins"]:
            rel["origins"].append(origin)
        if confidence is not None:
            rel["confidence"] = max(rel["confidence"] or 0, confidence)


async def build_mesh(db: AsyncSession, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    ws_query = select(Workspace)
    if workspace_id:
        ws_query = ws_query.where(Workspace.id == workspace_id)
    workspaces = (await db.execute(ws_query)).scalars().all()
    ws_slug = {w.id: _slug(w.name) for w in workspaces}
    ws_ids = list(ws_slug)
    m = MeshBuilder()

    def scoped(model):
        return select(model).where(model.workspace_id.in_(ws_ids))

    # ── Containment: catalog → schema → table ──
    catalogs = (await db.execute(scoped(Catalog))).scalars().all()
    schemas = (await db.execute(scoped(Schema))).scalars().all()
    tables = (await db.execute(scoped(Table))).scalars().all()
    col_counts = dict((await db.execute(
        select(Column.table_id, func.count()).where(Column.workspace_id.in_(ws_ids)).group_by(Column.table_id)
    )).all())

    cat_uid, sch_uid = {}, {}
    for c in catalogs:
        cat_uid[c.id] = m.add("catalog", ws_slug[c.workspace_id], [c.name], name=c.name, entity_id=c.entity_id,
                              parent=None, description=c.comment)
    for s in schemas:
        parent = cat_uid.get(s.catalog_id)
        sch_uid[s.id] = m.add("schema", ws_slug[s.workspace_id], s.full_name.split("."), name=s.name,
                              entity_id=s.entity_id, parent=parent, description=s.comment)
        if parent:
            m.relate("containment", "CONTAINS", parent, sch_uid[s.id], "synced")
    for t in tables:
        parent = sch_uid.get(t.schema_id)
        uid = m.add("table", ws_slug[t.workspace_id], t.full_name.split("."), name=t.name, entity_id=t.entity_id,
                    parent=parent, description=t.comment, table_type=t.table_type,
                    format=t.data_source_format)
        m.bundles[uid]["inherited"] = {"columns": int(col_counts.get(t.id, 0))}
        if parent:
            m.relate("containment", "CONTAINS", parent, uid, "synced")

    # ── Pipelines (jobs) with runs inherited; tasks with task runs inherited ──
    jobs = (await db.execute(scoped(Job))).scalars().all()
    runs = (await db.execute(
        select(Run.id, Run.job_id, Run.result_state, Run.state, Run.start_time, Run.source_native_id,
               Run.execution_duration_ms)
        .where(Run.workspace_id.in_(ws_ids)).order_by(Run.start_time.desc().nulls_last())
    )).all()
    runs_by_job: Dict[Any, List[Any]] = defaultdict(list)
    run_job = {}
    for r in runs:
        runs_by_job[r.job_id].append(r)
        run_job[r.id] = r.job_id

    job_uid = {}
    for j in jobs:
        uid = m.add("pipeline", ws_slug[j.workspace_id], [j.source_native_id], name=j.name, entity_id=j.entity_id,
                    parent=None, schedule=(j.schedule or {}).get("quartz_cron_expression") if j.schedule else None)
        job_uid[j.id] = uid
        jr = runs_by_job.get(j.id, [])
        results = Counter((r.result_state or r.state or "UNKNOWN").upper() for r in jr)
        m.bundles[uid]["inherited"] = {
            "runs": len(jr),
            "failed_runs": sum(n for s, n in results.items() if s in FAILED_STATES),
            "by_result": dict(results),
            "recent": [
                {"run_id": str(r.id), "result": (r.result_state or r.state), "start_time":
                 r.start_time.isoformat() if r.start_time else None, "duration_ms": r.execution_duration_ms}
                for r in jr[:RECENT_RUNS]
            ],
        }
        m.bundles[uid]["status"] = (jr[0].result_state or jr[0].state) if jr else None

    tasks = (await db.execute(scoped(Task))).scalars().all()
    task_runs = (await db.execute(
        select(TaskRun.task_id, TaskRun.run_id, TaskRun.task_key, TaskRun.result_state, TaskRun.state,
               TaskRun.start_time)
        .where(TaskRun.workspace_id.in_(ws_ids)).order_by(TaskRun.start_time.desc().nulls_last())
    )).all()
    task_by_key = {(t.job_id, t.task_key): t.id for t in tasks}
    tr_by_task: Dict[Any, List[Any]] = defaultdict(list)
    for tr in task_runs:
        tid = tr.task_id or task_by_key.get((run_job.get(tr.run_id), tr.task_key))
        if tid:
            tr_by_task[tid].append(tr)

    task_uid = {}
    for t in tasks:
        parent = job_uid.get(t.job_id)
        job_native = parent.split(".", 2)[2] if parent else "_"
        uid = m.add("task", ws_slug[t.workspace_id], [job_native, t.task_key], name=t.task_key,
                    entity_id=t.entity_id, parent=parent, task_type=t.task_type, notebook_path=t.notebook_path)
        task_uid[(t.job_id, t.task_key)] = uid
        trs = tr_by_task.get(t.id, [])
        results = Counter((r.result_state or r.state or "UNKNOWN").upper() for r in trs)
        m.bundles[uid]["inherited"] = {
            "task_runs": len(trs),
            "failed_runs": sum(n for s, n in results.items() if s in FAILED_STATES),
            "by_result": dict(results),
        }
        m.bundles[uid]["status"] = (trs[0].result_state or trs[0].state) if trs else None
        if parent:
            m.relate("pipeline", "HAS_TASK", parent, uid, "synced")
    for t in tasks:
        for key in _depends_on_keys(t.depends_on):
            upstream = task_uid.get((t.job_id, key))
            if upstream:
                m.relate("depends_on", "DEPENDS_ON", upstream, task_uid[(t.job_id, t.task_key)], "synced")

    # ── Volumes: from /Volumes/<catalog>/<schema>/<volume> paths; files inherited ──
    discovered = (await db.execute(scoped(DiscoveredEntity))).scalars().all()
    schema_by_fqn = {s.full_name.lower(): sch_uid[s.id] for s in schemas}
    volume_files: Dict[str, List[str]] = defaultdict(list)
    for d in discovered:
        match = _VOLUME_PATH.match(d.full_name or d.name or "")
        if not match:
            continue  # cloud storage locations of managed tables are not UC volumes
        cat, sch, vol, rest = match.groups()
        ws = d.entity_id.split(":")[1] if d.entity_id.count(":") >= 2 else "_"
        uid = ".".join(["volume", _slug(ws), _slug(cat), _slug(sch), _slug(vol)])
        if uid not in m.bundles:
            parent = schema_by_fqn.get(f"{cat}.{sch}".lower())
            m.add("volume", _slug(ws), [cat, sch, vol], name=vol, entity_id=None, parent=parent,
                  path=f"/Volumes/{cat}/{sch}/{vol}")
            if parent:
                m.relate("containment", "CONTAINS", parent, uid, "discovered")
        m.by_entity[d.entity_id] = uid
        if rest and rest.strip("/"):
            volume_files[uid].append(rest.strip("/"))
    for uid, files in volume_files.items():
        m.bundles[uid]["inherited"] = {"paths": len(set(files)), "sample": sorted(set(files))[:8]}

    # ── Data products: business concepts defined in Kairos, each reading its input tables ──
    for d in discovered:
        if d.origin != "product":
            continue
        a = d.attrs or {}
        ws = d.entity_id.split(":")[1] if d.entity_id.count(":") >= 2 else "_"
        m.add("product", _slug(ws), [d.full_name or d.name], name=d.name, entity_id=d.entity_id, parent=None,
              domain=a.get("domain"), status=a.get("health"), product_status=a.get("status"),
              inherited={"metrics": len(a.get("metrics") or []), "inputs": len(a.get("inputs") or [])})

    # ── Data flow: synced lineage (column lineage rolls up to its tables) ──
    edges = (await db.execute(scoped(LineageEdge))).scalars().all()
    for e in edges:
        src, tgt = e.source_entity_id, e.target_entity_id
        if e.source_type != "TABLE":
            src = "table:" + src.split(":", 1)[1].rsplit(".", 1)[0] if src.startswith("column:") else src
            tgt = "table:" + tgt.split(":", 1)[1].rsplit(".", 1)[0] if tgt.startswith("column:") else tgt
        s, t = m.by_entity.get(src), m.by_entity.get(tgt)
        if s and t:
            m.relate("flow", "FLOWS_TO", s, t, "lineage")

    # ── Data flow: what the enrichment agent read out of code ──
    rels = (await db.execute(
        scoped(DiscoveredRelation).where(DiscoveredRelation.status != "contradicted")
    )).scalars().all()
    for r in rels:
        s, t = _bundle_for(m, r.source_entity_id), _bundle_for(m, r.target_entity_id)
        if not s or not t:
            continue
        flow = _flow(r.relation_type, m.bundles[s]["resource_type"], m.bundles[t]["resource_type"])
        if not flow:
            continue
        reverse, group = flow
        src, tgt = (t, s) if reverse else (s, t)
        m.relate(group, r.relation_type, src, tgt, "discovered", confidence=r.confidence)

    # Child counts, so a collapsed bundle can say what it holds.
    children: Dict[str, Counter] = defaultdict(Counter)
    for b in m.bundles.values():
        if b["parent"]:
            children[b["parent"]][b["resource_type"]] += 1
    for uid, b in m.bundles.items():
        b["children"] = dict(children.get(uid, {}))

    bundles = list(m.bundles.values())
    return {
        "workspaces": [{"id": str(w.id), "name": w.name, "slug": ws_slug[w.id]} for w in workspaces],
        "bundles": bundles,
        "relationships": list(m.rels.values()),
        "stats": {
            "bundles": dict(Counter(b["resource_type"] for b in bundles)),
            "relationships": dict(Counter(r["group"] for r in m.rels.values())),
            "inherited": {
                "columns": sum(b["inherited"].get("columns", 0) for b in bundles),
                "runs": sum(b["inherited"].get("runs", 0) for b in bundles),
                "task_runs": sum(b["inherited"].get("task_runs", 0) for b in bundles),
            },
        },
    }


def _bundle_for(m: MeshBuilder, entity_id: str) -> Optional[str]:
    """Map any entity id onto the bundle that owns it."""
    if entity_id in m.by_entity:
        return m.by_entity[entity_id]
    kind, _, rest = entity_id.partition(":")
    if kind == "column":  # columns are inherited by their table
        return m.by_entity.get("table:" + rest.rsplit(".", 1)[0])
    if kind in ("volume", "file"):
        path = rest.split(":", 1)[1] if ":" in rest else rest
        match = _VOLUME_PATH.match(path)
        if match:
            cat, sch, vol, _ = match.groups()
            ws = rest.split(":", 1)[0]
            return next(
                (uid for uid in m.bundles
                 if uid == ".".join(["volume", _slug(ws), _slug(cat), _slug(sch), _slug(vol)])),
                None,
            )
    return None
