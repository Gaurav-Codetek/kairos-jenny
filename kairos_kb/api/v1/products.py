"""Data product endpoints — per connection: build a product from a business concept, query it, check it."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.api.v1.context import _audit, agent_identity
from kairos_kb.context.access import AgentIdentity
from kairos_kb.db.engine import async_session_factory, get_db
from kairos_kb.exceptions import KairosException, NotFoundError
from kairos_kb.models.data_product import DataProduct
from kairos_kb.models.workspace import Workspace
from kairos_kb.products import mesh as product_mesh
from kairos_kb.products import service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/products", tags=["Data products"])


class CreateProduct(BaseModel):
    workspace_id: uuid.UUID
    concept: str = Field(min_length=1, description="The business concept, e.g. 'Sales'.")
    intent: str = Field("", description="What the product is for, in the person's words.")
    pins: List[str] = Field(default_factory=list, description="Tables that must be inputs (entity ids).")


class RebuildProduct(BaseModel):
    concept: Optional[str] = None
    intent: Optional[str] = None
    pins: Optional[List[str]] = None


class UpdateProduct(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(draft|confirmed)$")
    freshness_slo_hours: Optional[float] = Field(None, ge=0, description="0 clears the SLO.")


class QueryProduct(BaseModel):
    metrics: List[str] = Field(default_factory=list)
    by: List[str] = Field(default_factory=list)
    filters: List[Dict[str, Any]] = Field(default_factory=list)
    order: str = ""
    tool: str = ""
    limit: int = Field(100, ge=1, le=1000)


async def _publish(db: AsyncSession, product: DataProduct, workspace_name: str) -> List[str]:
    """Put the product into the map (entity, links to its inputs); returns the documents to refresh."""
    health = (await service.contracts_of(db, product))["health"]["status"]
    return await product_mesh.publish(db, product, workspace_name, health)


async def _workspace(db: AsyncSession, workspace_id: uuid.UUID) -> Workspace:
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise NotFoundError("Workspace", str(workspace_id))
    return ws


async def _get(db: AsyncSession, product_id: uuid.UUID) -> DataProduct:
    p = await db.get(DataProduct, product_id)
    if not p:
        raise NotFoundError("Data product", str(product_id))
    return p


# ── builds run in the background; the screen follows their steps ──

STEPS = {
    "map": "Reading the connection's enriched map",
    "inputs": "Picking the tables that belong to the concept",
    "model": "Defining metrics, dimensions and tools",
    "verify": "Compiling every metric and join on the platform",
    "repair": "Repairing what the platform rejected",
    "supply": "Tracing the supply chain and writing contracts",
}
_BUILDS: Dict[str, Dict[str, Any]] = {}


def _running_for(workspace_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    return next((b for b in _BUILDS.values() if b["workspace_id"] == str(workspace_id) and b["status"] == "running"), None)


async def _run_build(build_id: str, workspace_id: uuid.UUID, concept: str, intent: str, pins: List[str],
                     product_id: Optional[uuid.UUID]) -> None:
    b = _BUILDS[build_id]

    def step(key: str) -> None:
        b["steps"].append({"key": key, "label": STEPS.get(key, key), "at": datetime.now(timezone.utc).isoformat()})

    try:
        async with async_session_factory() as db:
            ws = await db.get(Workspace, workspace_id)
            product = await db.get(DataProduct, product_id) if product_id else None
            product = await service.build(db, ws, concept=concept, intent=intent, pins=pins, product=product,
                                          step=step)
            touched = await _publish(db, product, ws.name)
            await db.commit()
            await product_mesh.reindex(touched)
            b.update(status="completed", product_id=str(product.id))
    except Exception as exc:  # noqa: BLE001 — shown on the screen
        logger.exception("Data product build failed")
        b.update(status="failed", error=str(exc)[:600])
    finally:
        b["finished_at"] = datetime.now(timezone.utc).isoformat()


def _start(workspace_id: uuid.UUID, concept: str, intent: str, pins: List[str],
           product_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    if _busy(workspace_id):
        raise KairosException("A data product is already being built for this connection; wait for it to finish.",
                              status_code=409)
    build_id = str(uuid.uuid4())
    _BUILDS[build_id] = {"id": build_id, "workspace_id": str(workspace_id), "concept": concept, "status": "running",
                         "steps": [], "product_id": str(product_id) if product_id else None, "error": None,
                         "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None}
    asyncio.create_task(_run_build(build_id, workspace_id, concept, intent, pins, product_id))
    return _BUILDS[build_id]


@router.get("/builds/{build_id}")
async def get_build(build_id: str):
    b = _BUILDS.get(build_id)
    if not b:
        raise NotFoundError("Build", build_id)
    return b


# ── the engine: every product the warehouse's data flow supports ─────

_ENGINES: Dict[str, Dict[str, Any]] = {}


class RunEngine(BaseModel):
    workspace_id: uuid.UUID
    rebuild_existing: bool = Field(False, description="Rebuild products that already exist instead of keeping them.")


def _busy(workspace_id: uuid.UUID) -> bool:
    return bool(_running_for(workspace_id)) or any(
        e["workspace_id"] == str(workspace_id) and e["status"] == "running" for e in _ENGINES.values())


async def _run_engine(job_id: str, workspace_id: uuid.UUID, rebuild_existing: bool) -> None:
    from kairos_kb.products.engine import flow_map, propose, resolve_tables

    job = _ENGINES[job_id]
    try:
        async with async_session_factory() as db:
            ws = await db.get(Workspace, workspace_id)
            job["phase"] = "flow"
            flow = await flow_map(db, ws)
            t = flow["tables"]
            job["flow"] = {
                "facts": [t[f["table"]]["full_name"] for f in flow["facts"]],
                "marts": [t[m["table"]]["full_name"] for m in flow["marts"]],
                "dimensions": [t[d]["full_name"] for d in flow["dimensions"]],
                "operational": [t[o]["full_name"] for o in flow["operational"]],
            }
            existing = {service.slugify(p.name): p for p in (await db.execute(
                select(DataProduct).where(DataProduct.workspace_id == ws.id))).scalars()}
            job["phase"] = "plan"
            plan = await propose(flow, [p.name for p in existing.values()])
            job["proposals"] = [{"concept": p.concept, "intent": p.intent, "rationale": p.rationale,
                                 "tables": [t[e]["full_name"] for e in resolve_tables(p.tables, t)],
                                 "pins": resolve_tables(p.tables, t), "status": "queued", "product_id": None,
                                 "error": None, "steps": []} for p in plan.products]
            job["not_covered"] = [x.model_dump() for x in plan.not_covered]
            existing_ids = {slug: p.id for slug, p in existing.items()}

        job["phase"] = "build"
        # Products this run will rebuild do not own their current metrics: the plan reassigns them.
        pending = {existing_ids[service.slugify(p["concept"])] for p in job["proposals"]
                   if rebuild_existing and service.slugify(p["concept"]) in existing_ids}
        for prop in job["proposals"]:
            slug = service.slugify(prop["concept"])
            if slug in existing_ids and not rebuild_existing:
                prop.update(status="kept", product_id=str(existing_ids[slug]))
                continue
            prop["status"] = "building"

            def step(key: str, prop=prop) -> None:
                prop["steps"].append({"key": key, "label": STEPS.get(key, key)})

            try:
                # A session per product, committed: the next build sees this one's metrics as owned.
                async with async_session_factory() as db:
                    ws = await db.get(Workspace, workspace_id)
                    current = await db.get(DataProduct, existing_ids[slug]) if slug in existing_ids else None
                    product = await service.build(db, ws, concept=prop["concept"], intent=prop["intent"],
                                                  pins=prop["pins"], product=current, step=step, origin="engine",
                                                  not_owners=pending - ({current.id} if current else set()))
                    touched = await _publish(db, product, ws.name)
                    await db.commit()
                    await product_mesh.reindex(touched)
                    prop.update(status="built", product_id=str(product.id))
                pending.discard(existing_ids.get(slug))
            except Exception as exc:  # noqa: BLE001 — one product failing does not stop the others
                logger.exception("Engine build failed for %s", prop["concept"])
                prop.update(status="failed", error=str(exc)[:400])
        job.update(status="completed", phase="done")
    except Exception as exc:  # noqa: BLE001 — shown on the screen
        logger.exception("Data product engine failed")
        job.update(status="failed", error=str(exc)[:600])
    finally:
        job["finished_at"] = datetime.now(timezone.utc).isoformat()


@router.post("/engine", status_code=202)
async def run_engine(body: RunEngine, db: AsyncSession = Depends(get_db)):
    """Discover and build every data product the connection's data flow supports (several minutes).

    Poll GET /products/engine/{id}: the flow it read, the products it proposed, and each one's build.
    """
    ws = await _workspace(db, body.workspace_id)
    if _busy(ws.id):
        raise KairosException("Data products are already being built for this connection; wait for it to finish.",
                              status_code=409)
    job_id = str(uuid.uuid4())
    _ENGINES[job_id] = {"id": job_id, "workspace_id": str(ws.id), "status": "running", "phase": "flow",
                        "flow": None, "proposals": [], "not_covered": [], "error": None,
                        "rebuild_existing": body.rebuild_existing,
                        "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None}
    asyncio.create_task(_run_engine(job_id, ws.id, body.rebuild_existing))
    return _ENGINES[job_id]


@router.get("/engine/latest")
async def latest_engine(workspace_id: uuid.UUID):
    """The connection's most recent engine run, if any (so the screen can pick it up again)."""
    runs = [e for e in _ENGINES.values() if e["workspace_id"] == str(workspace_id)]
    return max(runs, key=lambda e: e["started_at"]) if runs else None


@router.get("/engine/{job_id}")
async def get_engine(job_id: str):
    job = _ENGINES.get(job_id)
    if not job:
        raise NotFoundError("Engine run", job_id)
    return job


@router.get("")
async def list_products(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """The connection's data products, with their inputs, semantics and health: what the graph draws."""
    ws = await _workspace(db, workspace_id)
    rows = (await db.execute(select(DataProduct).where(DataProduct.workspace_id == ws.id)
                             .order_by(DataProduct.name))).scalars().all()
    products = []
    for p in rows:
        c = await service.contracts_of(db, p)
        products.append({**service.summary(p, ws.name, c["health"]), "consumers": await service.consumers(db, p)})
    return {"workspace_id": str(ws.id), "workspace": ws.name, "products": products}


@router.get("/tables")
async def list_tables(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Enriched tables of the connection, for pinning inputs."""
    ws = await _workspace(db, workspace_id)
    tables = await service.enriched_tables(db, ws)
    return {"tables": [{k: t.get(k) for k in ("entity_id", "name", "full_name", "lane", "role", "trust", "grain")}
                       for t in tables]}


@router.post("", status_code=202)
async def create_product(body: CreateProduct, db: AsyncSession = Depends(get_db)):
    """Start building a product for a business concept from the connection's enriched map (one to two minutes).

    Poll GET /products/builds/{id} for its steps; it ends with the product's id.
    """
    ws = await _workspace(db, body.workspace_id)
    return _start(ws.id, body.concept.strip(), body.intent.strip(), body.pins)


@router.get("/{product_id}")
async def get_product(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    p = await _get(db, product_id)
    ws = await _workspace(db, p.workspace_id)
    return await service.full(db, p, ws.name)


@router.get("/{product_id}/agent")
async def get_product_for_agent(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Exactly what an agent receives from get_data_product."""
    p = await _get(db, product_id)
    ws = await _workspace(db, p.workspace_id)
    return await service.for_agent(db, p, ws.name)


@router.post("/{product_id}/query")
async def query_product(product_id: uuid.UUID, body: QueryProduct,
                        identity: AgentIdentity = Depends(agent_identity), db: AsyncSession = Depends(get_db)):
    """The product's query port: metrics by dimensions, compiled to read-only SQL and run on the platform."""
    p = await _get(db, product_id)
    started = time.perf_counter()
    if body.tool:
        result = await service.run_tool(db, p, identity, body.tool, body.filters, body.limit)
    else:
        result = await service.query(db, p, identity, metrics=body.metrics, by=body.by, filters=body.filters,
                                     order=body.order, limit=body.limit)
    await _audit(identity, "query_data_product", {"product": p.slug, **body.model_dump()}, result, started)
    return result


@router.post("/{product_id}/check")
async def check_product(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Run the live contracts on the platform: every metric computes, shortcuts reconcile with the base."""
    p = await _get(db, product_id)
    ws = await _workspace(db, p.workspace_id)
    out = await service.check_live(db, p, ws)
    touched = await product_mesh.publish(db, p, ws.name, out["health"]["status"])
    await db.commit()
    await product_mesh.reindex(touched[:1])
    return out


@router.post("/{product_id}/rebuild", status_code=202)
async def rebuild_product(product_id: uuid.UUID, body: RebuildProduct, db: AsyncSession = Depends(get_db)):
    """Build again from the current map — after a re-enrichment, or with a new intent or pins."""
    p = await _get(db, product_id)
    ws = await _workspace(db, p.workspace_id)
    spec = p.spec or {}
    concept = (body.concept if body.concept is not None else spec.get("concept") or p.name).strip()
    intent = (body.intent if body.intent is not None else p.intent or "").strip()
    pins = body.pins if body.pins is not None else spec.get("pins") or []
    return _start(ws.id, concept, intent, pins, product_id=p.id)


@router.patch("/{product_id}")
async def update_product(product_id: uuid.UUID, body: UpdateProduct, db: AsyncSession = Depends(get_db)):
    """Rename, describe, confirm, or set the freshness SLO."""
    p = await _get(db, product_id)
    if body.name is not None and body.name.strip():
        p.name = body.name.strip()[:255]
        p.slug = await service._unique_slug(db, p.workspace_id, p.name, p.id)
    if body.description is not None:
        p.description = body.description.strip() or None
    if body.status is not None:
        p.status = body.status
        p.confirmed_at = datetime.now(timezone.utc) if body.status == "confirmed" else None
    if body.freshness_slo_hours is not None:
        spec = dict(p.spec or {})
        spec["settings"] = {**(spec.get("settings") or {}),
                            "freshness_slo_hours": body.freshness_slo_hours or None}
        p.spec = spec
    ws = await _workspace(db, p.workspace_id)
    touched = await _publish(db, p, ws.name)
    await db.commit()
    await product_mesh.reindex(touched)
    return await service.full(db, p, ws.name)


@router.delete("/{product_id}", status_code=204)
async def delete_product(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    p = await _get(db, product_id)
    touched = await product_mesh.unpublish(db, p)
    await db.delete(p)
    await db.commit()
    await product_mesh.reindex(touched)
    return None
