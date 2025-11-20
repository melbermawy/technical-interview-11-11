"""Integration test for /qa/plan AgentRun creation (FK violation fix).

This test ensures that /qa/plan creates an AgentRun row before inserting
run_event rows, preventing foreign key violations.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.db.models import AgentRun, Base, Org, RunEvent, User
from backend.app.main import app


@pytest_asyncio.fixture
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create test async engine."""
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
async def test_db(test_engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    """Create test database with org and user."""
    async with AsyncSession(test_engine) as session:
        # Create org
        org = Org(
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            name="Test Org",
        )
        session.add(org)

        # Create user
        user = User(
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            org_id=org.org_id,
            email="test@example.com",
            password_hash="dummy",
        )
        session.add(user)

        await session.commit()

    yield test_engine


@pytest.mark.integration
@pytest.mark.asyncio
async def test_qa_plan_creates_agent_run_before_events(test_db: AsyncEngine) -> None:
    """Test that /qa/plan creates AgentRun before logging events (prevents FK violation)."""
    from backend.app.db.engine import get_async_engine, get_session

    # Override get_async_engine to use test engine
    def override_get_async_engine() -> AsyncEngine:
        return test_db

    app.dependency_overrides[get_async_engine] = override_get_async_engine

    # Override get_session to use test engine
    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with AsyncSession(test_db) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    # Mock auth to return test org/user
    from backend.app.api.auth import get_current_context
    from backend.app.db.context import RequestContext

    async def mock_auth() -> RequestContext:
        return RequestContext(
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        )

    app.dependency_overrides[get_current_context] = mock_auth

    try:
        client = TestClient(app)

        # Call /qa/plan with minimal intent
        response = client.post(
            "/qa/plan",
            json={
                "city": "Paris",
                "date_window": {"start": "2025-06-10", "end": "2025-06-14"},
                "budget_usd_cents": 200000,
                "airports": ["CDG"],
                "themes": ["art"],
                "timezone": "Europe/Paris",
            },
        )

        # Assert HTTP 200
        assert (
            response.status_code == 200
        ), f"Expected 200, got {response.status_code}: {response.text}"

        response_data = response.json()
        assert "answer_markdown" in response_data
        assert "itinerary" in response_data

        # Verify AgentRun was created
        async with AsyncSession(test_db) as session:
            result = await session.execute(select(AgentRun))
            agent_runs = result.scalars().all()

            # Should have exactly one AgentRun
            assert len(agent_runs) == 1, f"Expected 1 AgentRun, found {len(agent_runs)}"

            agent_run = agent_runs[0]
            assert agent_run.org_id == uuid.UUID("00000000-0000-0000-0000-000000000001")
            assert agent_run.user_id == uuid.UUID("00000000-0000-0000-0000-000000000002")
            assert agent_run.intent is not None
            assert agent_run.intent["city"] == "Paris"

            # Verify RunEvents exist for this run_id
            result = await session.execute(
                select(RunEvent).where(RunEvent.run_id == agent_run.run_id)
            )
            run_events = result.scalars().all()

            # Should have at least one RunEvent (from graph execution)
            assert len(run_events) > 0, "Expected at least one RunEvent"

            # All events should reference the same run_id
            for event in run_events:
                assert event.run_id == agent_run.run_id

    finally:
        app.dependency_overrides.clear()
