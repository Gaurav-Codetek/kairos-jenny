"""report loop: agents' reports about data products carry their evidence and move through triage, proposal and proof

Revision ID: 8a4d2f6c1e59
Revises: 7e3b5c9d2f40
Create Date: 2026-10-11 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "8a4d2f6c1e59"
down_revision: Union[str, None] = "7e3b5c9d2f40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # What the agent was asked and which lookups failed: so a fix can be proven by replaying them.
    op.add_column("context_feedback", sa.Column("evidence", postgresql.JSON(), nullable=True))
    # Where the report is: new → triaged → proposed | verified, or needs_person / merged / dismissed.
    op.add_column("context_feedback", sa.Column("stage", sa.String(32), nullable=True))
    # The triage read, the proposal and its checks, the proof, and the history of each step.
    op.add_column("context_feedback", sa.Column("loop", postgresql.JSON(), nullable=True))
    op.create_index("ix_context_feedback_stage", "context_feedback", ["stage"])


def downgrade() -> None:
    op.drop_index("ix_context_feedback_stage", table_name="context_feedback")
    op.drop_column("context_feedback", "loop")
    op.drop_column("context_feedback", "stage")
    op.drop_column("context_feedback", "evidence")
