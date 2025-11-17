"""SQLAlchemy ORM models matching SPEC §9.1."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class Org(Base):
    """Organization table - top-level tenancy boundary."""

    __tablename__ = "org"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    users: Mapped[list["User"]] = relationship("User", back_populates="org")
    destinations: Mapped[list["Destination"]] = relationship(
        "Destination", back_populates="org"
    )
    knowledge_items: Mapped[list["KnowledgeItem"]] = relationship(
        "KnowledgeItem", back_populates="org"
    )
    agent_runs: Mapped[list["AgentRun"]] = relationship("AgentRun", back_populates="org")
    itineraries: Mapped[list["Itinerary"]] = relationship("Itinerary", back_populates="org")


class User(Base):
    """User table - org-scoped user accounts."""

    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_user_org_email"),
        Index("idx_user_org", "org_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org.org_id"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    org: Mapped["Org"] = relationship("Org", back_populates="users")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    agent_runs: Mapped[list["AgentRun"]] = relationship("AgentRun", back_populates="user")
    itineraries: Mapped[list["Itinerary"]] = relationship("Itinerary", back_populates="user")


class RefreshToken(Base):
    """Refresh token table - for JWT rotation."""

    __tablename__ = "refresh_token"
    __table_args__ = (Index("idx_refresh_user", "user_id", "revoked"),)

    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")


class Destination(Base):
    """Destination table - org-scoped city/country data."""

    __tablename__ = "destination"
    __table_args__ = (UniqueConstraint("org_id", "city", "country", name="uq_dest_org_city"),)

    dest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org.org_id"), nullable=False
    )
    city: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    geo: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fixture_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    org: Mapped["Org"] = relationship("Org", back_populates="destinations")
    knowledge_items: Mapped[list["KnowledgeItem"]] = relationship(
        "KnowledgeItem", back_populates="destination"
    )


class KnowledgeItem(Base):
    """Knowledge item table - RAG content."""

    __tablename__ = "knowledge_item"
    __table_args__ = (Index("idx_knowledge_org_dest", "org_id", "dest_id"),)

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org.org_id"), nullable=False
    )
    dest_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("destination.dest_id"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    org: Mapped["Org"] = relationship("Org", back_populates="knowledge_items")
    destination: Mapped["Destination | None"] = relationship(
        "Destination", back_populates="knowledge_items"
    )
    embeddings: Mapped[list["Embedding"]] = relationship(
        "Embedding", back_populates="knowledge_item", cascade="all, delete-orphan"
    )


class Embedding(Base):
    """Embedding table - pgvector embeddings for RAG."""

    __tablename__ = "embedding"

    embedding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_item.item_id", ondelete="CASCADE"),
        nullable=False,
    )
    # Note: vector column requires pgvector extension
    # This is a placeholder; actual pgvector integration would use pgvector types
    vector: Mapped[list[float] | None] = mapped_column(ARRAY(Numeric), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    knowledge_item: Mapped["KnowledgeItem"] = relationship(
        "KnowledgeItem", back_populates="embeddings"
    )


class AgentRun(Base):
    """Agent run table - LangGraph execution state."""

    __tablename__ = "agent_run"
    __table_args__ = (Index("idx_run_org_user", "org_id", "user_id", "created_at"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org.org_id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.user_id"), nullable=False
    )
    intent: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    plan_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(
        ARRAY(JSONB), nullable=True
    )
    tool_log: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    trace_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    org: Mapped["Org"] = relationship("Org", back_populates="agent_runs")
    user: Mapped["User"] = relationship("User", back_populates="agent_runs")
    itineraries: Mapped[list["Itinerary"]] = relationship("Itinerary", back_populates="agent_run")


class Itinerary(Base):
    """Itinerary table - final generated travel plans."""

    __tablename__ = "itinerary"
    __table_args__ = (
        UniqueConstraint("org_id", "itinerary_id", name="uq_itinerary_org"),
        Index("idx_itinerary_org_user", "org_id", "user_id", "created_at"),
    )

    itinerary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org.org_id"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_run.run_id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.user_id"), nullable=False
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    org: Mapped["Org"] = relationship("Org", back_populates="itineraries")
    agent_run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="itineraries")
    user: Mapped["User"] = relationship("User", back_populates="itineraries")


class Idempotency(Base):
    """Idempotency table - request deduplication with full response replay."""

    __tablename__ = "idempotency"
    __table_args__ = (
        Index(
            "idx_idempotency_ttl",
            "ttl_until",
            postgresql_where=Column("status") == "completed",
        ),
    )

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ttl_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    # Full response envelope stored as JSONB for replay
    response_envelope: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RunEvent(Base):
    """Run event table - tracks graph execution progress."""

    __tablename__ = "run_event"
    __table_args__ = (
        Index("idx_run_event_run_ts", "run_id", "timestamp"),
        Index("idx_run_event_run_seq", "run_id", "sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_run.run_id"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org.org_id"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    node: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
