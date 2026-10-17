"""Evidence model — factual observation backing a claim or state."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class Evidence(Base):
    """Factual observation backing a claim or state.

    Every important inference in the system should have associated evidence.
    This is a core differentiator — the system should never simply assert
    facts without tracing them to observations.
    """

    __tablename__ = "evidence"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # API_RESPONSE, SQL_QUERY, TABLE_HISTORY, SCHEMA_CHANGE, SYSTEM_TABLE, etc.
    source_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace = relationship("Workspace", lazy="selectin")
