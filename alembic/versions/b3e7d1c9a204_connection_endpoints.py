"""per-connection MCP endpoints: room for connection names in activity channels and eval connectors

Revision ID: b3e7d1c9a204
Revises: a7d4c2e9f531
Create Date: 2026-10-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b3e7d1c9a204"
down_revision: Union[str, None] = "a7d4c2e9f531"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # "mcp:<connection slug>" and "c:<connection slug>" outgrow 16 characters.
    op.alter_column("agent_activity", "channel", type_=sa.String(96), existing_nullable=False)
    op.alter_column("eval_threads", "connector", type_=sa.String(96), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("eval_threads", "connector", type_=sa.String(16), existing_nullable=False)
    op.alter_column("agent_activity", "channel", type_=sa.String(16), existing_nullable=False)
