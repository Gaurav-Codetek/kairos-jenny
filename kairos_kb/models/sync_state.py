"""SyncState model — tracks synchronization progress per workspace per domain."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class SyncState(Base):
    """Tracks synchronization progress per workspace per domain."""

    __tablename__ = "sync_states"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(50), nullable=False)  # catalog, jobs, lineage, runs
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cursor: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="idle")  # idle, running, error
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    items_synced: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    workspace = relationship("Workspace", lazy="selectin")
