"""Connector evaluations: many questions, asked through each MCP server, every step kept.

  EvalRun     one evaluation: a question set asked through one or more connectors
              (v1 /mcp, v2 /mcp-v2) by one model, with totals as it goes
  EvalThread  one question through one connector: the full conversation (the
              agent's text, each tool call with its arguments and result), the
              final answer, and how it scored
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from kairos_kb.db.base import Base


class EvalRun(Base):
    __tablename__ = "eval_runs"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # queued · running · completed · failed · cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    judge_model: Mapped[str] = mapped_column(String(128), nullable=False)
    # Which connectors were asked: ["v1", "v2"]
    connectors: Mapped[list] = mapped_column(JSON, nullable=False)
    # The questions asked, as chosen when the run started (ids and filters).
    selection: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_threads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    finished_threads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Per connector: {"v1": {"passed": 0, "score_sum": 0.0, "tokens": 0, "tool_calls": 0, ...}}
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalThread(Base):
    __tablename__ = "eval_threads"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    connector: Mapped[str] = mapped_column(String(96), nullable=False)  # v1 | v2 | c:<connection slug>
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    # queued · running · answered · scored · failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    # The conversation, in order: [{"type": "text"|"tool_call"|"answer", ...}]
    transcript: Mapped[list | None] = mapped_column(JSON, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tools_used: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tool_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Tokens the model read and wrote for this thread, and what tool results added to its context.
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_result_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_limit_hit: Mapped[bool] = mapped_column(nullable=False, default=False)
    # Scoring: deterministic mentions, then an LLM judge against the reference.
    mention_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    mentions_missing: Mapped[list | None] = mapped_column(JSON, nullable=True)
    judge_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    missing_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    passed: Mapped[bool | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
