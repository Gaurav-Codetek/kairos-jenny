"""Column model — table column entity."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class Column(Base):
    """Table column."""

    __tablename__ = "columns"

    entity_id: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    data_type: Mapped[str] = mapped_column(String(255), nullable=False)
    full_data_type: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_nullable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_partition_column: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    workspace = relationship("Workspace", lazy="selectin")
    table = relationship("Table", back_populates="columns", lazy="selectin")
