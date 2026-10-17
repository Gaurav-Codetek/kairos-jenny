"""Change detector — compares incoming data vs. existing state to generate ChangeEvents."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.models.change_event import ChangeEvent
from kairos_kb.models.evidence import Evidence

logger = logging.getLogger(__name__)


def compute_content_hash(content: Any) -> str:
    """SHA-256 hash of content for dedup."""
    if isinstance(content, dict):
        content = json.dumps(content, sort_keys=True, default=str)
    elif not isinstance(content, str):
        content = str(content)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def create_evidence(
    session: AsyncSession,
    *,
    workspace_id: Any,
    entity_id: str,
    source_type: str,
    content: Any,
    source_id: str | None = None,
    metadata_extra: dict | None = None,
) -> Evidence:
    """Create and persist an Evidence record."""
    content_str = json.dumps(content, default=str) if isinstance(content, dict) else str(content)
    evidence = Evidence(
        workspace_id=workspace_id,
        entity_id=entity_id,
        source_type=source_type,
        source_id=source_id,
        content=content_str,
        content_hash=compute_content_hash(content_str),
        observed_at=datetime.now(timezone.utc),
        metadata_extra=metadata_extra,
    )
    session.add(evidence)
    return evidence


async def detect_changes(
    session: AsyncSession,
    *,
    workspace_id: Any,
    entity_id: str,
    entity_type: str,
    old_values: Dict[str, Any],
    new_values: Dict[str, Any],
    fields_to_compare: List[str],
) -> List[ChangeEvent]:
    """Compare old and new values, create ChangeEvent records for differences."""
    now = datetime.now(timezone.utc)
    changes: List[ChangeEvent] = []

    for field in fields_to_compare:
        old_val = old_values.get(field)
        new_val = new_values.get(field)

        # Normalize for comparison
        old_str = json.dumps(old_val, sort_keys=True, default=str) if isinstance(old_val, (dict, list)) else str(old_val) if old_val is not None else None
        new_str = json.dumps(new_val, sort_keys=True, default=str) if isinstance(new_val, (dict, list)) else str(new_val) if new_val is not None else None

        if old_str != new_str:
            change = ChangeEvent(
                workspace_id=workspace_id,
                entity_id=entity_id,
                entity_type=entity_type,
                change_type="MODIFIED",
                field_name=field,
                old_value=old_str,
                new_value=new_str,
                detected_at=now,
            )
            session.add(change)
            changes.append(change)

    if changes:
        logger.info("Detected %d changes on %s %s", len(changes), entity_type, entity_id)

    return changes


async def record_creation(
    session: AsyncSession,
    *,
    workspace_id: Any,
    entity_id: str,
    entity_type: str,
) -> ChangeEvent:
    """Record that a new entity was discovered."""
    change = ChangeEvent(
        workspace_id=workspace_id,
        entity_id=entity_id,
        entity_type=entity_type,
        change_type="CREATED",
        detected_at=datetime.now(timezone.utc),
    )
    session.add(change)
    logger.info("New %s discovered: %s", entity_type, entity_id)
    return change


async def record_removal(
    session: AsyncSession,
    *,
    workspace_id: Any,
    entity_id: str,
    entity_type: str,
) -> ChangeEvent:
    """Record that an entity was no longer found."""
    change = ChangeEvent(
        workspace_id=workspace_id,
        entity_id=entity_id,
        entity_type=entity_type,
        change_type="REMOVED",
        detected_at=datetime.now(timezone.utc),
    )
    session.add(change)
    logger.info("%s removed: %s", entity_type, entity_id)
    return change
