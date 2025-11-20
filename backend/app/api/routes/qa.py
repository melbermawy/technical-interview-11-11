"""QA plan endpoint - POST /qa/plan (PR-8B), GET /qa/plan/{run_id} (PR-13A)."""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.auth import get_current_context
from backend.app.db.agent_runs import create_agent_run_for_state
from backend.app.db.context import RequestContext
from backend.app.db.engine import get_session
from backend.app.db.models import AgentRun as AgentRunDB
from backend.app.models.answer import AnswerV1, QAPlanResponse, build_qa_plan_response_from_state
from backend.app.models.docs import DocChunk
from backend.app.models.intent import IntentV1
from backend.app.models.itinerary import Citation, Decision
from backend.app.models.plan import Choice, PlanV1
from backend.app.models.tool_results import WeatherDay
from backend.app.models.tools import ToolCallLog
from backend.app.models.violations import Violation
from backend.app.orchestration.graph import run_graph_stub
from backend.app.orchestration.state import GraphState

router = APIRouter(prefix="/qa", tags=["qa"])
logger = logging.getLogger(__name__)


def deserialize_graph_state(state_json: dict[str, Any]) -> GraphState:
    """Deserialize GraphState from JSON dict (PR-13A).

    Args:
        state_json: Dict representation of GraphState

    Returns:
        GraphState instance

    Raises:
        ValueError: If deserialization fails
    """
    try:
        # Parse UUIDs
        run_id = uuid.UUID(state_json["run_id"])
        org_id = uuid.UUID(state_json["org_id"])
        user_id = uuid.UUID(state_json["user_id"])

        # Parse Pydantic models
        intent = IntentV1.model_validate(state_json["intent"]) if state_json.get("intent") else None
        answer = AnswerV1.model_validate(state_json["answer"]) if state_json.get("answer") else None
        plan = PlanV1.model_validate(state_json["plan"]) if state_json.get("plan") else None

        # Parse lists of Pydantic models
        choices = [Choice.model_validate(c) for c in state_json.get("choices", [])]
        weather = [WeatherDay.model_validate(w) for w in state_json.get("weather", [])]
        violations = [Violation.model_validate(v) for v in state_json.get("violations", [])]
        decisions = [Decision.model_validate(d) for d in state_json.get("decisions", [])]
        citations = [Citation.model_validate(c) for c in state_json.get("citations", [])]
        doc_matches = [DocChunk.model_validate(d) for d in state_json.get("doc_matches", [])]
        tool_calls = [ToolCallLog.model_validate(t) for t in state_json.get("tool_calls", [])]

        # Reconstruct GraphState
        # Handle optional datetime fields
        from datetime import datetime as dt

        created_at = state_json.get("created_at")
        updated_at = state_json.get("updated_at")

        # Parse datetime strings if present
        if created_at and isinstance(created_at, str):
            created_at = dt.fromisoformat(created_at.replace("Z", "+00:00"))
        if updated_at and isinstance(updated_at, str):
            updated_at = dt.fromisoformat(updated_at.replace("Z", "+00:00"))

        return GraphState(
            run_id=run_id,
            org_id=org_id,
            user_id=user_id,
            intent=intent,
            plan=plan,
            choices=choices,
            weather=weather,
            violations=violations,
            has_blocking_violations=state_json.get("has_blocking_violations", False),
            decisions=decisions,
            selector_logs=state_json.get("selector_logs", []),
            answer=answer,
            citations=citations,
            doc_matches=doc_matches,
            tool_calls=tool_calls,
            rng_seed=state_json.get("rng_seed", 42),
            sequence_counter=state_json.get("sequence_counter", 0),
            status=state_json.get("status", "succeeded"),
            created_at=created_at or dt.utcnow(),
            updated_at=updated_at or dt.utcnow(),
        )
    except (KeyError, ValueError, TypeError) as e:
        raise ValueError(f"Failed to deserialize GraphState: {e}") from e


@router.post("/plan", response_model=QAPlanResponse, status_code=status.HTTP_200_OK)
async def create_plan(
    intent: IntentV1,
    ctx: Annotated[RequestContext, Depends(get_current_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QAPlanResponse:
    """Generate a travel plan from user intent.

    Runs the full orchestrator graph (planner → selector → verifiers → synth)
    and returns a structured response with itinerary, citations, and decisions.

    Args:
        intent: User's travel intent (destination, dates, budget, preferences)
        ctx: Request context (org_id, user_id from auth)
        session: Database session

    Returns:
        QAPlanResponse with answer_markdown, itinerary, citations, tools_used, decisions

    Raises:
        HTTPException: 500 if graph execution fails
    """
    run_id = uuid.uuid4()

    logger.info(f"[POST /qa/plan] run_id={run_id}, city={intent.city}")

    try:
        # Initialize graph state with the incoming intent
        state = GraphState(
            run_id=run_id,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            intent=intent,
        )

        # Ensure AgentRun exists before any run_event inserts (prevents FK violation)
        await create_agent_run_for_state(session, state)

        # Run the full orchestrator graph
        final_state = await run_graph_stub(state, session)

        # Convert final state to QAPlanResponse
        response = build_qa_plan_response_from_state(final_state)

        logger.info(
            f"[POST /qa/plan] run_id={run_id} succeeded, "
            f"{len(response.citations)} citations, "
            f"{len(response.decisions)} decisions"
        )

        return response

    except Exception as e:
        logger.error(f"[POST /qa/plan] run_id={run_id} failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="internal error",
        ) from e


@router.get("/plan/{run_id}", response_model=QAPlanResponse, status_code=status.HTTP_200_OK)
async def get_plan_by_run_id(
    run_id: str,
    ctx: Annotated[RequestContext, Depends(get_current_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QAPlanResponse:
    """Retrieve QAPlanResponse for a completed run by run_id (PR-13A).

    Does NOT re-run the graph - retrieves the persisted final state.

    Args:
        run_id: Run ID (UUID string)
        ctx: Request context (org_id, user_id from auth)
        session: Database session

    Returns:
        QAPlanResponse built from stored GraphState

    Raises:
        HTTPException: 400 for invalid UUID, 404 if not found, 409 if not completed
    """
    # Parse UUID
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid run_id format (expected UUID)",
        ) from e

    logger.info(f"[GET /qa/plan/{run_id}] org_id={ctx.org_id}, user_id={ctx.user_id}")

    # Fetch run with tenancy enforcement
    result = await session.execute(
        select(AgentRunDB).where(
            AgentRunDB.run_id == run_uuid,
            AgentRunDB.org_id == ctx.org_id,
            AgentRunDB.user_id == ctx.user_id,
        )
    )
    agent_run = result.scalar_one_or_none()

    if not agent_run:
        # Not found or out of tenancy
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    # Check if completed
    if agent_run.status != "succeeded":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run not completed yet",
        )

    # Check if final state exists
    if not agent_run.final_state_json:
        logger.error(f"[GET /qa/plan/{run_id}] Run succeeded but no final_state_json")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="internal error",
        )

    # Deserialize GraphState
    try:
        graph_state = deserialize_graph_state(agent_run.final_state_json)
    except ValueError as e:
        logger.error(f"[GET /qa/plan/{run_id}] Failed to deserialize state: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="internal error",
        ) from e

    # Build QAPlanResponse
    response = build_qa_plan_response_from_state(graph_state)

    logger.info(
        f"[GET /qa/plan/{run_id}] Retrieved response with "
        f"{len(response.citations)} citations, "
        f"{len(response.violations)} violations"
    )

    return response
