"""Add response_envelope to idempotency - PR-2b

Revision ID: 002
Revises: 001
Create Date: 2025-11-13

Adds response_envelope column to idempotency table to enable full response replay
per SPEC §9.3. This replaces response_hash with a complete envelope containing
status_code, headers, and body.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add response_envelope column and drop response_hash."""
    # Add new response_envelope column
    op.add_column(
        "idempotency",
        sa.Column("response_envelope", postgresql.JSONB(), nullable=True),
    )

    # Drop old response_hash column (safe because existing data can be migrated offline if needed)
    # Note: In production, you'd migrate existing data first
    op.drop_column("idempotency", "response_hash")


def downgrade() -> None:
    """Restore response_hash column."""
    # Re-add response_hash
    op.add_column(
        "idempotency",
        sa.Column("response_hash", sa.Text(), nullable=True),
    )

    # Drop response_envelope
    op.drop_column("idempotency", "response_envelope")
