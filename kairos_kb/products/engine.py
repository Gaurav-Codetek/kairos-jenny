"""The data product engine: every data product a warehouse holds, found from how its data flows.

  1. flow      code reads the map: which curated facts feed which marts, which dimensions
               they join (lineage, or a shared key column), and which tables are
               operational (logs, config, scratch) and serve no product.
  2. plan      the LLM proposes the business products a company would recognise in that
               flow — one concept each, every measure owned by exactly one product. A mart
               whose columns serve two concepts is split between them.
  3. build     each proposal is built in turn with the same builder a person uses; each
               build sees the metrics earlier products own and does not redefine them.

Products that already exist are left alone unless asked to rebuild them. A person can still
build any product by hand.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.models.discovered import DiscoveredRelation
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.models.workspace import Workspace

OPERATIONAL_ROLES = {"LOG_AUDIT", "CONFIG_CONTROL", "PROFILING_SNAPSHOT", "SCRATCH_TEST"}
NUMERIC = re.compile(r"NUMBER|DECIMAL|NUMERIC|INT|FLOAT|DOUBLE|REAL", re.I)
KEYISH = re.compile(r"(_ID|_KEY|_CODE)$", re.I)


def _short(full_name: str) -> str:
    return full_name.split(".")[-1]


async def flow_map(db: AsyncSession, workspace: Workspace) -> Dict[str, Any]:
    """The warehouse as a product designer needs it: facts, marts, dimensions and how they connect."""
    from kairos_kb.products.service import enriched_tables

    tables = await enriched_tables(db, workspace)
    by_id = {t["entity_id"]: t for t in tables}
    ids = list(by_id)
    up: Dict[str, Set[str]] = {t: set() for t in ids}
    if ids:
        for e in (await db.execute(select(LineageEdge).where(
                LineageEdge.source_type == "TABLE", LineageEdge.target_entity_id.in_(ids)))).scalars():
            if e.source_entity_id in by_id and e.source_entity_id != e.target_entity_id:
                up[e.target_entity_id].add(e.source_entity_id)
        for r in (await db.execute(select(DiscoveredRelation).where(
                DiscoveredRelation.status != "contradicted", DiscoveredRelation.relation_type == "FEEDS",
                DiscoveredRelation.target_entity_id.in_(ids)))).scalars():
            if r.source_entity_id in by_id and r.source_entity_id != r.target_entity_id:
                up[r.target_entity_id].add(r.source_entity_id)

    def closure(t: str) -> Set[str]:
        seen, q = set(), deque([t])
        while q:
            for u in up.get(q.popleft(), ()):
                if u not in seen:
                    seen.add(u)
                    q.append(u)
        return seen

    from kairos_kb.products.bundle import assign_lanes, lane_from_classification

    # Landed from a stage or a storage location: that is what makes a table raw. A table with no
    # recorded inputs and no landing (built by a job lineage does not see) is placed by its role.
    landed = {r.target_entity_id for r in (await db.execute(select(DiscoveredRelation).where(
        DiscoveredRelation.status != "contradicted", DiscoveredRelation.target_entity_id.in_(ids),
        DiscoveredRelation.relation_type.in_(("FEEDS", "LOADS_INTO", "WRITES_TABLE"))))).scalars()
        if r.source_entity_id.split(":", 1)[0] in ("stage", "location", "volume", "pipe")} if ids else set()
    classified = {t: lane_from_classification(by_id[t].get("role"), by_id[t].get("layer")) for t in ids}
    for t in ids:
        if classified[t] is None and not up[t]:
            classified[t] = "raw" if t in landed else lane_from_classification(
                by_id[t].get("role"), by_id[t].get("layer"), by_role=True)
    lanes = assign_lanes(ids, classified, up, {t: by_id[t].get("role") for t in ids})
    for t in ids:
        by_id[t]["lane"] = lanes[t]
    role = lambda t: (by_id[t].get("role") or "").upper()  # noqa: E731
    lane = lambda t: by_id[t].get("lane") or "core"  # noqa: E731
    operational = [t for t in ids if role(t) in OPERATIONAL_ROLES]
    usable = [t for t in ids if t not in operational]
    facts = [t for t in usable if role(t) == "FACT_EVENT" and lane(t) in ("core", "mart")] or \
            [t for t in usable if role(t) == "FACT_EVENT" and lane(t) != "raw"]
    marts = [t for t in usable if lane(t) == "mart" and t not in facts and role(t) != "DIMENSION_MASTER"]
    dims = [t for t in usable if role(t) in ("DIMENSION_MASTER", "MAPPING_CROSSWALK") and lane(t) in ("core", "mart")]

    def keys(t: str) -> Set[str]:
        return {c["name"].upper() for c in by_id[t].get("columns") or [] if KEYISH.search(c["name"])}

    out_facts, out_marts = [], []
    for f in facts:
        fed = [m for m in marts if f in closure(m)]
        joined = sorted({d for d in dims if keys(d) & keys(f)} | {d for m in fed for d in closure(m) if d in dims})
        out_facts.append({"table": f, "feeds": fed, "dimensions": joined})
    for m in marts:
        c = closure(m)
        out_marts.append({"table": m, "built_from": [f for f in facts if f in c], "dimensions": [d for d in dims if d in c]})
    covered = set(facts) | set(marts) | set(dims)
    return {
        "tables": by_id,
        "facts": out_facts,
        "marts": out_marts,
        "dimensions": dims,
        "operational": operational,
        "other": [t for t in usable if t not in covered and lane(t) not in ("raw", "staging")],
    }


# ── the plan ─────────────────────────────────────────────────────────


class Proposal(BaseModel):
    concept: str = Field(description="Business name of the product, e.g. 'Sales'.")
    intent: str = Field(description="What it covers, in business words: the metrics it owns (orders, GMV, AOV, "
                                    "cancellation rate …) and the slices it offers (city, day, restaurant …), one or "
                                    "two sentences. Name the metrics it leaves to a neighbour. Not a list of columns.")
    tables: List[str] = Field(description="The central tables (facts and marts) it is built on, exactly as listed.")
    rationale: str = Field(description="Why this is one product: the flow and the measures that make it.")


class NotCovered(BaseModel):
    table: str
    why: str


class Plan(BaseModel):
    products: List[Proposal]
    not_covered: List[NotCovered] = Field(default_factory=list)


PLAN_SYSTEM = """You design the data products of a warehouse: the business concepts a company
would recognise (Sales, Delivery performance, Customer, Inventory …), each served as one unit.
You are given how its data flows: curated facts, the marts built from them, the dimensions they
join, and every measure with its meaning.
- Propose every product the data supports, 2 to 8 of them, named in business terms.
- One concept per product. Every measure belongs to exactly ONE product; when a mart holds
  measures of two concepts (revenue and delivery time in one table), split it: each product
  takes its own measures, and its intent names the measures it leaves to the other.
- A product is built on facts and marts (its central tables); dimensions are shared freely.
- Describe each product's metrics as the business tracks them — the measures its marts compute are
  the best evidence (GMV, AOV, orders, cancellation rate) — not as raw column names.
- Do not propose products for operational tables (logs, config, profiling, scratch).
- Do not propose a product that only renames another, or one with no measure of its own.
Use table names exactly as given."""


def _measures(t: Dict[str, Any], limit: int = 30) -> str:
    out = []
    for c in t.get("columns") or []:
        if KEYISH.search(c["name"]) or not (c.get("aggregation") or NUMERIC.search(str(c.get("type") or ""))):
            continue
        out.append(f"{c['name']}" + (f" — {str(c.get('meaning'))[:110]}" if c.get("meaning") else ""))
        if len(out) >= limit:
            break
    return "; ".join(out) or "-"


def plan_brief(flow: Dict[str, Any], existing: List[str]) -> str:
    t = flow["tables"]
    lines = ["CURATED FACTS:"]
    for f in flow["facts"]:
        x = t[f["table"]]
        lines.append(f"- {x['full_name']} · grain: {(x.get('grain') or '-')[:160]}\n  measures: {_measures(x)}"
                     f"\n  feeds marts: {', '.join(_short(t[m]['full_name']) for m in f['feeds']) or 'none'}"
                     f"\n  joins dimensions: {', '.join(_short(t[d]['full_name']) for d in f['dimensions']) or 'none'}")
    lines.append("\nMARTS:")
    for m in flow["marts"]:
        x = t[m["table"]]
        lines.append(f"- {x['full_name']} · grain: {(x.get('grain') or '-')[:160]}\n  measures: {_measures(x)}"
                     f"\n  built from: {', '.join(_short(t[f]['full_name']) for f in m['built_from']) or 'unknown'}")
    lines.append("\nDIMENSIONS: " + ", ".join(t[d]["full_name"] for d in flow["dimensions"]))
    if flow["other"]:
        lines.append("OTHER CURATED TABLES: " + ", ".join(
            f"{t[o]['full_name']} ({(t[o].get('role') or 'unclassified').lower()})" for o in flow["other"]))
    if flow["operational"]:
        lines.append("OPERATIONAL (no product): " + ", ".join(t[o]["full_name"] for o in flow["operational"]))
    if existing:
        lines.append("\nPRODUCTS THAT ALREADY EXIST (propose them again under the same name if they belong, so they "
                     "are kept; do not duplicate them): " + ", ".join(existing))
    return "\n".join(lines)


async def propose(flow: Dict[str, Any], existing: List[str]) -> Plan:
    from kairos_kb.llm.provider import chat_model

    llm = chat_model()
    if llm is None:
        raise RuntimeError("No LLM is configured; the engine cannot propose products.")
    if not flow["facts"] and not flow["marts"]:
        raise ValueError("No curated fact or mart is enriched on this connection yet; enrich it first.")
    return await llm.with_structured_output(Plan).ainvoke(
        [("system", PLAN_SYSTEM), ("human", plan_brief(flow, existing))])


def resolve_tables(names: List[str], tables: Dict[str, Dict[str, Any]]) -> List[str]:
    """Proposed table names → entity ids (full name, or an unambiguous short name)."""
    norm = lambda s: re.sub(r"[`\"\s]", "", str(s or "")).upper()  # noqa: E731
    full = {norm(t["full_name"]): eid for eid, t in tables.items()}
    short: Dict[str, Optional[str]] = {}
    for eid, t in tables.items():
        k = norm(t["full_name"]).split(".")[-1]
        short[k] = None if k in short else eid
    out = []
    for n in names:
        eid = full.get(norm(n)) or short.get(norm(n).split(".")[-1])
        if eid and eid not in out:
            out.append(eid)
    return out
