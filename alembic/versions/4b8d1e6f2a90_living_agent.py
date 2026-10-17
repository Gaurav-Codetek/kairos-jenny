"""living agent: watches, metric observations as they stood, memory notes, runs

Revision ID: 4b8d1e6f2a90
Revises: 9c4e2a7b1d35
Create Date: 2026-10-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "4b8d1e6f2a90"
down_revision: Union[str, None] = "9c4e2a7b1d35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base():
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _ws():
    return sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                     sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)


def upgrade() -> None:
    op.create_table(
        "agent_watches", *_base(), _ws(),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("data_products.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("metric", sa.String(255), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("time_dim", sa.String(255), nullable=False),
        sa.Column("grain", sa.String(16), nullable=False, server_default="month"),
        sa.Column("slices", sa.JSON(), nullable=True),
        sa.Column("good_direction", sa.String(16), nullable=False, server_default="neutral"),
        sa.Column("settle_periods", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("settle_reason", sa.Text(), nullable=True),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("min_impact_pct", sa.Float(), nullable=False, server_default="5"),
        sa.Column("sensitivity", sa.Float(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("origin", sa.String(16), nullable=False, server_default="agent"),
        sa.UniqueConstraint("product_id", "metric", name="uq_agent_watch_metric"),
    )
    op.create_table(
        "agent_observations", *_base(),
        sa.Column("watch_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_watches.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("slice", sa.String(512), nullable=False, server_default=""),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
    )
    op.create_index("ix_agent_obs_series", "agent_observations", ["watch_id", "slice", "period", "as_of"])
    op.create_table(
        "agent_notes", *_base(), _ws(),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("mode", sa.String(16), nullable=False, server_default="live"),
        sa.Column("watch_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_watches.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("data_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False, index=True),
        sa.Column("signal", sa.String(32), nullable=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("facts", sa.JSON(), nullable=True),
        sa.Column("period", sa.Date(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open", index=True),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("feedback", sa.String(16), nullable=True),
        sa.Column("feedback_note", sa.Text(), nullable=True),
        sa.Column("seen", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "agent_runs", *_base(), _ws(),
        sa.Column("mode", sa.String(16), nullable=False, server_default="live"),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("stats", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("agent_runs")
    op.drop_table("agent_notes")
    op.drop_index("ix_agent_obs_series", table_name="agent_observations")
    op.drop_table("agent_observations")
    op.drop_table("agent_watches")
