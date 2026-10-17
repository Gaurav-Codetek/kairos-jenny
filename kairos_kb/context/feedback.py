"""The loop that makes the map better with use.

An agent that finds context wrong, missing or stale says so. The report is
kept against the entity, shown to every other agent in that entity's card
straight away, and handed to the enrichment agent the next time the entity
is profiled — an open report also forces that re-profile rather than letting
the entity be skipped as unchanged. Once folded in, the report is marked applied.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kairos_kb.context.access import AgentIdentity
from kairos_kb.models.context import ContextFeedback
from kairos_kb.models.context import ContextDocument

KINDS = ("incorrect", "missing", "stale", "confusing", "useful")


async def report_issue(db: AsyncSession, identity: AgentIdentity, entity_id: str, kind: str, message: str,
                       field: Optional[str] = None, suggestion: Optional[str] = None,
                       evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    kind = (kind or "").strip().lower()
    if kind not in KINDS:
        return {"error": f"kind must be one of {', '.join(KINDS)}"}
    if not (message or "").strip():
        return {"error": "Say what is wrong, missing or stale in message."}
    if not identity.sees_entity(entity_id):
        return {"error": "This agent key cannot see that entity."}
    doc = (await db.execute(select(ContextDocument).where(ContextDocument.entity_id == entity_id))).scalars().first()
    row = ContextFeedback(
        workspace_id=doc.workspace_id if doc else None,
        entity_id=entity_id,
        agent_id=identity.agent_id,
        reporter=identity.name,
        kind=kind,
        message=message.strip()[:4000],
        field=(field or None),
        suggestion=(suggestion or None),
        status="applied" if kind == "useful" else "open",
        evidence=evidence or None,
        # A report about a data product goes through the report loop (kairos_kb/products/fixes.py).
        stage="new" if entity_id.startswith("product:") and kind != "useful" else None,
    )
    db.add(row)
    await db.commit()
    return {
        "recorded": True,
        "feedback_id": str(row.id),
        "effect": ("Noted as useful." if kind == "useful" else
                   "Shown to every agent in this entity's context now, and given to the enrichment agent "
                   "the next time the entity is profiled."),
    }


async def open_feedback_for(db: AsyncSession, entity_id: str) -> List[ContextFeedback]:
    return list((await db.execute(
        select(ContextFeedback).where(ContextFeedback.entity_id == entity_id, ContextFeedback.status == "open")
        .order_by(ContextFeedback.created_at)
    )).scalars())


def feedback_brief(items: List[ContextFeedback]) -> str:
    """For the enrichment agent: what consumers of this profile have reported."""
    if not items:
        return ""
    lines = ["AGENT FEEDBACK ON THE CURRENT PROFILE — verify each against the facts and code; correct the "
             "profile where the report holds, and say in open_questions where it does not:"]
    for f in items[:10]:
        where = f" (field: {f.field})" if f.field else ""
        hint = f" Suggested: {f.suggestion}" if f.suggestion else ""
        lines.append(f"- [{f.kind}] {f.message}{where}.{hint}")
    return "\n".join(lines)


async def mark_applied(db: AsyncSession, ids: List[Any], note: str) -> None:
    if not ids:
        return
    await db.execute(update(ContextFeedback).where(ContextFeedback.id.in_(ids)).values(
        status="applied", resolution=f"{note} ({datetime.now(timezone.utc).isoformat(timespec='seconds')})",
    ))
    await db.commit()
