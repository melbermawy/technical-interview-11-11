"""add run events table

Revision ID: 003
Revises: 002
Create Date: 2025-01-17 10:00:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add run_event table for tracking graph execution progress."""
    op.create_table(
        "run_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_run.run_id"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org.org_id"),
            nullable=False,
        ),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("node", sa.Text, nullable=False),
        sa.Column("phase", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
    )

    # Create indexes for efficient querying
    op.create_index("idx_run_event_run_ts", "run_event", ["run_id", "timestamp"])
    op.create_index("idx_run_event_run_seq", "run_event", ["run_id", "sequence"])


def downgrade() -> None:
    """Remove run_event table."""
    op.drop_index("idx_run_event_run_seq", table_name="run_event")
    op.drop_index("idx_run_event_run_ts", table_name="run_event")
    op.drop_table("run_event")
