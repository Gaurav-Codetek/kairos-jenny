"""Compose and persist entity profile YAML.

Relationships are never taken from the model's prose. They are read back
from ``discovered_relations``, which is only written by the ``link_entities``
tool, so every relationship in a YAML file traces to a deliberate tool call
with a rationale attached.

Because relationships are stored once but must appear in *both* endpoints'
files, a profile is rewritten whenever it gains a new edge.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yaml
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.models.discovered import DiscoveredRelation
from kairos_kb.models.entity_profile import EntityProfile
from kairos_kb.storage.local import LocalStorageBackend

logger = logging.getLogger(__name__)

PROFILE_VERSION = 1
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def profile_path(entity_id: str) -> str:
    """Storage path for an entity's YAML artifact."""
    kind, _, rest = entity_id.partition(":")
    safe = _UNSAFE.sub("_", rest) or "unnamed"
    # Filesystems dislike very long names; keep the tail, which is the
    # discriminating part of a fully qualified name.
    if len(safe) > 180:
        safe = safe[-180:]
    return f"profiles/{kind}/{safe}.yaml"


async def _relationship_block(db: AsyncSession, entity_id: str) -> List[Dict[str, Any]]:
    """Every discovered edge touching this entity, in both directions."""
    rows = (
        await db.execute(
            select(DiscoveredRelation)
            .where(
                DiscoveredRelation.status != "contradicted",
                or_(
                    DiscoveredRelation.source_entity_id == entity_id,
                    DiscoveredRelation.target_entity_id == entity_id,
                )
            )
            .order_by(DiscoveredRelation.relation_type)
        )
    ).scalars().all()

    block: List[Dict[str, Any]] = []
    for row in rows:
        outgoing = row.source_entity_id == entity_id
        block.append(
            {
                "direction": "outgoing" if outgoing else "incoming",
                "type": row.relation_type,
                "target" if outgoing else "source": (
                    row.target_entity_id if outgoing else row.source_entity_id
                ),
                "confidence": round(row.confidence, 2),
                "rationale": row.rationale,
                "source_ref": row.source_ref,
                "observed_at": row.observed_at.isoformat(),
            }
        )
    return block


async def compose_profile_yaml(
    db: AsyncSession,
    *,
    entity_id: str,
    kind: str,
    name: str,
    fields: Dict[str, Any],
) -> str:
    """Build the YAML document for one entity."""
    document: Dict[str, Any] = {
        "entity_id": entity_id,
        "kind": kind,
        "name": name,
        "profile_version": PROFILE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Agent-authored understanding and the code-authored blocks around it
    # (classification, facts, verification), in a stable key order.
    for key in (
        "summary",
        "purpose",
        "data_product",
        "semantic_tags",
        "classification",
        "facts",
        "shape",
        "grain_key",
        "creation",
        "verification",
        "operational_notes",
        "open_questions",
        "classification_feedback",
    ):
        value = fields.get(key)
        if value not in (None, "", [], {}):
            document[key] = value

    document["relationships"] = await _relationship_block(db, entity_id)

    return yaml.safe_dump(
        document,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )


async def write_profile(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    entity_id: str,
    kind: str,
    name: str,
    fields: Dict[str, Any],
    source_hash_value: str,
    model: str | None = None,
    run_id: uuid.UUID | None = None,
    storage: LocalStorageBackend | None = None,
) -> EntityProfile:
    """Render the YAML, persist it, and upsert the index row."""
    backend = storage or LocalStorageBackend()
    path = profile_path(entity_id)

    content = await compose_profile_yaml(
        db, entity_id=entity_id, kind=kind, name=name, fields=fields
    )
    await backend.save(path, content)

    existing = (
        await db.execute(select(EntityProfile).where(EntityProfile.entity_id == entity_id))
    ).scalars().first()

    tags = fields.get("semantic_tags")
    if not isinstance(tags, list):
        tags = None

    now = datetime.now(timezone.utc)

    if existing:
        existing.kind = kind
        existing.yaml_path = path
        existing.summary = fields.get("summary")
        existing.purpose = fields.get("purpose")
        existing.data_product = fields.get("data_product")
        existing.semantic_tags = tags
        existing.source_hash = source_hash_value
        existing.model = model
        existing.run_id = run_id
        existing.generated_at = now
        existing.profile_version = PROFILE_VERSION
        profile = existing
    else:
        profile = EntityProfile(
            workspace_id=workspace_id,
            entity_id=entity_id,
            kind=kind,
            yaml_path=path,
            summary=fields.get("summary"),
            purpose=fields.get("purpose"),
            data_product=fields.get("data_product"),
            semantic_tags=tags,
            source_hash=source_hash_value,
            profile_version=PROFILE_VERSION,
            model=model,
            run_id=run_id,
            generated_at=now,
        )
        db.add(profile)

    await db.flush()
    return profile


async def refresh_profile_yaml(
    db: AsyncSession,
    entity_id: str,
    *,
    storage: LocalStorageBackend | None = None,
) -> bool:
    """Rewrite an existing profile so newly discovered edges appear in it.

    Called for the *other* end of every link, so a relationship shows up in
    both files without the agent having to revisit the counterpart entity.
    """
    profile = (
        await db.execute(select(EntityProfile).where(EntityProfile.entity_id == entity_id))
    ).scalars().first()
    if not profile:
        return False

    backend = storage or LocalStorageBackend()
    try:
        raw = await backend.load(profile.yaml_path)
        document = yaml.safe_load(raw.decode("utf-8")) or {}
    except (FileNotFoundError, yaml.YAMLError) as exc:
        logger.warning("Could not reload profile %s: %s", profile.yaml_path, exc)
        return False

    document["relationships"] = await _relationship_block(db, entity_id)
    document["generated_at"] = datetime.now(timezone.utc).isoformat()

    await backend.save(
        profile.yaml_path,
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100),
    )
    return True


async def load_profile_yaml(
    db: AsyncSession, entity_id: str, *, storage: LocalStorageBackend | None = None
) -> Optional[str]:
    """Read back a stored YAML profile."""
    profile = (
        await db.execute(select(EntityProfile).where(EntityProfile.entity_id == entity_id))
    ).scalars().first()
    if not profile:
        return None
    backend = storage or LocalStorageBackend()
    try:
        return (await backend.load(profile.yaml_path)).decode("utf-8")
    except FileNotFoundError:
        return None
