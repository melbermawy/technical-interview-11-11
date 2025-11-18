"""QA plan endpoint - POST /qa/plan (PR-8B)."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.auth import get_current_context
from backend.app.db.context import RequestContext
from backend.app.db.engine import get_session
from backend.app.models.answer import QAPlanResponse, build_qa_plan_response_from_state
from backend.app.models.intent import IntentV1
from backend.app.orchestration.graph import run_graph_stub
from backend.app.orchestration.state import GraphState

router = APIRouter(prefix="/qa", tags=["qa"])
logger = logging.getLogger(__name__)


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
