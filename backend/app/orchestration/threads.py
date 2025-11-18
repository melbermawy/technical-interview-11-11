"""Run thread helpers for what-if scenario tracking (PR-9B)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import AgentRun


async def get_run_thread(
    session: AsyncSession,
    run_id: UUID,
    *,
    org_id: UUID,
    user_id: UUID,
) -> tuple[AgentRun, list[AgentRun]]:
    """Get a run thread: base run + all child scenarios.

    If run_id is a child run, walks up to find the ultimate ancestor (base run).
    Then fetches all children of that base run.

    Args:
        session: Database session
        run_id: Run ID (can be base or child)
        org_id: Organization ID for tenancy enforcement
        user_id: User ID for tenancy enforcement

    Returns:
        Tuple of (base_run, children) where children is sorted by created_at ascending

    Raises:
        ValueError: If run not found or org/user mismatch
    """
    # Fetch the initial run
    result = await session.execute(
        select(AgentRun).where(
            AgentRun.run_id == run_id,
            AgentRun.org_id == org_id,
            AgentRun.user_id == user_id,
        )
    )
    initial_run = result.scalar_one_or_none()

    if not initial_run:
        raise ValueError(f"Run {run_id} not found or access denied")

    # Walk up to find base run (ultimate ancestor)
    base_run = initial_run
    while base_run.parent_run_id is not None:
        result = await session.execute(
            select(AgentRun).where(
                AgentRun.run_id == base_run.parent_run_id,
                AgentRun.org_id == org_id,
                AgentRun.user_id == user_id,
            )
        )
        parent = result.scalar_one_or_none()
        if not parent:
            # Parent not found or access denied - stop here
            break
        base_run = parent

    # Fetch all children of the base run (depth-1 only)
    result = await session.execute(
        select(AgentRun)
        .where(
            AgentRun.parent_run_id == base_run.run_id,
            AgentRun.org_id == org_id,
            AgentRun.user_id == user_id,
        )
        .order_by(AgentRun.created_at.asc(), AgentRun.run_id.asc())
    )
    children = list(result.scalars().all())

    return base_run, children
