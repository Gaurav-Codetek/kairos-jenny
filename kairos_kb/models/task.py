"""Task model — task within a Databricks job."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class Task(Base):
    """Task within a Databricks job."""

    __tablename__ = "tasks"

    entity_id: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_key: Mapped[str] = mapped_column(String(255), nullable=False)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown")
    depends_on: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notebook_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sql_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    workspace = relationship("Workspace", lazy="selectin")
    job = relationship("Job", back_populates="tasks", lazy="selectin")
