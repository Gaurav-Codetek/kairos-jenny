"""Industry knowledge: what Kairos knows about a sector, independent of any client.

Three layers make up what an agent can rely on:

  industry knowledge   curated by Kairos per sector (pharma first) — what an 867
                       feed is, how NDC and NPI work, which dataset answers which
                       question, governance rules. Shared by every client.
  client context       curated with each client by Kairos's forward deployed
                       engineers — that client's definitions, calendars, hierarchies.
  technical map        derived automatically — tables, lineage, grain, runs, trust.

This module holds the first layer and its bindings to the third:

  KnowledgePack      one versioned knowledge base (an Open Knowledge Format bundle)
  KnowledgeConcept   one concept: a dataset type, identifier, regulation, metric, …
  KnowledgeRelation  a typed edge between concepts, from the bundle
  KnowledgeBinding   a warehouse entity bound to a concept — "this table is a 3PL
                     867 feed", "this column is an NPI" — with evidence, a
                     confidence, and a status: proposed by Kairos, confirmed or
                     rejected by a person.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from kairos_kb.db.base import Base
from kairos_kb.models.context import EMBEDDING_DIMENSIONS


class KnowledgePack(Base):
    __tablename__ = "knowledge_packs"

    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Content hash of every concept loaded: changes when the bundle changes.
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    okf_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    concept_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeConcept(Base):
    __tablename__ = "knowledge_concepts"
    __table_args__ = (UniqueConstraint("pack_id", "concept_id", name="uq_knowledge_concept"),)

    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The OKF concept ID: the file path without .md, e.g. /identifiers/provider/npi
    concept_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Every other frontmatter key: grain, primary_key, join_keys, identifier_format, …
    fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Body sections by heading: {"Definition": "...", "Pitfalls": "...", ...}
    sections: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)
    search_vector = mapped_column(TSVECTOR, nullable=True)
    embedding = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class KnowledgeRelation(Base):
    __tablename__ = "knowledge_relations"

    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_concept: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    predicate: Mapped[str] = mapped_column(String(64), nullable=False)
    target_concept: Mapped[str] = mapped_column(String(512), nullable=False, index=True)


class KnowledgeBinding(Base):
    __tablename__ = "knowledge_bindings"
    __table_args__ = (UniqueConstraint("entity_id", "concept_id", "predicate", name="uq_knowledge_binding"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    concept_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    # instance_of: a table is a dataset type · identified_by: a column holds an identifier
    predicate: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # auto: proposed by Kairos · person: set by a reviewer (an FDE)
    method: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    # proposed · confirmed · rejected — a rejected binding is never proposed again
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
