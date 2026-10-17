"""Incident and RCA report models.

An Incident is the durable, externally addressable handle for something that
went wrong. An RcaReport is one analysis of it — a run can be re-analysed as
the warehouse learns more, so an incident has many reports over time and the
newest is not automatically the only truth.

These exist so that consumers outside Kairos (an MCP client, a remediation
agent) have something stable to reference, subscribe to and act on. A
markdown paragraph returned from an HTTP call is not that.
"""


import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class Incident(Base):
    """Something that went wrong, with a lifecycle external systems can track."""

    __tablename__ = "incidents"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The failed run this incident is about. Unique so one run maps to one
    # incident rather than accumulating duplicates on repeated analysis.
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # open, investigating, explained, resolved, dismissed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")

    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace = relationship("Workspace", lazy="selectin")
    run = relationship("Run", lazy="selectin")


class RcaReport(Base):
    """One structured root cause analysis of an incident.

    Both representations are kept: the structured fields are what an agent
    acts on, the narrative is what a human reads. Neither is derived from the
    other after the fact — the agent produces both in one pass.
    """

    __tablename__ = "rca_reports"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ── Root cause ───────────────────────────────────────────────────
    # Free-form so the vocabulary can grow, but seeded with a known set:
    # SCHEMA_DRIFT, MISSING_DATA, PERMISSION, CONFIG_ERROR, CODE_DEFECT,
    # UPSTREAM_FAILURE, INFRASTRUCTURE, RESOURCE_LIMIT, UNKNOWN.
    root_cause_category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    root_cause_entity_id: Mapped[str | None] = mapped_column(String(1024), nullable=True, index=True)
    root_cause_summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    # ── Findings ─────────────────────────────────────────────────────
    evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    timeline: Mapped[list | None] = mapped_column(JSON, nullable=True)
    affected_assets: Mapped[list | None] = mapped_column(JSON, nullable=True)
    blocked_tasks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    open_questions: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # ── Remediation, proposed only — Kairos never applies it ─────────
    remediation: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ── Human-readable form ──────────────────────────────────────────
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Provenance and staleness ─────────────────────────────────────
    # A finding is true against the state it was derived from. Recording that
    # state lets a consumer tell a current explanation from a stale one.
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    evidence_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tools_used: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="final")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    incident = relationship("Incident", backref="reports", lazy="selectin")
