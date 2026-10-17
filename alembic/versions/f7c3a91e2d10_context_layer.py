"""context layer: search documents, agent clients, activity audit, feedback

Revision ID: f7c3a91e2d10
Revises: e5a1c7d2b9f4
Create Date: 2026-09-28 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "f7c3a91e2d10"
down_revision: Union[str, None] = "e5a1c7d2b9f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base():
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "context_documents",
        *_base(),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.String(1024), nullable=False, unique=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("name", sa.String(1024), nullable=False),
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("trust_level", sa.String(32), nullable=False, server_default="synced"),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_context_documents_workspace_id", "context_documents", ["workspace_id"])
    op.create_index("ix_context_documents_entity_id", "context_documents", ["entity_id"])
    op.create_index("ix_context_documents_kind", "context_documents", ["kind"])
    op.execute("CREATE INDEX ix_context_documents_search ON context_documents USING GIN (search_vector)")
    op.execute("CREATE INDEX ix_context_documents_name_trgm ON context_documents USING GIN (name gin_trgm_ops)")
    op.execute(
        "CREATE INDEX ix_context_documents_embedding ON context_documents "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "agent_clients",
        *_base(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("workspace_ids", sa.JSON(), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_agent_clients_key_prefix", "agent_clients", ["key_prefix"])

    op.create_table(
        "agent_activity",
        *_base(),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_name", sa.String(255), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("tool", sa.String(128), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=True),
        sa.Column("entity_ids", sa.JSON(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_size", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_agent_activity_agent_id", "agent_activity", ["agent_id"])
    op.create_index("ix_agent_activity_tool", "agent_activity", ["tool"])
    op.create_index("ix_agent_activity_created_at", "agent_activity", ["created_at"])

    op.create_table(
        "context_feedback",
        *_base(),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("entity_id", sa.String(1024), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reporter", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("field", sa.String(255), nullable=True),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
    )
    op.create_index("ix_context_feedback_workspace_id", "context_feedback", ["workspace_id"])
    op.create_index("ix_context_feedback_entity_id", "context_feedback", ["entity_id"])
    op.create_index("ix_context_feedback_status", "context_feedback", ["status"])


def downgrade() -> None:
    op.drop_table("context_feedback")
    op.drop_table("agent_activity")
    op.drop_table("agent_clients")
    op.drop_table("context_documents")
