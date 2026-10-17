"""Open-vocabulary entities and relationships found by the enrichment agent.

The synced warehouse only knows the kinds the connector extracts. Reading
task code surfaces things the sync never created — volumes, files, Genie
spaces, external connections, dashboards — and relationships nobody
declared up front. Both are stored with free-form ``kind`` /
``relation_type`` strings so the entity map can grow without a migration.
"""


import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kairos_kb.db.base import Base


class DiscoveredEntity(Base):
    """An entity the agent found that the connector never synced."""

    __tablename__ = "discovered_entities"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False, index=True)
    # Free-form: volume, file, genie_space, external_connection, notebook, ...
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    attrs: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # How the agent came to know about this entity.
    origin: Mapped[str] = mapped_column(String(64), nullable=False, default="agent_discovered")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enrichment_runs.id", ondelete="SET NULL"), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    workspace = relationship("Workspace", lazy="selectin")
    evidence = relationship("Evidence", lazy="selectin")


class DiscoveredRelation(Base):
    """A relationship the agent asserted between two entities.

    Every row must carry a rationale, and should carry evidence — an edge the
    system cannot justify is not something the agent should be trusted on.
    """

    __tablename__ = "discovered_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            name="uq_discovered_relation",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_entity_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    target_entity_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    # Free-form: READS_TABLE, WRITES_TABLE, READS_VOLUME_FILE, USES_GENIE_SPACE, ...
    relation_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    # Where in the source material this was seen (file path, line, API field).
    source_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enrichment_runs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    workspace = relationship("Workspace", lazy="selectin")
    evidence = relationship("Evidence", lazy="selectin")
