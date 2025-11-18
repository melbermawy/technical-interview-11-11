"""Agent run endpoints - POST /runs, SSE streaming, and what-if replanning (PR-9A)."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.auth import get_current_context
from backend.app.db.context import RequestContext
from backend.app.db.engine import get_session
from backend.app.db.models import AgentRun as AgentRunDB
from backend.app.db.run_events import append_run_event, list_run_events
from backend.app.models.events import SSERunEvent
from backend.app.models.intent import IntentV1
from backend.app.models.what_if import WhatIfPatch
from backend.app.orchestration.graph import run_graph_stub
from backend.app.orchestration.state import GraphState
from backend.app.orchestration.threads import get_run_thread
from backend.app.orchestration.what_if import derive_intent_from_what_if

router = APIRouter(prefix="/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    """Request body for POST /runs."""

    prompt: str = Field(..., min_length=1, description="User prompt for trip planning")
    max_days: int | None = Field(None, ge=4, le=7, description="Maximum trip days")
    budget_usd_cents: int | None = Field(None, gt=0, description="Budget in cents")


class CreateRunResponse(BaseModel):
    """Response for POST /runs."""

    run_id: str
    status: str


class RunResponse(BaseModel):
    """Response for GET /runs/{run_id} and thread listing (PR-9B)."""

    run_id: str
    org_id: str
    user_id: str
    status: str
    created_at: datetime
    completed_at: datetime | None
    parent_run_id: str | None = None
    scenario_label: str | None = None


class RunThreadResponse(BaseModel):
    """Response for GET /runs/{run_id}/thread (PR-9B)."""

    base_run: RunResponse
    scenarios: list[RunResponse]


@router.post("", response_model=CreateRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    request: CreateRunRequest,
    ctx: Annotated[RequestContext, Depends(get_current_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CreateRunResponse:
    """Create a new agent run and start graph execution.

    Args:
        request: Run creation request
        ctx: Request context (org_id, user_id)
        session: Database session

    Returns:
        Run ID and status
    """
    # Create agent_run record
    run_id = uuid.uuid4()
    trace_id = f"trace_{run_id.hex[:8]}"

    agent_run = AgentRunDB(
        run_id=run_id,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        intent={"prompt": request.prompt},  # Minimal stub intent
        plan_snapshot=None,
        tool_log=None,
        cost_usd=None,
        trace_id=trace_id,
        status="pending",
        created_at=datetime.utcnow(),
        completed_at=None,
    )
    session.add(agent_run)
    await session.commit()

    # Create initial event
    await append_run_event(
        session,
        run_id=run_id,
        org_id=ctx.org_id,
        sequence=0,
        node="intent",
        phase="started",
        summary="Run created",
    )
    await session.commit()

    # Schedule graph execution in background
    asyncio.create_task(_run_graph_background(run_id, ctx.org_id, ctx.user_id))

    return CreateRunResponse(run_id=str(run_id), status="accepted")


async def _run_graph_background(run_id: uuid.UUID, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Execute graph in background task.

    Args:
        run_id: Run ID
        org_id: Organization ID
        user_id: User ID
    """
    # Get a new session for background task
    from backend.app.db.engine import get_async_engine

    async with AsyncSession(get_async_engine()) as session:
        try:
            # Fetch run to get stored intent (needed for what-if runs)
            result = await session.execute(
                select(AgentRunDB).where(
                    AgentRunDB.run_id == run_id,
                    AgentRunDB.org_id == org_id,
                )
            )
            run_record = result.scalar_one_or_none()

            # Deserialize intent if present
            intent = None
            if run_record and run_record.intent:
                intent = IntentV1.model_validate(run_record.intent)

            # Initialize state
            state = GraphState(
                run_id=run_id,
                org_id=org_id,
                user_id=user_id,
                sequence_counter=1,  # Start at 1 (0 was initial event)
                intent=intent,  # Pre-populate intent from DB (e.g., from what-if)
            )

            # Run graph
            final_state = await run_graph_stub(state, session)

            # Update agent_run status
            await session.execute(
                update(AgentRunDB)
                .where(AgentRunDB.run_id == run_id)
                .where(AgentRunDB.org_id == org_id)
                .values(status=final_state.status, completed_at=datetime.utcnow())
            )
            await session.commit()

        except Exception as e:
            # Log error and update status
            await session.execute(
                update(AgentRunDB)
                .where(AgentRunDB.run_id == run_id)
                .where(AgentRunDB.org_id == org_id)
                .values(status="failed", completed_at=datetime.utcnow())
            )
            await session.commit()

            # Append error event
            await append_run_event(
                session,
                run_id=run_id,
                org_id=org_id,
                sequence=999,  # Error event
                node="responder",
                phase="completed",
                summary=f"Run failed: {str(e)[:100]}",
            )
            await session.commit()


@router.get("/{run_id}/events/stream")
async def stream_run_events(
    run_id: str,
    ctx: Annotated[RequestContext, Depends(get_current_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
    last_ts: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    """Stream run events via SSE.

    Args:
        run_id: Run ID
        ctx: Request context (enforces tenancy)
        session: Database session
        last_ts: Optional ISO8601 timestamp to resume from

    Returns:
        SSE stream
    """
    # Validate run exists and check org access
    run_uuid = uuid.UUID(run_id)

    # First check if run exists at all (without org filter)
    result = await session.execute(select(AgentRunDB).where(AgentRunDB.run_id == run_uuid))
    agent_run = result.scalar_one_or_none()

    if not agent_run:
        # Run doesn't exist anywhere
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    if agent_run.org_id != ctx.org_id:
        # Run exists but belongs to different org
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Parse last_ts if provided
    since_ts: datetime | None = None
    if last_ts:
        try:
            since_ts = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid last_ts format (expected ISO8601)",
            ) from e

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events."""
        last_seen_ts = since_ts
        heartbeat_counter = 0

        while True:
            # Fetch new events
            events = await list_run_events(session, run_uuid, ctx, since_ts=last_seen_ts)

            # Emit events
            for event in events:
                sse_event = SSERunEvent.from_run_event(event)
                yield "event: run_event\n"
                yield f"data: {sse_event.model_dump_json()}\n\n"
                last_seen_ts = event.timestamp

            # Check if run is terminal
            await session.refresh(agent_run)
            if agent_run.status in ("succeeded", "failed", "cancelled"):
                yield "event: done\n"
                yield f'data: {{"status": "{agent_run.status}"}}\n\n'
                break

            # Heartbeat every ~1s
            heartbeat_counter += 1
            if heartbeat_counter % 2 == 0:  # Every other poll cycle
                yield "event: heartbeat\n"
                yield f'data: {{"ts": "{datetime.utcnow().isoformat()}"}}\n\n'

            # Poll interval
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post(
    "/{run_id}/what_if",
    response_model=CreateRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_what_if_run(
    run_id: str,
    patch: WhatIfPatch,
    ctx: Annotated[RequestContext, Depends(get_current_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CreateRunResponse:
    """Create a what-if child run by applying a patch to a base run's intent.

    This endpoint enables what-if replanning: derive a new intent from an existing run
    by applying structured transformations (budget changes, theme adds/removes, date shifts).

    Args:
        run_id: Base run ID to fork from
        patch: Structured intent transformations
        ctx: Request context (org_id, user_id)
        session: Database session

    Returns:
        New run ID and status (same format as POST /runs)

    Raises:
        HTTPException: 404 if base run not found
    """
    # Parse run_id
    try:
        base_run_id = uuid.UUID(run_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid run_id format",
        ) from e

    # Fetch base run
    result = await session.execute(
        select(AgentRunDB).where(
            AgentRunDB.run_id == base_run_id,
            AgentRunDB.org_id == ctx.org_id,  # Enforce tenancy
        )
    )
    base_run = result.scalar_one_or_none()

    if not base_run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Base run not found",
        )

    # Deserialize base intent
    base_intent = IntentV1.model_validate(base_run.intent)

    # Derive new intent
    derived_intent = derive_intent_from_what_if(base_intent, patch)

    # Build scenario label
    scenario_label = patch.notes or "what-if"
    if len(scenario_label) > 100:
        scenario_label = scenario_label[:97] + "..."

    # Create new run record
    new_run_id = uuid.uuid4()
    trace_id = f"trace_{new_run_id.hex[:8]}"

    child_run = AgentRunDB(
        run_id=new_run_id,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        parent_run_id=base_run_id,  # Link to parent
        scenario_label=scenario_label,
        intent=derived_intent.model_dump(mode="json"),  # Serialize derived intent
        plan_snapshot=None,
        tool_log=None,
        cost_usd=None,
        trace_id=trace_id,
        status="pending",
        created_at=datetime.utcnow(),
        completed_at=None,
    )
    session.add(child_run)
    await session.commit()

    # Create initial event
    await append_run_event(
        session,
        run_id=new_run_id,
        org_id=ctx.org_id,
        sequence=0,
        node="intent",
        phase="started",
        summary=f"What-if run created (parent: {base_run_id.hex[:8]})",
    )
    await session.commit()

    # Schedule graph execution in background (reuse existing path)
    asyncio.create_task(_run_graph_background(new_run_id, ctx.org_id, ctx.user_id))

    return CreateRunResponse(run_id=str(new_run_id), status="accepted")


@router.get("/{run_id}/thread", response_model=RunThreadResponse)
async def get_run_thread_endpoint(
    run_id: str,
    ctx: Annotated[RequestContext, Depends(get_current_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunThreadResponse:
    """Get run thread: base run + all what-if scenarios (PR-9B).

    If run_id is a child run, automatically resolves to the base run.
    Returns the base run and all its direct children (depth-1 scenarios).

    Args:
        run_id: Run ID (can be base or child)
        ctx: Request context (enforces tenancy)
        session: Database session

    Returns:
        RunThreadResponse with base_run and scenarios list

    Raises:
        HTTPException: 404 if run not found or access denied
    """
    # Parse run_id
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid run_id format",
        ) from e

    # Get thread using helper
    try:
        base_run, children = await get_run_thread(
            session,
            run_uuid,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e

    # Convert to response DTOs
    def to_run_response(run: AgentRunDB) -> RunResponse:
        return RunResponse(
            run_id=str(run.run_id),
            org_id=str(run.org_id),
            user_id=str(run.user_id),
            status=run.status,
            created_at=run.created_at,
            completed_at=run.completed_at,
            parent_run_id=str(run.parent_run_id) if run.parent_run_id else None,
            scenario_label=run.scenario_label,
        )

    return RunThreadResponse(
        base_run=to_run_response(base_run),
        scenarios=[to_run_response(child) for child in children],
    )
