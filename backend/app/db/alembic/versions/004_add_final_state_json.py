"""Add final_state_json to agent_run for PR-13A.

Revision ID: 004
Revises: 003
Create Date: 2025-11-19

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add final_state_json column to agent_run table."""
    op.add_column(
        "agent_run",
        sa.Column("final_state_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Remove final_state_json column from agent_run table."""
    op.drop_column("agent_run", "final_state_json")
