"""Helper functions for AgentRun database operations."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import AgentRun as AgentRunDB
from backend.app.orchestration.state import GraphState


async def create_agent_run_for_state(
    session: AsyncSession,
    state: GraphState,
    *,
    status: str = "running",
) -> AgentRunDB:
    """Ensure there's an AgentRun row corresponding to this GraphState.run_id.

    If one already exists, just return it. If not, create it.
    This is needed to satisfy FK constraints for run_event table.

    Args:
        session: Database session
        state: GraphState with run_id, org_id, user_id, intent
        status: Initial status for new runs (default: "running")

    Returns:
        AgentRun instance (either existing or newly created)
    """
    # Check if AgentRun already exists for this run_id
    result = await session.execute(
        select(AgentRunDB).where(AgentRunDB.run_id == state.run_id)
    )
    existing_run = result.scalar_one_or_none()

    if existing_run:
        return existing_run

    # Create new AgentRun
    agent_run = AgentRunDB(
        run_id=state.run_id,
        org_id=state.org_id,
        user_id=state.user_id,
        intent=state.intent.model_dump(mode="json") if state.intent else None,
        plan_snapshot=None,
        tool_log=None,
        cost_usd=None,
        trace_id=f"trace_{state.run_id.hex[:8]}",
        status=status,
        created_at=datetime.utcnow(),
        completed_at=None,
    )

    session.add(agent_run)
    await session.flush()

    return agent_run
