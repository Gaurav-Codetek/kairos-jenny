"""Job model — Databricks job entity."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class Job(Base):
    """Databricks job."""

    __tablename__ = "jobs"

    entity_id: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_native_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schedule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    max_concurrent_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    settings_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    workspace = relationship("Workspace", backref="jobs", lazy="selectin")
    tasks = relationship("Task", back_populates="job", lazy="selectin")
