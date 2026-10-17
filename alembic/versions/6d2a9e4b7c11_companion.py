"""companion: live state per connection, and the pulses that built it

Revision ID: 6d2a9e4b7c11
Revises: 4b8d1e6f2a90
Create Date: 2026-10-10 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "6d2a9e4b7c11"
down_revision: Union[str, None] = "4b8d1e6f2a90"
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
        "companion_state", *_base(),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("interval_seconds", sa.Integer, nullable=False, server_default="300"),
        sa.Column("tz_offset_minutes", sa.Integer, nullable=True),
        sa.Column("tz_source", sa.String(16), nullable=True),
        sa.Column("vitals", postgresql.JSON, nullable=True),
        sa.Column("memory", postgresql.JSON, nullable=True),
        sa.Column("snapshot", postgresql.JSON, nullable=True),
        sa.Column("headline", sa.Text, nullable=True),
        sa.Column("headline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_pulse_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("live", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(16), nullable=False, server_default="idle"),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_table(
        "companion_pulses", *_base(),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("headline", sa.Text, nullable=True),
        sa.Column("summary", postgresql.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("companion_pulses")
    op.drop_table("companion_state")
