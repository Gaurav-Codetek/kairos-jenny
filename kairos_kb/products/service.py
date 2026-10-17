"""Data products, one connection (warehouse) at a time.

A data product consolidates one business concept — Sales, Delivery performance —
from a warehouse into a single unit with its own interface, the way Nextdata OS
describes autonomous data products, but without replacing any pipeline:

  identity       name, domain, description, purpose
  input ports    the warehouse tables that feed the concept, picked by the LLM from
                 the enriched map, each with its role and the columns it must keep
  semantic model metrics defined once, dimensions, entities, glossary
  output ports   query (metrics by dimensions, no table names), domain tools, MCP
  contracts      schema, grain, pipeline, freshness, metric, reconcile — by code
  supply chain   everything upstream of the inputs, in lanes
  policies       read-only, personal columns masked, the agent's own permissions

Build: tables (code) → inputs (LLM) → model (LLM) → checks (code, and on the
platform) → supply chain and contracts (code) → stored as a draft.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.context.documents import load_profile
from kairos_kb.models.context import AgentActivity
from kairos_kb.models.data_product import DataProduct
from kairos_kb.models.entity_profile import EntityProfile
from kairos_kb.models.workspace import Workspace
from kairos_kb.products import contracts as contract_checks
from kairos_kb.products.bundle import LANES, _table_member, lane_from_classification
from kairos_kb.products.semantic import QueryError, compile_query

MAX_SELECTION_TABLES = 90
PRODUCT_TOOLS = ("get_data_product", "query_data_product")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:120] or "product"


async def _unique_slug(db: AsyncSession, workspace_id: uuid.UUID, name: str, own: Optional[uuid.UUID]) -> str:
    base = slugify(name)
    slug, n = base, 2
    while True:
        hit = (await db.execute(select(DataProduct.id).where(
            DataProduct.workspace_id == workspace_id, DataProduct.slug == slug))).scalar()
        if hit is None or hit == own:
            return slug
        slug, n = f"{base}-{n}", n + 1


async def enriched_tables(db: AsyncSession, workspace: Workspace) -> List[Dict[str, Any]]:
    """Every enriched table of a connection, with its profile: what a product can be built from."""
    ids = [r[0] for r in (await db.execute(select(EntityProfile.entity_id).where(
        EntityProfile.workspace_id == workspace.id, EntityProfile.kind == "table")
        .order_by(EntityProfile.entity_id))).all()]
    out = []
    for eid in ids:
        profile = await load_profile(db, eid)
        cls = (profile or {}).get("classification") or {}
        lane = (lane_from_classification(cls.get("role"), cls.get("layer"), by_role=True)
                if cls.get("status") == "ok" else None) or "core"
        m = await _table_member(db, eid, lane, profile, False)
        if m:
            out.append(m)
    return out


async def _shortlist(db: AsyncSession, workspace: Workspace, tables: List[Dict[str, Any]], concept: str,
                     intent: str, pins: List[str]) -> List[Dict[str, Any]]:
    """For a large warehouse, the tables most related to the concept (meaning search), plus any pinned."""
    if len(tables) <= MAX_SELECTION_TABLES:
        return tables
    from kairos_kb.context.access import AgentIdentity
    from kairos_kb.context.search import find_data

    identity = AgentIdentity(agent_id=None, name="data products", workspace_ids=frozenset({str(workspace.id)}),
                             workspace_names=frozenset({workspace.name}))
    hits = await find_data(db, f"{concept}. {intent}".strip(), identity, kinds=["table"], limit=MAX_SELECTION_TABLES)
    ranked = [h["entity_id"] for h in hits.get("results") or []]
    keep = set(ranked[:MAX_SELECTION_TABLES]) | set(pins)
    return [t for t in tables if t["entity_id"] in keep] or tables[:MAX_SELECTION_TABLES]


def _norm(s: str) -> str:
    return re.sub(r"[`\"\s]", "", str(s or "")).upper()


def _snake(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_") or "x"


async def owned_elsewhere(db: AsyncSession, workspace: Workspace, own: Optional[uuid.UUID],
                         not_owners: Optional[set] = None) -> str:
    """The metrics other products of this connection already define: one owner per metric.

    not_owners: products about to be rebuilt in the same run — their current metrics are not a claim.
    """
    lines = []
    for p in (await db.execute(select(DataProduct).where(DataProduct.workspace_id == workspace.id)
                               .order_by(DataProduct.name))).scalars():
        if (own is not None and p.id == own) or p.id in (not_owners or set()):
            continue
        for m in ((p.spec or {}).get("model") or {}).get("metrics") or []:
            lines.append(f"- {p.name}: {m['name']} — {(m.get('description') or '')[:140]}")
    return "\n".join(lines)


async def build(db: AsyncSession, workspace: Workspace, *, concept: str, intent: str = "",
                pins: Optional[List[str]] = None, product: Optional[DataProduct] = None,
                step: Optional[Callable[[str], None]] = None, origin: str = "manual",
                not_owners: Optional[set] = None) -> DataProduct:
    from kairos_kb.connectors.factory import connector_for, sql_dialect
    from kairos_kb.llm.provider import model_name
    from kairos_kb.products.bundle import assemble
    from kairos_kb.products.designer import (
        design_model, repair_metrics, select_inputs, validate_model, verify_on_platform,
    )

    step = step or (lambda _s: None)
    pins = list(dict.fromkeys(pins or []))
    step("map")
    tables = await enriched_tables(db, workspace)
    if not tables:
        raise ValueError(f"{workspace.name} has no enriched tables yet. Enrich it first.")
    shortlist = await _shortlist(db, workspace, tables, concept, intent, pins)
    owned = await owned_elsewhere(db, workspace, product.id if product else None, not_owners)

    # ── inputs: the LLM picks the tables that belong to the concept; pins always stay ──
    step("inputs")
    selection = await select_inputs(concept, intent, shortlist, owned)
    by_name = {_norm(t["full_name"]): t for t in tables}
    picked: Dict[str, Dict[str, Any]] = {}
    for p in selection.inputs:
        t = by_name.get(_norm(p.table))
        if t and t["entity_id"] not in picked:
            picked[t["entity_id"]] = {**t, "port_role": p.role, "why": p.why}
    for eid in pins:
        t = next((x for x in tables if x["entity_id"] == eid), None)
        if t and eid not in picked:
            picked[eid] = {**t, "port_role": "aggregate" if t["lane"] == "mart" else "fact", "why": "Pinned by a person."}
    inputs = list(picked.values())
    if not inputs:
        raise ValueError(f"Nothing in {workspace.name} matches '{concept}'. Try a different concept or intent.")

    # ── the semantic model, checked statically, then on the platform; rejected metrics get one repair ──
    step("model")
    connector = connector_for(workspace)
    dialect = sql_dialect(connector)
    designed = await design_model(concept, intent, inputs, dialect, owned)
    step("verify")
    model, dropped = validate_model(designed, inputs)
    dropped += await verify_on_platform(model, connector)
    failures = [d for d in dropped if d["kind"] == "metric" and "does not compile" in d["reason"]]
    repaired: List[str] = []
    if failures:
        step("repair")
        fixed = await repair_metrics(designed, failures, inputs, dialect)
        if fixed:
            names = {f["item"] for f in failures}
            designed.metrics = [m for m in designed.metrics if _snake(m.name) not in names] + fixed
            model, dropped = validate_model(designed, inputs)
            dropped += await verify_on_platform(model, connector)
            repaired = sorted(names - {d["item"] for d in dropped if d["kind"] == "metric"})
    if not model["metrics"]:
        raise ValueError("No metric of the proposed model holds against the warehouse; nothing to serve.")

    # ── supply chain upstream of the inputs ──
    step("supply")
    bundle = await assemble(db, workspace.id, [t["entity_id"] for t in inputs])
    roles = {t["entity_id"]: t for t in inputs}
    for m in bundle["members"]:
        if m["entity_id"] in roles:
            m["port_role"] = roles[m["entity_id"]]["port_role"]

    name = (concept.strip() or selection.name).strip()[:255]
    slug = await _unique_slug(db, workspace.id, name, product.id if product else None)
    settings = ((product.spec or {}).get("settings") or {}) if product is not None else {}
    if product is None:
        product = DataProduct(workspace_id=workspace.id, seeds=[], name=name, slug=slug)
        db.add(product)
    product.name, product.slug = name, slug
    product.domain = (selection.domain or "")[:255] or None
    product.description = model.get("description")
    product.intent = intent or None
    product.seeds = [t["entity_id"] for t in inputs]
    product.spec = {
        "concept": concept,
        "origin": origin if product is None else ((product.spec or {}).get("origin") or origin),
        "pins": pins,
        "settings": settings,
        "inputs": [{"entity_id": t["entity_id"], "table": t["full_name"], "role": t["port_role"], "why": t["why"],
                    "lane": t["lane"], "grain": t.get("grain"), "trust": t["trust"]} for t in inputs],
        "left_out": [x.model_dump() for x in selection.left_out],
        "model": model,
    }
    product.bundle = bundle
    product.validation = {"dropped": dropped, "repaired": repaired, "dialect": dialect, "live": None, "live_at": None}
    product.model = model_name()
    product.built_at = datetime.now(timezone.utc)
    product.status, product.confirmed_at = "draft", None
    await db.flush()
    return product


# ── contracts and health ─────────────────────────────────────────────


async def contracts_of(db: AsyncSession, p: DataProduct) -> Dict[str, Any]:
    spec, bundle = p.spec or {}, p.bundle or {}
    seeds = set(p.seeds or [])
    inputs = [m for m in bundle.get("members") or [] if m["entity_id"] in seeds]
    slo = (spec.get("settings") or {}).get("freshness_slo_hours")
    checks = await contract_checks.map_checks(db, inputs, spec.get("model") or {}, bundle.get("pipelines") or [], slo)
    allc = checks + ((p.validation or {}).get("live") or [])
    return {"contracts": allc, "health": contract_checks.health(allc), "live_at": (p.validation or {}).get("live_at"),
            "freshness_slo_hours": slo}


async def check_live(db: AsyncSession, p: DataProduct, workspace: Workspace) -> Dict[str, Any]:
    from kairos_kb.connectors.factory import connector_for

    live = await contract_checks.live_checks((p.spec or {}).get("model") or {}, connector_for(workspace))
    p.validation = {**(p.validation or {}), "live": live, "live_at": datetime.now(timezone.utc).isoformat()}
    await db.flush()
    return await contracts_of(db, p)


# ── the query port ───────────────────────────────────────────────────


async def query(db: AsyncSession, p: DataProduct, identity, *, metrics: List[str], by: Optional[List[str]] = None,
                filters: Optional[List[Dict[str, Any]]] = None, order: str = "", limit: int = 100) -> Dict[str, Any]:
    """Answer from the product: compile to SQL, then run it through the read-only, masking SQL guard."""
    from kairos_kb.context.query import run_sql

    model = (p.spec or {}).get("model") or {}
    try:
        compiled = compile_query(model, metrics, by, filters, order)
    except QueryError as exc:
        return {"error": str(exc), "metrics": [m["name"] for m in model.get("metrics") or []],
                "dimensions": [d["name"] for d in model.get("dimensions") or []]}
    result = await run_sql(db, identity, compiled["sql"], limit)
    return {"product": p.name, "source": compiled["source"], "table": compiled["table"], "sql": compiled["sql"],
            "notes": compiled["notes"], **result}


async def run_tool(db: AsyncSession, p: DataProduct, identity, tool: str,
                   filters: Optional[List[Dict[str, Any]]] = None, limit: int = 100) -> Dict[str, Any]:
    t = next((x for x in ((p.spec or {}).get("model") or {}).get("tools") or [] if x["name"] == tool), None)
    if t is None:
        return {"error": f"No tool '{tool}' on {p.name}.",
                "tools": [x["name"] for x in ((p.spec or {}).get("model") or {}).get("tools") or []]}
    return await query(db, p, identity, metrics=t["metrics"], by=t["by"], filters=filters, limit=limit)


# ── views ────────────────────────────────────────────────────────────


async def consumers(db: AsyncSession, p: DataProduct) -> List[Dict[str, Any]]:
    """Agents that used this product, from the audit log."""
    refs = {p.slug, p.name.lower(), str(p.id)}
    rows = (await db.execute(
        select(AgentActivity.agent_name, AgentActivity.channel, AgentActivity.arguments, AgentActivity.created_at)
        .where(AgentActivity.tool.in_(PRODUCT_TOOLS)).order_by(AgentActivity.created_at.desc()).limit(500))).all()
    seen: Dict[tuple, Dict[str, Any]] = {}
    for agent, channel, args, at in rows:
        ref = str((args or {}).get("product") or "").strip().lower()
        if ref not in refs and slugify(ref) != p.slug:
            continue
        row = seen.setdefault((agent, channel), {"agent": agent, "channel": channel, "calls": 0,
                                                 "last": at.isoformat() if at else None})
        row["calls"] += 1
    return list(seen.values())


def summary(p: DataProduct, workspace_name: str = "", health: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    spec = p.spec or {}
    model = spec.get("model") or {}
    return {
        "id": str(p.id),
        "workspace_id": str(p.workspace_id),
        "workspace": workspace_name,
        "name": p.name,
        "slug": p.slug,
        "domain": p.domain,
        "description": p.description,
        "status": p.status,
        "intent": p.intent,
        "inputs": spec.get("inputs") or [],
        "entities": [e.get("name") for e in model.get("entities") or []],
        "dimensions": [{"name": d["name"], "label": d.get("label"), "table": d.get("table")}
                       for d in model.get("dimensions") or []],
        "metrics": [{"name": m["name"], "label": m.get("label")} for m in model.get("metrics") or []],
        "tools": [t["name"] for t in model.get("tools") or []],
        "health": health,
        "model": p.model,
        "built_at": p.built_at.isoformat() if p.built_at else None,
        "confirmed_at": p.confirmed_at.isoformat() if p.confirmed_at else None,
    }


async def full(db: AsyncSession, p: DataProduct, workspace_name: str = "") -> Dict[str, Any]:
    c = await contracts_of(db, p)
    return {**summary(p, workspace_name, c["health"]), "spec": p.spec, "bundle": p.bundle,
            "validation": p.validation, "contracts": c, "consumers": await consumers(db, p)}


async def for_agent(db: AsyncSession, p: DataProduct, workspace_name: str = "") -> Dict[str, Any]:
    """The product as an agent reads it: how to ask it, what it means, what it promises."""
    spec = p.spec or {}
    model = spec.get("model") or {}
    c = await contracts_of(db, p)
    first = model["metrics"][0]["name"] if model.get("metrics") else None
    dim = next((d["name"] for d in model.get("dimensions") or [] if d.get("type") != "time"), None)
    members = (p.bundle or {}).get("members") or []
    return {
        "product": p.name,
        "id": p.slug,
        "connection": workspace_name,
        "status": p.status + ("" if p.status == "confirmed" else " (built by Kairos, not yet confirmed by a person)"),
        "health": c["health"]["status"],
        "domain": p.domain,
        "description": p.description,
        "purpose": model.get("purpose"),
        "how_to_ask": {
            "query": "query_data_product(product, metrics=[...], by=[...], filters=[{dimension, op, value}]) — "
                     "name metrics and dimensions, never tables. Time dimensions take a grain: 'order_date:month'.",
            "example": {"product": p.slug, "metrics": [first] if first else [], "by": [dim] if dim else []},
            "tools": "or run a named tool: query_data_product(product, tool='<name>').",
        },
        "rules": model.get("agent_guidance"),
        "metrics": [{k: m.get(k) for k in ("name", "label", "description", "unit", "additive", "caveat")}
                    | {"defined_as": m.get("expression"), "computed_from": m.get("base_table"),
                       "fast_path": [s["table"] for s in m.get("shortcuts") or []]}
                    for m in model.get("metrics") or []],
        "dimensions": [{k: d.get(k) for k in ("name", "label", "type", "description")} for d in model.get("dimensions") or []],
        "tools": model.get("tools"),
        "entities": model.get("entities"),
        "glossary": model.get("glossary"),
        "caveats": model.get("caveats"),
        "input_ports": [{"table": i["table"], "role": i["role"], "grain": i.get("grain"), "trust": i.get("trust")}
                        for i in spec.get("inputs") or []],
        "supply_chain": {lane: [m["full_name"] for m in members if m["lane"] == lane]
                         for lane in LANES if any(m["lane"] == lane for m in members)},
        "contracts": [{k: x.get(k) for k in ("contract", "port", "status", "detail")} for x in c["contracts"]],
        "policies": ["read-only", "personal-data columns masked", "runs with the calling agent's own permissions"],
    }


async def find_product(db: AsyncSession, ref: str, workspace_ids: Optional[List[uuid.UUID]] = None) -> Optional[DataProduct]:
    """A product by id, slug or name (case-insensitive), within the given connections."""
    q = select(DataProduct)
    if workspace_ids is not None:
        q = q.where(DataProduct.workspace_id.in_(workspace_ids))
    try:
        hit = (await db.execute(q.where(DataProduct.id == uuid.UUID(str(ref))))).scalars().first()
        if hit:
            return hit
    except ValueError:
        pass
    rows = (await db.execute(q)).scalars().all()
    ref_l = str(ref).strip().lower()
    return next((p for p in rows if p.slug == slugify(ref) or p.name.lower() == ref_l), None)
