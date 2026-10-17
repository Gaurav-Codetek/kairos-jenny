"""The companion's own records: its live view of the business, and the pulses that built it.

  CompanionState  one per connection: on or off, how often it looks, the business's clock
                  (the time zone its events are written in), the vitals it keeps an eye on,
                  its short-term memory (streaks, what is open today, the last day it closed),
                  and the latest snapshot and headline the screen shows
  CompanionPulse  one look: when, the headline, and each vital's numbers in brief — the
                  day's timeline

What it noticed (moments, daily briefings, stalled data) goes to the same memory stream as
the living agent's notes (AgentNote), so the monthly reflection and the live view share one memory.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from kairos_kb.db.base import Base


class CompanionState(Base):
    __tablename__ = "companion_state"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    # Minutes ahead of UTC that the data's timestamps are written in; inferred from a live stream, or set.
    tz_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tz_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    vitals: Mapped[list | None] = mapped_column(JSON, nullable=True)
    memory: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    headline: Mapped[str | None] = mapped_column(Text, nullable=True)
    headline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_pulse_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    live: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="idle")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CompanionPulse(Base):
    __tablename__ = "companion_pulses"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    headline: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CompanionConversation(Base):
    """A conversation with Jenny — typed, spoken on calls, or both. Kept so a refresh (or a restart)
    picks it up where it was; `history` is what the model saw, in its own message format."""

    __tablename__ = "companion_conversations"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    last_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class CompanionMessage(Base):
    """One line of a conversation: a question, an answer, or a call starting or ending."""

    __tablename__ = "companion_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companion_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    # user · assistant · call (a call starting or ending)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    voice: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    steps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # pending (being answered) · done · error · interrupted (cut off while speaking)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="done")
    # from_memory: answered from an earlier answer to the same question; call: {event, seconds}
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
