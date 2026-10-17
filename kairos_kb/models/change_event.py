"""ChangeEvent model — records a detected change on any entity."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class ChangeEvent(Base):
    """Records a change detected on any entity.

    This is the temporal layer — it allows the system to answer
    'What changed between the last successful run and the failed run?'
    """

    __tablename__ = "change_events"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # CATALOG, SCHEMA, TABLE, COLUMN, JOB, TASK
    change_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # CREATED, MODIFIED, REMOVED, SCHEMA_CHANGE, RENAMED
    field_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    workspace = relationship("Workspace", lazy="selectin")
    evidence = relationship("Evidence", lazy="selectin")
