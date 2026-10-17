"""Run model — job run execution record."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class Run(Base):
    """Job run execution record."""

    __tablename__ = "runs"

    entity_id: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_native_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    run_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    state: Mapped[str] = mapped_column(String(50), nullable=False)  # PENDING, RUNNING, TERMINATED, etc.
    result_state: Mapped[str | None] = mapped_column(String(50), nullable=True)  # SUCCESS, FAILED, TIMEDOUT, etc.
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger: Mapped[str] = mapped_column(String(50), nullable=False, default="UNKNOWN")
    execution_duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    setup_duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    run_page_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Relationships
    workspace = relationship("Workspace", lazy="selectin")
    job = relationship("Job", backref="runs", lazy="selectin")
    task_runs = relationship("TaskRun", back_populates="run", lazy="selectin")
