"""The living agent's own records: what it watches, what it saw, and what it remembers.

  Watch              one metric of a data product the agent keeps an eye on, at a time grain,
                     with the slices it explains changes by and how it reads good and bad
  MetricObservation  a metric's value for one period and slice *as it stood at one moment*
                     (as_of). Kept on every look, so the agent learns how numbers mature:
                     how much a recent period still moves before it settles.
  AgentNote          the memory stream: observations, findings, data issues, corrections,
                     briefings — each with the numbers behind it, a confidence, a status
                     and the person's feedback
  AgentRun           one look at the business (live, or a replay of history)
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from kairos_kb.db.base import Base


class Watch(Base):
    __tablename__ = "agent_watches"
    __table_args__ = (UniqueConstraint("product_id", "metric", name="uq_agent_watch_metric"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_products.id", ondelete="CASCADE"), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    time_dim: Mapped[str] = mapped_column(String(255), nullable=False)
    grain: Mapped[str] = mapped_column(String(16), nullable=False, default="month")
    slices: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # up: higher is better · down: lower is better · neutral: neither
    good_direction: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")
    # Periods a recent value keeps moving before it settles: a prior from what the data is,
    # replaced by the measured maturity once enough looks have been recorded.
    settle_periods: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settle_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    why: Mapped[str | None] = mapped_column(Text, nullable=True)
    min_impact_pct: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    sensitivity: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="agent")


class MetricObservation(Base):
    __tablename__ = "agent_observations"

    watch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_watches.id", ondelete="CASCADE"), nullable=False, index=True)
    slice: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    period: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)


class AgentNote(Base):
    __tablename__ = "agent_notes"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="live")
    watch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_watches.id", ondelete="SET NULL"), nullable=True, index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_products.id", ondelete="SET NULL"), nullable=True)
    # finding · data_issue · correction · briefing · reflection
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # spike · drop · trend · shift · crossing · drift
    signal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    facts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    period: Mapped[date | None] = mapped_column(Date, nullable=True)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    # provisional (waiting for the data to settle) · open · confirmed · withdrawn · resolved · dismissed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", index=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    feedback: Mapped[str | None] = mapped_column(String(16), nullable=True)
    feedback_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    seen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="live")
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
