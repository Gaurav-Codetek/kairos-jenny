"""connector evaluations: runs and their per-question, per-connector threads

Revision ID: a7d4c2e9f531
Revises: d6e2b9f3a148
Create Date: 2026-10-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a7d4c2e9f531"
down_revision: Union[str, None] = "d6e2b9f3a148"
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
        "eval_runs", *_base(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("judge_model", sa.String(128), nullable=False),
        sa.Column("connectors", postgresql.JSON(), nullable=False),
        sa.Column("selection", postgresql.JSON(), nullable=True),
        sa.Column("total_threads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finished_threads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", postgresql.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_eval_runs_status", "eval_runs", ["status"])
    op.create_table(
        "eval_threads", *_base(),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", sa.String(128), nullable=False),
        sa.Column("connector", sa.String(16), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("transcript", postgresql.JSON(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tools_used", postgresql.JSON(), nullable=True),
        sa.Column("tool_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_result_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("step_limit_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mention_score", sa.Float(), nullable=True),
        sa.Column("mentions_missing", postgresql.JSON(), nullable=True),
        sa.Column("judge_score", sa.Float(), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column("missing_context", sa.Text(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_eval_threads_run_id", "eval_threads", ["run_id"])
    op.create_index("ix_eval_threads_case_id", "eval_threads", ["case_id"])
    op.create_index("ix_eval_threads_status", "eval_threads", ["status"])


def downgrade() -> None:
    op.drop_table("eval_threads")
    op.drop_table("eval_runs")
