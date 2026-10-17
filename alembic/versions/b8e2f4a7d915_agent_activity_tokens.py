"""agent activity: tokens per tool call and estimated cost

Revision ID: b8e2f4a7d915
Revises: a3d9e6b1c472
Create Date: 2026-10-01 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b8e2f4a7d915"
down_revision: Union[str, None] = "a3d9e6b1c472"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_activity", sa.Column("args_tokens", sa.Integer(), nullable=True))
    op.add_column("agent_activity", sa.Column("result_tokens", sa.Integer(), nullable=True))
    op.add_column("agent_activity", sa.Column("est_cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_activity", "est_cost_usd")
    op.drop_column("agent_activity", "result_tokens")
    op.drop_column("agent_activity", "args_tokens")
