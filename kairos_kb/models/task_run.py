"""TaskRun model — individual task execution within a run."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class TaskRun(Base):
    """Individual task execution within a run."""

    __tablename__ = "task_runs"

    entity_id: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_native_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_key: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    result_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # For a failed run, what actually went wrong, from the run's output: the
    # exception, where it was raised (cell, line, function, code) and the frames
    # leading there. See kairos_kb/ingestion/run_errors.py.
    error_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # The traceback, terminal colour codes removed, capped.
    error_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When the output was read; null for runs never fetched (succeeded, or synced before).
    output_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace = relationship("Workspace", lazy="selectin")
    run = relationship("Run", back_populates="task_runs", lazy="selectin")
    task = relationship("Task", lazy="selectin")
