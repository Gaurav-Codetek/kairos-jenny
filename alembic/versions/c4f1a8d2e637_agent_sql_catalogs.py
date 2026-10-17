"""agent clients: catalogs each agent may query with run_sql

Revision ID: c4f1a8d2e637
Revises: b8e2f4a7d915
Create Date: 2026-10-01 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4f1a8d2e637"
down_revision: Union[str, None] = "b8e2f4a7d915"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_clients", sa.Column("sql_catalogs", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_clients", "sql_catalogs")
