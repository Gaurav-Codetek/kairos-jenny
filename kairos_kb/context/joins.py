"""How two tables join, and why Kairos believes it.

Wrong joins are the most common way an agent produces a confident, wrong
number. So a join is proposed with its evidence, strongest first:

  grain key     the column is part of either table's stated grain key
  shared key    both tables have an identifier-like column of that name and a
                compatible type
  co-used       a pipeline task reads both tables, so they are combined somewhere
  lineage       one table is built from the other

A pair with no shared key can still be joined through a bridge table that
shares a key with each side; that is reported as a two-step path.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.context.documents import load_profile
from kairos_kb.enrichment.pipeline import canonical_relation
from kairos_kb.models.column import Column
from kairos_kb.models.discovered import DiscoveredRelation
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.models.table import Table

GENERIC = {"created_at", "updated_at", "load_date", "load_ts", "ingestion_time", "_rescued_data", "source",
           "source_file", "file_name", "etl_timestamp", "insert_date", "update_date", "status", "name",
           "description", "comment", "type", "flag", "is_active", "active", "version", "run_id", "batch_id"}
_ID_LIKE = re.compile(r"(^id$|_id$|_key$|_vid$|_code$|_num$|_number$|_no$|^npi$|^ndc|^dea|^hin$|_sk$|_nk$)", re.I)

STRINGS = {"STRING", "VARCHAR", "CHAR", "TEXT"}
INTEGERS = {"INT", "BIGINT", "LONG", "SHORT", "SMALLINT", "TINYINT", "INTEGER", "DECIMAL"}


def type_family(data_type: Optional[str]) -> str:
    t = (data_type or "").upper().split("(")[0]
    if t in STRINGS:
        return "string"
    if t in INTEGERS:
        return "integer"
    if t in ("DATE", "TIMESTAMP", "TIMESTAMP_NTZ"):
        return "time"
    return t.lower() or "unknown"


def is_key_like(name: str) -> bool:
    n = (name or "").lower()
    return n not in GENERIC and bool(_ID_LIKE.search(n))


def score_shared(shared: List[Tuple[str, str, str]], grain_a: Set[str], grain_b: Set[str]) -> List[Dict[str, Any]]:
    """Rank shared columns (name, type_a, type_b) as join keys, best first."""
    keys = []
    for name, ta, tb in shared:
        low = name.lower()
        if low in GENERIC:
            continue
        compatible = type_family(ta) == type_family(tb)
        in_grain = low in grain_a or low in grain_b
        key_like = is_key_like(name)
        if not (in_grain or key_like):
            continue
        score = (3 if in_grain else 0) + (2 if key_like else 0) + (1 if compatible else -2)
        reasons = []
        if in_grain:
            reasons.append("part of a stated grain key")
        if key_like:
            reasons.append("identifier-like name")
        reasons.append("same type family" if compatible else f"type differs ({ta} vs {tb}) — cast before joining")
        keys.append({"column": name, "score": score, "types": [ta, tb], "why": "; ".join(reasons)})
    return sorted(keys, key=lambda k: (-k["score"], k["column"]))


async def _table(db: AsyncSession, entity_id: str) -> Optional[Table]:
    return (await db.execute(select(Table).where(Table.entity_id == entity_id))).scalars().first()


async def _columns(db: AsyncSession, table_id) -> Dict[str, str]:
    return {n: t for n, t in (await db.execute(
        select(Column.name, Column.data_type).where(Column.table_id == table_id)
    )).all()}


async def _grain(db: AsyncSession, entity_id: str) -> Set[str]:
    p = await load_profile(db, entity_id) or {}
    return {k.strip().lower() for k in str(p.get("grain_key") or "").split(",") if k.strip()}


async def _readers(db: AsyncSession, table_entity_id: str) -> Set[str]:
    rels = (await db.execute(select(DiscoveredRelation).where(
        DiscoveredRelation.status != "contradicted",
        or_(DiscoveredRelation.source_entity_id == table_entity_id,
            DiscoveredRelation.target_entity_id == table_entity_id),
    ))).scalars().all()
    out = set()
    for r in rels:
        canonical, flip, _ = canonical_relation(r.relation_type)
        src, dst = (r.target_entity_id, r.source_entity_id) if flip else (r.source_entity_id, r.target_entity_id)
        if canonical == "READS_TABLE" and dst == table_entity_id and src.startswith("task:"):
            out.add(src)
    return out


async def _lineage_linked(db: AsyncSession, a: str, b: str) -> Optional[str]:
    edge = (await db.execute(select(LineageEdge).where(
        LineageEdge.source_type == "TABLE",
        or_((LineageEdge.source_entity_id == a) & (LineageEdge.target_entity_id == b),
            (LineageEdge.source_entity_id == b) & (LineageEdge.target_entity_id == a)),
    ).limit(1))).scalars().first()
    if not edge:
        return None
    return f"{edge.source_entity_id.split(':')[-1]} feeds {edge.target_entity_id.split(':')[-1]} (Databricks lineage)"


def _sql(a_full: str, b_full: str, keys: List[str]) -> str:
    q = lambda f: ".".join(f"`{p}`" for p in f.split("."))  # noqa: E731
    on = "\n  AND ".join(f"a.{k} = b.{k}" for k in keys)
    return f"SELECT a.*, b.*\nFROM {q(a_full)} AS a\nJOIN {q(b_full)} AS b\n  ON {on}\nLIMIT 100"


async def join_path(db: AsyncSession, a_id: str, b_id: str) -> Dict[str, Any]:
    a, b = await _table(db, a_id), await _table(db, b_id)
    if not a or not b:
        missing = a_id if not a else b_id
        return {"error": f"{missing} is not a known table. Use find_data() to find its entity_id."}
    cols_a, cols_b = await _columns(db, a.id), await _columns(db, b.id)
    lower_b = {n.lower(): (n, t) for n, t in cols_b.items()}
    shared = [(n, t, lower_b[n.lower()][1]) for n, t in cols_a.items() if n.lower() in lower_b]
    grain_a, grain_b = await _grain(db, a_id), await _grain(db, b_id)
    keys = score_shared(shared, grain_a, grain_b)

    evidence = []
    co_used = (await _readers(db, a_id)) & (await _readers(db, b_id))
    if co_used:
        evidence.append("Read together by task(s): " + ", ".join(sorted(t.split(":")[-1] for t in co_used)))
    lineage = await _lineage_linked(db, a_id, b_id)
    if lineage:
        evidence.append(lineage)

    result: Dict[str, Any] = {"from": a_id, "to": b_id, "evidence": evidence}
    if keys:
        best = [k["column"] for k in keys if k["score"] >= keys[0]["score"] - 1][:3]
        result.update({
            "direct": True,
            "keys": keys[:6],
            "recommended_keys": best,
            "example_sql": _sql(a.full_name, b.full_name, best),
            "confidence": "high" if (co_used or lineage) and keys[0]["score"] >= 4 else
                          "medium" if keys[0]["score"] >= 3 else "low",
            "caution": ("Check the grain of both sides: joining a line-level fact to a table at a coarser "
                        "grain on a partial key repeats rows."),
        })
        return result

    # No shared key: look for a bridge that shares a key with each side.
    key_a = {n.lower() for n in cols_a if is_key_like(n)}
    key_b = {n.lower() for n in cols_b if is_key_like(n)}
    bridges = []
    if key_a and key_b:
        rows = (await db.execute(
            select(Column.table_id, func.lower(Column.name))
            .where(func.lower(Column.name).in_(key_a | key_b), Column.table_id.not_in([a.id, b.id]))
        )).all()
        by_table: Dict[Any, Set[str]] = {}
        for table_id, name in rows:
            by_table.setdefault(table_id, set()).add(name)
        candidates = [(tid, names & key_a, names & key_b) for tid, names in by_table.items()
                      if names & key_a and names & key_b]
        candidates.sort(key=lambda c: -(len(c[1]) + len(c[2])))
        for tid, ka, kb in candidates[:3]:
            t = (await db.execute(select(Table).where(Table.id == tid))).scalars().first()
            if t:
                bridges.append({"via": t.entity_id, "via_name": t.full_name,
                                "from_keys": sorted(ka), "to_keys": sorted(kb)})
    result.update({
        "direct": False,
        "bridges": bridges,
        "note": ("No shared key column. " + ("Join through one of the bridge tables." if bridges else
                 "No bridge table found either — these tables may not be meant to join.")),
        "confidence": "low",
    })
    return result


async def suggest_joins(db: AsyncSession, entity_id: str, *, limit: int = 5) -> Dict[str, Any]:
    """Tables this one most plausibly joins to, by shared keys and co-use."""
    table = await _table(db, entity_id)
    if not table:
        return {"candidates": []}
    cols = await _columns(db, table.id)
    grain = await _grain(db, entity_id)
    keys = {n.lower(): t for n, t in cols.items() if is_key_like(n) or n.lower() in grain}
    if not keys:
        return {"candidates": []}
    rows = (await db.execute(
        select(Column.table_id, Column.name, Column.data_type)
        .where(func.lower(Column.name).in_(list(keys)), Column.table_id != table.id)
    )).all()
    by_table: Dict[Any, List[Tuple[str, str]]] = {}
    for tid, name, dtype in rows:
        by_table.setdefault(tid, []).append((name, dtype))
    # Tables this one is actually combined with — by lineage, in either
    # direction — are far likelier join partners than look-alikes elsewhere.
    lineage_ids = set()
    for src, dst in (await db.execute(select(LineageEdge.source_entity_id, LineageEdge.target_entity_id).where(
        LineageEdge.source_type == "TABLE",
        or_(LineageEdge.source_entity_id == entity_id, LineageEdge.target_entity_id == entity_id),
    ))).all():
        lineage_ids.add(dst if src == entity_id else src)
    related = {tid for tid, in (await db.execute(
        select(Table.id).where(Table.entity_id.in_(lineage_ids))
    )).all()} if lineage_ids else set()
    ranked = []
    for tid, shared in by_table.items():
        compatible = [n for n, t in shared if type_family(t) == type_family(keys[n.lower()])]
        score = 3 * sum(1 for n in compatible if n.lower() in grain) + 2 * len(compatible) + len(shared)
        if tid in related:
            score += 20
        ranked.append((score, tid, compatible or [n for n, _ in shared]))
    ranked.sort(key=lambda r: -r[0])
    out = []
    for score, tid, shared in ranked[: limit * 2]:
        t = (await db.execute(select(Table.entity_id, Table.full_name).where(Table.id == tid))).first()
        if t:
            out.append({"entity_id": t[0], "name": t[1], "on": sorted(shared)[:4], "strength": score,
                        "evidence": "lineage-connected, shared keys" if tid in related else "shared key columns"})
        if len(out) >= limit:
            break
    return {"candidates": out}
