"""enrichment live telemetry: token usage, call counts, current activity

Revision ID: e5a1c7d2b9f4
Revises: bdb3efd12822
Create Date: 2026-09-28 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5a1c7d2b9f4"
down_revision: Union[str, None] = "bdb3efd12822"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USAGE = [
    ("input_tokens", sa.BigInteger()),
    ("output_tokens", sa.BigInteger()),
    ("llm_calls", sa.Integer()),
    ("tool_calls", sa.Integer()),
]


def upgrade() -> None:
    for table in ("enrichment_runs", "enrichment_items"):
        for name, type_ in USAGE:
            op.add_column(table, sa.Column(name, type_, nullable=False, server_default="0"))
    op.add_column("enrichment_runs", sa.Column("current_activity", sa.String(length=512), nullable=True))
    op.add_column("enrichment_runs", sa.Column("current_activity_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("enrichment_runs", "current_activity_at")
    op.drop_column("enrichment_runs", "current_activity")
    for table in ("enrichment_runs", "enrichment_items"):
        for name, _ in USAGE:
            op.drop_column(table, name)
