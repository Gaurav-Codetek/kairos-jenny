"""Schema model — Unity Catalog schema (database) entity."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class Schema(Base):
    """Unity Catalog schema (database)."""

    __tablename__ = "schemas"

    entity_id: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    catalog_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalogs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(512), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    properties: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    workspace = relationship("Workspace", lazy="selectin")
    catalog = relationship("Catalog", backref="schemas", lazy="selectin")
