"""Data products in the map: each product is an entity, linked to the tables it reads.

A product is published into the same map every tool reads, so it is not a side record:

  entity    product:<connection>:<slug>, kind "product", origin "product" — with its
            domain, status, metrics, dimensions, glossary and inputs in attrs
  links     product —READS_TABLE→ each input table, verified (a person or the engine
            defined it), source_ref "data product". Because it is the relation a
            pipeline uses to read a table, lineage, trace() and blast radius show a
            product downstream of its tables with no special case.
  index     the product gets a search document (find() returns it), and each input
            table's document says which products it feeds

Published on every build, rename, status change; removed when the product is deleted.
Sync never touches these rows: it replaces only origin "platform" entities and
"platform metadata" links.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.models.context import ContextDocument
from kairos_kb.models.data_product import DataProduct
from kairos_kb.models.discovered import DiscoveredEntity, DiscoveredRelation

KIND = "product"
ORIGIN = "product"
SOURCE_REF = "data product"


def entity_id(workspace_name: str, slug: str) -> str:
    return f"{KIND}:{workspace_name}:{slug}"


def _attrs(p: DataProduct, health: Optional[str]) -> Dict[str, Any]:
    spec = p.spec or {}
    model = spec.get("model") or {}
    return {
        "product_id": str(p.id),
        "slug": p.slug,
        "domain": p.domain,
        "status": p.status,
        "health": health,
        "comment": p.description,
        "purpose": model.get("purpose"),
        "metrics": [{"name": m["name"], "label": m.get("label"), "description": m.get("description"),
                     "unit": m.get("unit")} for m in model.get("metrics") or []],
        "dimensions": [{"name": d["name"], "label": d.get("label"), "type": d.get("type")}
                       for d in model.get("dimensions") or []],
        "tools": [t["name"] for t in model.get("tools") or []],
        "glossary": model.get("glossary") or [],
        "inputs": [{"entity_id": i["entity_id"], "role": i.get("role")} for i in spec.get("inputs") or []],
    }


async def _withdraw(db: AsyncSession, eid: str) -> None:
    await db.execute(delete(DiscoveredRelation).where(
        DiscoveredRelation.source_entity_id == eid, DiscoveredRelation.source_ref == SOURCE_REF))
    await db.execute(delete(DiscoveredEntity).where(DiscoveredEntity.entity_id == eid))
    await db.execute(delete(ContextDocument).where(ContextDocument.entity_id == eid))


async def _published_for(db: AsyncSession, product_id: str, workspace_id) -> List[DiscoveredEntity]:
    rows = (await db.execute(select(DiscoveredEntity).where(
        DiscoveredEntity.workspace_id == workspace_id, DiscoveredEntity.origin == ORIGIN))).scalars().all()
    return [r for r in rows if (r.attrs or {}).get("product_id") == product_id]


async def publish(db: AsyncSession, p: DataProduct, workspace_name: str, health: Optional[str] = None) -> List[str]:
    """Write the product into the map. Returns the entity ids whose search documents need refreshing."""
    eid = entity_id(workspace_name, p.slug)
    now = datetime.now(timezone.utc)
    touched: set = set()
    # A rename changes the slug: the old entity goes, and so do its links and document.
    for old in await _published_for(db, str(p.id), p.workspace_id):
        if old.entity_id != eid:
            touched |= {i["entity_id"] for i in (old.attrs or {}).get("inputs") or []}
            await _withdraw(db, old.entity_id)

    ent = (await db.execute(select(DiscoveredEntity).where(DiscoveredEntity.entity_id == eid))).scalars().first()
    if ent is None:
        ent = DiscoveredEntity(workspace_id=p.workspace_id, entity_id=eid, kind=KIND, name=p.name[:512],
                               full_name=p.slug, origin=ORIGIN, rationale="Data product defined in Kairos.",
                               first_seen_at=now, last_seen_at=now)
        db.add(ent)
    else:
        touched |= {i["entity_id"] for i in (ent.attrs or {}).get("inputs") or []}
    ent.kind, ent.name, ent.full_name, ent.origin = KIND, p.name[:512], p.slug, ORIGIN
    ent.attrs, ent.last_seen_at = _attrs(p, health), now

    await db.execute(delete(DiscoveredRelation).where(
        DiscoveredRelation.source_entity_id == eid, DiscoveredRelation.source_ref == SOURCE_REF))
    for i in (p.spec or {}).get("inputs") or []:
        db.add(DiscoveredRelation(
            workspace_id=p.workspace_id, source_entity_id=eid, target_entity_id=i["entity_id"],
            relation_type="READS_TABLE", confidence=1.0, source_ref=SOURCE_REF, status="verified",
            rationale=f"Input port of the data product {p.name} ({i.get('role') or 'input'}): {i.get('why') or ''}"[:2000],
            observed_at=now))
        touched.add(i["entity_id"])
    await db.flush()
    return [eid, *sorted(touched)]


async def unpublish(db: AsyncSession, p: DataProduct) -> List[str]:
    """Take the product out of the map. Returns the input tables whose documents need refreshing."""
    touched: set = set()
    for old in await _published_for(db, str(p.id), p.workspace_id):
        touched |= {i["entity_id"] for i in (old.attrs or {}).get("inputs") or []}
        await _withdraw(db, old.entity_id)
    await db.flush()
    return sorted(touched)


async def reindex(entity_ids: List[str]) -> None:
    """Refresh search documents after a publish (their own sessions: call after the commit)."""
    from kairos_kb.context.documents import index_entities

    if entity_ids:
        await index_entities(entity_ids, force=True)


async def products_using(db: AsyncSession, entity_id_: str) -> List[Dict[str, Any]]:
    """The data products a table feeds, and its role in each."""
    rels = (await db.execute(select(DiscoveredRelation.source_entity_id).where(
        DiscoveredRelation.target_entity_id == entity_id_, DiscoveredRelation.source_ref == SOURCE_REF))).all()
    ids = [r[0] for r in rels]
    if not ids:
        return []
    out = []
    for ent in (await db.execute(select(DiscoveredEntity).where(DiscoveredEntity.entity_id.in_(ids)))).scalars():
        a = ent.attrs or {}
        role = next((i.get("role") for i in a.get("inputs") or [] if i.get("entity_id") == entity_id_), None)
        out.append({"product": ent.name, "id": a.get("slug"), "entity_id": ent.entity_id, "role": role,
                    "status": a.get("status"), "health": a.get("health")})
    return sorted(out, key=lambda x: x["product"])


async def publish_all() -> Dict[str, int]:
    """Publish every product (used once to backfill, and safe to repeat)."""
    from kairos_kb.db.engine import async_session_factory
    from kairos_kb.models.workspace import Workspace
    from kairos_kb.products.service import contracts_of

    touched: List[str] = []
    n = 0
    async with async_session_factory() as db:
        names = {w.id: w.name for w in (await db.execute(select(Workspace))).scalars()}
        for p in (await db.execute(select(DataProduct))).scalars().all():
            health = (await contracts_of(db, p))["health"]["status"]
            touched += await publish(db, p, names.get(p.workspace_id, ""), health)
            n += 1
        await db.commit()
    await reindex(list(dict.fromkeys(touched)))
    return {"products": n, "documents": len(set(touched))}
