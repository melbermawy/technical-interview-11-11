"""Initial schema - PR-2

Revision ID: 001
Revises:
Create Date: 2025-11-13

Creates all tables per SPEC §9.1:
- org, user, refresh_token
- destination, knowledge_item, embedding
- agent_run, itinerary
- idempotency
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables."""
    # org table
    op.create_table(
        "org",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # user table
    op.create_table(
        "user",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["org.org_id"]),
        sa.UniqueConstraint("org_id", "email", name="uq_user_org_email"),
    )
    op.create_index("idx_user_org", "user", ["org_id"])

    # refresh_token table
    op.create_table(
        "refresh_token",
        sa.Column("token_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"], ondelete="CASCADE"),
    )
    op.create_index("idx_refresh_user", "refresh_token", ["user_id", "revoked"])

    # destination table
    op.create_table(
        "destination",
        sa.Column("dest_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("country", sa.Text(), nullable=False),
        sa.Column("geo", postgresql.JSONB(), nullable=False),
        sa.Column("fixture_path", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["org.org_id"]),
        sa.UniqueConstraint("org_id", "city", "country", name="uq_dest_org_city"),
    )

    # knowledge_item table
    op.create_table(
        "knowledge_item",
        sa.Column("item_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dest_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["org.org_id"]),
        sa.ForeignKeyConstraint(["dest_id"], ["destination.dest_id"]),
    )
    op.create_index("idx_knowledge_org_dest", "knowledge_item", ["org_id", "dest_id"])

    # embedding table (pgvector placeholder)
    op.create_table(
        "embedding",
        sa.Column("embedding_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vector", postgresql.ARRAY(sa.Numeric()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["knowledge_item.item_id"], ondelete="CASCADE"),
    )

    # agent_run table
    op.create_table(
        "agent_run",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("intent", postgresql.JSONB(), nullable=False),
        sa.Column("plan_snapshot", postgresql.ARRAY(postgresql.JSONB()), nullable=True),
        sa.Column("tool_log", postgresql.JSONB(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["org.org_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"]),
    )
    op.create_index("idx_run_org_user", "agent_run", ["org_id", "user_id", "created_at"])

    # itinerary table
    op.create_table(
        "itinerary",
        sa.Column("itinerary_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["org.org_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run.run_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"]),
        sa.UniqueConstraint("org_id", "itinerary_id", name="uq_itinerary_org"),
    )
    op.create_index("idx_itinerary_org_user", "itinerary", ["org_id", "user_id", "created_at"])

    # idempotency table
    op.create_table(
        "idempotency",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ttl_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("response_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    # Note: Partial index requires raw SQL or special dialect support
    # This creates a standard index; for partial index, use:
    # CREATE INDEX idx_idempotency_ttl ON idempotency(ttl_until) WHERE status = 'completed';
    op.create_index("idx_idempotency_ttl", "idempotency", ["ttl_until"])


def downgrade() -> None:
    """Drop all tables (not used in PR-2 per spec)."""
    # Note: SPEC says migrations should be additive only during take-home
    # This downgrade is provided for development convenience only
    op.drop_table("idempotency")
    op.drop_table("itinerary")
    op.drop_table("agent_run")
    op.drop_table("embedding")
    op.drop_table("knowledge_item")
    op.drop_table("destination")
    op.drop_table("refresh_token")
    op.drop_table("user")
    op.drop_table("org")
