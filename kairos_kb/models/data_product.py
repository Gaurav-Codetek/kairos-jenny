"""DataProduct — a business-facing bundle of the map, built for agents.

A data product is what a person asks for ("Sales", "Delivery performance") and
what a chatbot should be scoped to. It is assembled from the map, never from a
new pipeline: the output tables a person picked (the product's output ports),
everything upstream that feeds them, the pipelines and platform objects
attached to any of them, their enriched profiles, checks and freshness — and,
on top, the business layer an LLM proposes from that material: the metrics
with one definition each, the dimensions to slice by, the joins, the questions
the product answers and its caveats. Code validates every column, table and
join the business layer names against the map before it is kept.

  bundle      code-assembled: members, flow, objects, pipelines, health
  spec        LLM-proposed, code-validated: purpose, metrics, dimensions, joins, questions
  validation  what code checked, and what it dropped

Status: draft until a person confirms it.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from kairos_kb.db.base import Base


class DataProduct(Base):
    __tablename__ = "data_products"
    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_data_product_slug"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What the person asked for, in their words; steers the business layer.
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The entities the person picked: the product's output ports.
    seeds: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    bundle: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
