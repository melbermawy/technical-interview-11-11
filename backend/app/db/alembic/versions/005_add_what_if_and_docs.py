"""Add what-if threading and docs tables - PR-15 (infra alignment)

Revision ID: 005
Revises: 004
Create Date: 2025-11-19

This migration adds missing schema elements that were added in PR-9A (what-if)
and PR-10A (docs) but never migrated:

1. What-if run threading (PR-9A):
   - agent_run.parent_run_id (self-referential FK)
   - agent_run.scenario_label
   - idx_run_parent index

2. User documents (PR-10A):
   - doc table (doc_id, org_id, user_id, title, kind, created_at)
   - doc_chunk table (chunk_id, doc_id, order, text, section_label)
   - Indexes for efficient querying

Safe to apply on fresh or existing DBs - all columns/tables use nullable or
have defaults where appropriate.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add what-if columns to agent_run and create doc tables."""

    # 1. Add what-if threading columns to agent_run
    op.add_column(
        "agent_run",
        sa.Column(
            "parent_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_run",
        sa.Column("scenario_label", sa.Text(), nullable=True),
    )

    # Add FK constraint for parent_run_id (self-referential)
    op.create_foreign_key(
        "fk_agent_run_parent_run_id",
        "agent_run",
        "agent_run",
        ["parent_run_id"],
        ["run_id"],
    )

    # Add index for parent_run_id lookups
    op.create_index("idx_run_parent", "agent_run", ["parent_run_id"])

    # 2. Create doc table
    op.create_table(
        "doc",
        sa.Column(
            "doc_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="other"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["org.org_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"]),
    )

    # Add index for doc queries
    op.create_index("idx_doc_org_user", "doc", ["org_id", "user_id", "created_at"])

    # 3. Create doc_chunk table
    op.create_table(
        "doc_chunk",
        sa.Column(
            "chunk_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "doc_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("section_label", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["doc_id"], ["doc.doc_id"]),
    )

    # Add indexes for doc_chunk queries
    op.create_index("idx_chunk_doc_order", "doc_chunk", ["doc_id", "order"])
    op.create_index("idx_chunk_doc", "doc_chunk", ["doc_id"])


def downgrade() -> None:
    """Remove what-if columns and doc tables."""
    # Drop doc_chunk table and indexes
    op.drop_index("idx_chunk_doc", table_name="doc_chunk")
    op.drop_index("idx_chunk_doc_order", table_name="doc_chunk")
    op.drop_table("doc_chunk")

    # Drop doc table and indexes
    op.drop_index("idx_doc_org_user", table_name="doc")
    op.drop_table("doc")

    # Drop what-if columns from agent_run
    op.drop_index("idx_run_parent", table_name="agent_run")
    op.drop_constraint("fk_agent_run_parent_run_id", "agent_run", type_="foreignkey")
    op.drop_column("agent_run", "scenario_label")
    op.drop_column("agent_run", "parent_run_id")
