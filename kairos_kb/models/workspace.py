"""Workspace model — represents a connected Databricks workspace."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from kairos_kb.db.base import Base


class Workspace(Base):
    """A connected Databricks workspace."""

    __tablename__ = "workspaces"

    workspace_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    host: Mapped[str] = mapped_column(String(512), nullable=False)
    # Which platform this connection targets. The connector layer is
    # platform-agnostic; this is what selects the concrete implementation.
    platform: Mapped[str] = mapped_column(
        String(50), nullable=False, default="databricks", index=True
    )
    # Non-secret connection settings that differ per platform — Snowflake
    # account/warehouse/role, dbt manifest location, and so on. Secrets stay
    # in configuration, never here.
    connection_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cloud: Mapped[str] = mapped_column(String(50), nullable=False, default="azure")
    region: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_cursor: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
