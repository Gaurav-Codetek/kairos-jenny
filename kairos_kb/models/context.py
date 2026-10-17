"""The context layer: what any agent connected to Kairos reads, and who is reading.

  ContextDocument  one searchable document per entity — its profile, columns
                   and relationships flattened to text, with an embedding and a
                   full-text vector. This is what "find data by meaning" searches.
  AgentClient      an agent registered to use Kairos, identified by an API key.
  AgentActivity    every tool call an agent makes: the audit trail.
  ContextFeedback  an agent's (or person's) report that context is wrong,
                   missing or stale — the loop that makes the map improve with use.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from kairos_kb.db.base import Base

# text-embedding-3-large, shortened. 1536 dimensions keeps an HNSW index
# possible (pgvector indexes up to 2000) at a small cost in recall.
EMBEDDING_DIMENSIONS = 1536


class ContextDocument(Base):
    """The searchable form of one entity."""

    __tablename__ = "context_documents"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(1024), nullable=False)
    # What an agent is shown for a hit: one line on what the entity is.
    headline: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Maintained by the indexer (to_tsvector over name + text, name weighted up).
    search_vector = mapped_column(TSVECTOR, nullable=True)
    embedding = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # profiled + verified | profiled | synced — how much Kairos knows.
    trust_level: Mapped[str] = mapped_column(String(32), nullable=False, default="synced")
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentClient(Base):
    """An agent allowed to read Kairos. The key itself is never stored."""

    __tablename__ = "agent_clients"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # Empty or null: every workspace. Otherwise only these workspace UUIDs.
    workspace_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # read: the map tools. act: reserved for costed actions; no agent-facing tool uses it today.
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, default=lambda: ["read"])
    # Catalogs run_sql may touch for this agent; empty or null: no per-agent limit.
    sql_catalogs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AgentActivity(Base):
    """One call from an agent: which tool, with what, how it went."""

    __tablename__ = "agent_activity"

    # Null for an unauthenticated call (when the server allows those).
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(96), nullable=False)  # mcp | mcp-v2 | mcp:<connection> | rest | eval
    tool: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    arguments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    entity_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # What the call cost the agent: tokens it wrote (arguments) and read back
    # (response), and the estimated price at the configured model's rates.
    args_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    est_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)


class ContextFeedback(Base):
    """A report that the context for an entity is wrong, missing or stale."""

    __tablename__ = "context_feedback"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_clients.id", ondelete="SET NULL"), nullable=True
    )
    reporter: Mapped[str] = mapped_column(String(255), nullable=False)
    # incorrect | missing | stale | confusing | useful
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # open → applied (folded into the next profile) | dismissed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What the reporting agent was asked and which lookups it ran (with their errors): a fix is proven by replaying them.
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # For reports about a data product (kairos_kb/products/fixes.py): new → triaged → proposed | verified, or
    # needs_person / merged / dismissed / rolled_back.
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # The triage read, the proposal and its checks, the proof, and a history of each step.
    loop: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
