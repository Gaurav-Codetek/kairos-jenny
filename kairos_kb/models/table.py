"""Table model — Unity Catalog table or view entity."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class Table(Base):
    """Unity Catalog table or view."""

    __tablename__ = "tables"

    entity_id: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schemas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    table_type: Mapped[str] = mapped_column(String(50), nullable=False)  # MANAGED, EXTERNAL, VIEW
    data_source_format: Mapped[str | None] = mapped_column(String(50), nullable=True)  # DELTA, PARQUET, CSV, etc.
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    properties: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    storage_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    workspace = relationship("Workspace", lazy="selectin")
    schema_ref = relationship("Schema", backref="tables", lazy="selectin")
    columns = relationship("Column", back_populates="table", lazy="selectin")
