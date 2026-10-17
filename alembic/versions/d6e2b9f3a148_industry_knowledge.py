"""industry knowledge: packs, concepts, relations, and bindings to the warehouse

Revision ID: d6e2b9f3a148
Revises: c4f1a8d2e637
Create Date: 2026-10-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "d6e2b9f3a148"
down_revision: Union[str, None] = "c4f1a8d2e637"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base():
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "knowledge_packs", *_base(),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("source_path", sa.String(1024), nullable=False),
        sa.Column("okf_version", sa.String(32), nullable=True),
        sa.Column("concept_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "knowledge_concepts", *_base(),
        sa.Column("pack_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.String(512), nullable=False),
        sa.Column("type", sa.String(128), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=True),
        sa.Column("sections", sa.JSON(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("pack_id", "concept_id", name="uq_knowledge_concept"),
    )
    op.create_index("ix_knowledge_concepts_pack_id", "knowledge_concepts", ["pack_id"])
    op.create_index("ix_knowledge_concepts_concept_id", "knowledge_concepts", ["concept_id"])
    op.create_index("ix_knowledge_concepts_type", "knowledge_concepts", ["type"])
    op.execute("CREATE INDEX ix_knowledge_concepts_search ON knowledge_concepts USING GIN (search_vector)")
    op.execute("CREATE INDEX ix_knowledge_concepts_embedding ON knowledge_concepts USING hnsw (embedding vector_cosine_ops)")

    op.create_table(
        "knowledge_relations", *_base(),
        sa.Column("pack_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_concept", sa.String(512), nullable=False),
        sa.Column("predicate", sa.String(64), nullable=False),
        sa.Column("target_concept", sa.String(512), nullable=False),
    )
    op.create_index("ix_knowledge_relations_pack_id", "knowledge_relations", ["pack_id"])
    op.create_index("ix_knowledge_relations_source", "knowledge_relations", ["source_concept"])
    op.create_index("ix_knowledge_relations_target", "knowledge_relations", ["target_concept"])

    op.create_table(
        "knowledge_bindings", *_base(),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.String(1024), nullable=False),
        sa.Column("concept_id", sa.String(512), nullable=False),
        sa.Column("predicate", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("method", sa.String(32), nullable=False, server_default="auto"),
        sa.Column("status", sa.String(32), nullable=False, server_default="proposed"),
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint("entity_id", "concept_id", "predicate", name="uq_knowledge_binding"),
    )
    op.create_index("ix_knowledge_bindings_workspace_id", "knowledge_bindings", ["workspace_id"])
    op.create_index("ix_knowledge_bindings_entity_id", "knowledge_bindings", ["entity_id"])
    op.create_index("ix_knowledge_bindings_concept_id", "knowledge_bindings", ["concept_id"])
    op.create_index("ix_knowledge_bindings_status", "knowledge_bindings", ["status"])


def downgrade() -> None:
    op.drop_table("knowledge_bindings")
    op.drop_table("knowledge_relations")
    op.drop_table("knowledge_concepts")
    op.drop_table("knowledge_packs")
