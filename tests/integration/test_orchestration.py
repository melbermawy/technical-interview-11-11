"""Tests for orchestration graph and run events - PR-4A."""

import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.db.models import Base
from backend.app.db.run_events import append_run_event, list_run_events
from backend.app.orchestration.graph import run_graph_stub
from backend.app.orchestration.state import GraphState


@pytest_asyncio.fixture
async def test_engine():
    """Create test async engine with in-memory SQLite."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=NullPool,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine):
    """Create test async session."""
    async with AsyncSession(test_engine) as session:
        yield session


@pytest.mark.asyncio
async def test_graph_event_sequence(test_session: AsyncSession) -> None:
    """Test that graph execution produces expected event sequence.

    Verifies:
    - Events are emitted for each node
    - Sequence is monotonic
    - Final status is succeeded
    """
    run_id = uuid.uuid4()
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    state = GraphState(
        run_id=run_id,
        org_id=org_id,
        user_id=user_id,
    )

    # Run graph
    final_state = await run_graph_stub(state, test_session)
    await test_session.commit()

    # Assert final status
    assert final_state.status == "succeeded"
    assert final_state.intent is not None
    assert final_state.plan is not None
    assert len(final_state.violations) == 0

    # Fetch events
    from backend.app.db.context import RequestContext

    ctx = RequestContext(org_id=org_id, user_id=user_id)
    events = await list_run_events(test_session, run_id, ctx)

    # Verify event sequence
    assert len(events) > 0, "Should have emitted events"

    # Check monotonic sequence
    for i, event in enumerate(events):
        assert event.sequence == i, f"Sequence should be {i}, got {event.sequence}"

    # Check expected nodes in order
    expected_nodes = [
        "intent",
        "intent",
        "planner",
        "planner",
        "selector",
        "selector",
        "tool_exec",
        "tool_exec",
        "verifier",
        "verifier",
        "synth",
        "synth",
        "responder",
        "responder",
    ]

    node_sequence = [e.node for e in events]
    assert node_sequence == expected_nodes, f"Expected {expected_nodes}, got {node_sequence}"

    # Check phases alternate between started/completed
    for i in range(0, len(events), 2):
        assert events[i].phase == "started", f"Event {i} should be started"
        assert events[i + 1].phase == "completed", f"Event {i+1} should be completed"


@pytest.mark.asyncio
async def test_run_events_since_ts_filter(test_session: AsyncSession) -> None:
    """Test that list_run_events correctly filters by timestamp."""
    run_id = uuid.uuid4()
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    from backend.app.db.context import RequestContext

    ctx = RequestContext(org_id=org_id, user_id=user_id)

    # Create events at different times
    await append_run_event(
        test_session,
        run_id=run_id,
        org_id=org_id,
        sequence=0,
        node="intent",
        phase="started",
        summary="Event 1",
    )
    await test_session.commit()

    # Get timestamp after first event
    mid_ts = datetime.utcnow()

    await append_run_event(
        test_session,
        run_id=run_id,
        org_id=org_id,
        sequence=1,
        node="intent",
        phase="completed",
        summary="Event 2",
    )
    await test_session.commit()

    # Fetch all events
    all_events = await list_run_events(test_session, run_id, ctx)
    assert len(all_events) == 2

    # Fetch events after mid_ts (should only get event 2)
    recent_events = await list_run_events(test_session, run_id, ctx, since_ts=mid_ts)
    assert len(recent_events) == 1
    assert recent_events[0].summary == "Event 2"


@pytest.mark.asyncio
async def test_run_events_tenancy_isolation(test_session: AsyncSession) -> None:
    """Test that list_run_events enforces org isolation."""
    run_id = uuid.uuid4()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    from backend.app.db.context import RequestContext

    # Create event for org_a
    await append_run_event(
        test_session,
        run_id=run_id,
        org_id=org_a,
        sequence=0,
        node="intent",
        phase="started",
        summary="Org A event",
    )
    await test_session.commit()

    # org_a can see it
    ctx_a = RequestContext(org_id=org_a, user_id=user_a)
    events_a = await list_run_events(test_session, run_id, ctx_a)
    assert len(events_a) == 1

    # org_b cannot see it
    ctx_b = RequestContext(org_id=org_b, user_id=user_b)
    events_b = await list_run_events(test_session, run_id, ctx_b)
    assert len(events_b) == 0
