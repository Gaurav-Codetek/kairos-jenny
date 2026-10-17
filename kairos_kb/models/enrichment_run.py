"""Enrichment run bookkeeping.

Runs are long (hundreds of entities, live Databricks reads) and the API
container restarts on code reload, so every unit of work is persisted.
A run can always be resumed from where it stopped.
"""


import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class EnrichmentRun(Base):
    """One background pass of the enrichment agent over a set of entities."""

    __tablename__ = "enrichment_runs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # What this run was asked to cover: kinds, entity ids, limits, force flag.
    scope: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # queued, running, paused, completed, failed, canceled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)

    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    relations_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entities_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    current_entity_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Live telemetry: what the run has consumed and is doing right now ──
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # A human-readable line: "Reading /Workspace/…/notebook", "Thinking · turn 3/24".
    current_activity: Mapped[str | None] = mapped_column(String(512), nullable=True)
    current_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace = relationship("Workspace", lazy="selectin")


class EnrichmentItem(Base):
    """One entity queued for profiling within a run."""

    __tablename__ = "enrichment_items"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enrichment_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    # pending, running, completed, failed, skipped
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    # Lower runs first, so containers are profiled before their contents.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # Hops from the seed entity. The queue is ordered by this first, so the
    # walk proceeds level by level outward rather than jumping between
    # unrelated branches.
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    # The entity whose profile led here. Its summary is handed to this
    # entity's agent so each profile is written with its parent in view.
    parent_entity_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Relation the frontier followed to reach this entity.
    via_relation: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    run = relationship("EnrichmentRun", lazy="selectin")


class EnrichmentEvent(Base):
    """Append-only activity log — the feed the UI streams while a run works."""

    __tablename__ = "enrichment_events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enrichment_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # entity_started, tool_call, relation_found, entity_discovered,
    # profile_written, entity_failed, run_finished
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Monotonic per run so the UI can poll with a simple cursor.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    run = relationship("EnrichmentRun", lazy="selectin")
