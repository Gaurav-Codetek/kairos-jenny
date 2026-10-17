"""LineageEdge model — table-level or column-level lineage relationship."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class LineageEdge(Base):
    """Table-level or column-level lineage relationship."""

    __tablename__ = "lineage_edges"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)  # TABLE or COLUMN
    source_entity_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    target_entity_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    source_table_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tables.id", ondelete="SET NULL"), nullable=True
    )
    target_table_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tables.id", ondelete="SET NULL"), nullable=True
    )
    transformation: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    task_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # Relationships
    workspace = relationship("Workspace", lazy="selectin")
    source_table = relationship("Table", foreign_keys=[source_table_id], lazy="selectin")
    target_table = relationship("Table", foreign_keys=[target_table_id], lazy="selectin")
