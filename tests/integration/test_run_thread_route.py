"""Integration tests for GET /runs/{run_id}/thread endpoint (PR-9B)."""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.db.models import AgentRun, Base, Org, User
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
async def test_db_with_thread(
    test_engine: AsyncEngine,
) -> AsyncGenerator[AsyncEngine, None]:
    """Create test database with org, user, base run, and 2 child runs."""
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
            password_hash="stub",
        )
        session.add(user)

        # Create base run
        base_run = AgentRun(
            run_id=uuid.UUID("00000000-0000-0000-0000-000000000100"),
            org_id=org.org_id,
            user_id=user.user_id,
            parent_run_id=None,
            scenario_label=None,
            intent={
                "city": "Paris",
                "date_window": {
                    "start": "2025-06-10",
                    "end": "2025-06-14",
                    "tz": "Europe/Paris",
                },
                "budget_usd_cents": 100000,
                "airports": ["CDG"],
                "prefs": {"themes": ["art", "food"]},
            },
            plan_snapshot=None,
            tool_log=None,
            cost_usd=None,
            trace_id="trace_base",
            status="completed",
            created_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
        )
        session.add(base_run)

        # Create child run 1
        child1 = AgentRun(
            run_id=uuid.UUID("00000000-0000-0000-0000-000000000101"),
            org_id=org.org_id,
            user_id=user.user_id,
            parent_run_id=base_run.run_id,
            scenario_label="Budget +$500",
            intent={
                "city": "Paris",
                "date_window": {
                    "start": "2025-06-10",
                    "end": "2025-06-14",
                    "tz": "Europe/Paris",
                },
                "budget_usd_cents": 150000,
                "airports": ["CDG"],
                "prefs": {"themes": ["art", "food"]},
            },
            plan_snapshot=None,
            tool_log=None,
            cost_usd=None,
            trace_id="trace_child1",
            status="pending",
            created_at=datetime.utcnow() + timedelta(seconds=1),
            completed_at=None,
        )
        session.add(child1)

        # Create child run 2
        child2 = AgentRun(
            run_id=uuid.UUID("00000000-0000-0000-0000-000000000102"),
            org_id=org.org_id,
            user_id=user.user_id,
            parent_run_id=base_run.run_id,
            scenario_label="Shift dates +7 days",
            intent={
                "city": "Paris",
                "date_window": {
                    "start": "2025-06-17",
                    "end": "2025-06-21",
                    "tz": "Europe/Paris",
                },
                "budget_usd_cents": 100000,
                "airports": ["CDG"],
                "prefs": {"themes": ["art", "food"]},
            },
            plan_snapshot=None,
            tool_log=None,
            cost_usd=None,
            trace_id="trace_child2",
            status="pending",
            created_at=datetime.utcnow() + timedelta(seconds=2),
            completed_at=None,
        )
        session.add(child2)

        await session.commit()

    yield test_engine


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


def test_get_run_thread_for_base_run(client: TestClient, test_db_with_thread: Any) -> None:
    """Test GET /runs/{base_run_id}/thread returns base + all scenarios."""
    response = client.get("/runs/00000000-0000-0000-0000-000000000100/thread")

    assert response.status_code == 200
    data = response.json()

    # Verify base_run
    assert "base_run" in data
    assert data["base_run"]["run_id"] == "00000000-0000-0000-0000-000000000100"
    assert data["base_run"]["parent_run_id"] is None
    assert data["base_run"]["scenario_label"] is None
    assert data["base_run"]["status"] == "completed"

    # Verify scenarios
    assert "scenarios" in data
    assert len(data["scenarios"]) == 2

    # Check first scenario
    assert data["scenarios"][0]["run_id"] == "00000000-0000-0000-0000-000000000101"
    assert data["scenarios"][0]["parent_run_id"] == "00000000-0000-0000-0000-000000000100"
    assert data["scenarios"][0]["scenario_label"] == "Budget +$500"

    # Check second scenario
    assert data["scenarios"][1]["run_id"] == "00000000-0000-0000-0000-000000000102"
    assert data["scenarios"][1]["parent_run_id"] == "00000000-0000-0000-0000-000000000100"
    assert data["scenarios"][1]["scenario_label"] == "Shift dates +7 days"


def test_get_run_thread_for_child_run(client: TestClient, test_db_with_thread: Any) -> None:
    """Test GET /runs/{child_run_id}/thread normalizes to base run."""
    # Query using child run ID
    response = client.get("/runs/00000000-0000-0000-0000-000000000101/thread")

    assert response.status_code == 200
    data = response.json()

    # Should still return base run (not the child)
    assert data["base_run"]["run_id"] == "00000000-0000-0000-0000-000000000100"
    assert data["base_run"]["parent_run_id"] is None

    # Should return both child scenarios
    assert len(data["scenarios"]) == 2


def test_get_run_thread_includes_parent_and_scenario_labels(
    client: TestClient, test_db_with_thread: Any
) -> None:
    """Test that response includes parent_run_id and scenario_label fields."""
    response = client.get("/runs/00000000-0000-0000-0000-000000000100/thread")

    assert response.status_code == 200
    data = response.json()

    # Base run
    assert "parent_run_id" in data["base_run"]
    assert "scenario_label" in data["base_run"]
    assert data["base_run"]["parent_run_id"] is None
    assert data["base_run"]["scenario_label"] is None

    # Scenarios
    for scenario in data["scenarios"]:
        assert "parent_run_id" in scenario
        assert "scenario_label" in scenario
        assert scenario["parent_run_id"] is not None
        assert scenario["scenario_label"] is not None


def test_get_run_thread_requires_auth(client: TestClient, test_db_with_thread: Any) -> None:
    """Test that endpoint uses auth context (via stub)."""
    # Without explicit auth header, uses test defaults from auth.py stub
    response = client.get("/runs/00000000-0000-0000-0000-000000000100/thread")

    # Should succeed with test defaults (org_id, user_id match test data)
    assert response.status_code == 200


def test_get_run_thread_404_on_nonexistent_run(
    client: TestClient, test_db_with_thread: Any
) -> None:
    """Test that 404 is returned for nonexistent run."""
    response = client.get("/runs/00000000-0000-0000-0000-000000000999/thread")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_run_thread_400_on_invalid_uuid(client: TestClient, test_db_with_thread: Any) -> None:
    """Test that 400 is returned for invalid UUID format."""
    response = client.get("/runs/invalid-uuid/thread")

    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


def test_get_run_thread_orders_scenarios_by_created_at(
    client: TestClient, test_db_with_thread: Any
) -> None:
    """Test that scenarios are ordered by created_at ascending."""
    response = client.get("/runs/00000000-0000-0000-0000-000000000100/thread")

    assert response.status_code == 200
    data = response.json()

    scenarios = data["scenarios"]
    assert len(scenarios) == 2

    # First scenario (child1) was created 1 second after base
    # Second scenario (child2) was created 2 seconds after base
    assert scenarios[0]["scenario_label"] == "Budget +$500"
    assert scenarios[1]["scenario_label"] == "Shift dates +7 days"


def test_get_run_thread_response_includes_all_run_fields(
    client: TestClient, test_db_with_thread: Any
) -> None:
    """Test that RunResponse includes all expected fields."""
    response = client.get("/runs/00000000-0000-0000-0000-000000000100/thread")

    assert response.status_code == 200
    data = response.json()

    # Check base_run has all RunResponse fields
    base = data["base_run"]
    assert "run_id" in base
    assert "org_id" in base
    assert "user_id" in base
    assert "status" in base
    assert "created_at" in base
    assert "completed_at" in base
    assert "parent_run_id" in base
    assert "scenario_label" in base

    # Check scenarios have same fields
    for scenario in data["scenarios"]:
        assert "run_id" in scenario
        assert "org_id" in scenario
        assert "user_id" in scenario
        assert "status" in scenario
        assert "created_at" in scenario
        assert "completed_at" in scenario
        assert "parent_run_id" in scenario
        assert "scenario_label" in scenario
