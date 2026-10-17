"""companion conversations: chats and calls with Jenny, kept across refreshes and restarts

Revision ID: 7e3b5c9d2f40
Revises: 6d2a9e4b7c11
Create Date: 2026-10-10 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "7e3b5c9d2f40"
down_revision: Union[str, None] = "6d2a9e4b7c11"
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
        "companion_conversations", *_base(),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("history", postgresql.JSON, nullable=True),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=True, index=True),
    )
    op.create_table(
        "companion_messages", *_base(),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("companion_conversations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("text", sa.Text, nullable=False, server_default=""),
        sa.Column("voice", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("steps", postgresql.JSON, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="done"),
        sa.Column("meta", postgresql.JSON, nullable=True),
        sa.Column("ms", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("companion_messages")
    op.drop_table("companion_conversations")
