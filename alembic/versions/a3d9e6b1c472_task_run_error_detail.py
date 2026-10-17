"""task runs: the exact error behind a failure (exception, cell, line, trace)

Revision ID: a3d9e6b1c472
Revises: f7c3a91e2d10
Create Date: 2026-10-01 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a3d9e6b1c472"
down_revision: Union[str, None] = "f7c3a91e2d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("task_runs", sa.Column("error_detail", sa.JSON(), nullable=True))
    op.add_column("task_runs", sa.Column("error_trace", sa.Text(), nullable=True))
    op.add_column("task_runs", sa.Column("output_fetched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("task_runs", "output_fetched_at")
    op.drop_column("task_runs", "error_trace")
    op.drop_column("task_runs", "error_detail")
