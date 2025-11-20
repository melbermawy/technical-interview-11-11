"""Integration tests for GET /qa/plan/{run_id} endpoint (PR-13A)."""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
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
async def test_db(test_engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    """Create test database with org, user, and completed run with final_state_json."""
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

        # Create a second org and user for tenancy tests
        org2 = Org(
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
            name="Other Org",
        )
        session.add(org2)

        user2 = User(
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000004"),
            org_id=org2.org_id,
            email="other@example.com",
            password_hash="stub",
        )
        session.add(user2)

        # Create completed run with well-formed final_state_json
        completed_run = AgentRun(
            run_id=uuid.UUID("00000000-0000-0000-0000-000000000100"),
            org_id=org.org_id,
            user_id=user.user_id,
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
            trace_id="trace_100",
            status="succeeded",
            created_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            final_state_json={
                "run_id": "00000000-0000-0000-0000-000000000100",
                "org_id": "00000000-0000-0000-0000-000000000001",
                "user_id": "00000000-0000-0000-0000-000000000002",
                "intent": {
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
                "answer": {
                    "answer_markdown": "# Paris Trip Itinerary\n\nStub answer for testing.",
                    "decisions": ["Selected budget flights", "Chose central hotel"],
                    "synthesis_source": "stub",
                },
                "plan": None,
                "choices": [],
                "weather": [],
                "violations": [],
                "has_blocking_violations": False,
                "decisions": [],
                "selector_logs": [],
                "citations": [
                    {
                        "choice_id": "flight_1",
                        "source": "adapter.flights",
                        "snippet": "AF123 Paris CDG",
                    }
                ],
                "doc_matches": [],
                "tool_calls": [
                    {
                        "name": "adapter.flights",
                        "started_at": "2025-01-01T00:00:00Z",
                        "finished_at": "2025-01-01T00:00:01Z",
                        "duration_ms": 100,
                        "success": True,
                    },
                    {
                        "name": "adapter.flights",
                        "started_at": "2025-01-01T00:00:02Z",
                        "finished_at": "2025-01-01T00:00:03Z",
                        "duration_ms": 200,
                        "success": True,
                    },
                ],
                "rng_seed": 42,
                "sequence_counter": 5,
                "status": "succeeded",
            },
        )
        session.add(completed_run)

        # Create pending run (for 409 test)
        pending_run = AgentRun(
            run_id=uuid.UUID("00000000-0000-0000-0000-000000000200"),
            org_id=org.org_id,
            user_id=user.user_id,
            intent={"prompt": "Pending trip"},
            plan_snapshot=None,
            tool_log=None,
            cost_usd=None,
            trace_id="trace_200",
            status="pending",
            created_at=datetime.utcnow(),
            completed_at=None,
            final_state_json=None,
        )
        session.add(pending_run)

        # Create completed run owned by org2 (for tenancy test)
        other_org_run = AgentRun(
            run_id=uuid.UUID("00000000-0000-0000-0000-000000000300"),
            org_id=org2.org_id,
            user_id=user2.user_id,
            intent={"city": "London"},
            plan_snapshot=None,
            tool_log=None,
            cost_usd=None,
            trace_id="trace_300",
            status="succeeded",
            created_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            final_state_json={
                "run_id": "00000000-0000-0000-0000-000000000300",
                "org_id": "00000000-0000-0000-0000-000000000003",
                "user_id": "00000000-0000-0000-0000-000000000004",
                "intent": {"city": "London"},
                "answer": {
                    "answer_markdown": "London trip",
                    "decisions": [],
                    "synthesis_source": "stub",
                },
                "plan": None,
                "choices": [],
                "weather": [],
                "violations": [],
                "has_blocking_violations": False,
                "decisions": [],
                "selector_logs": [],
                "citations": [],
                "doc_matches": [],
                "tool_calls": [],
                "rng_seed": 42,
                "sequence_counter": 1,
                "status": "succeeded",
            },
        )
        session.add(other_org_run)

        await session.commit()

    yield test_engine


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


def test_qa_plan_by_run_id_returns_response_for_completed_run(
    client: TestClient, test_db: Any
) -> None:
    """Test GET /qa/plan/{run_id} returns 200 with QAPlanResponse for completed run."""
    response = client.get("/qa/plan/00000000-0000-0000-0000-000000000100")

    assert response.status_code == 200
    data = response.json()

    # Verify QAPlanResponse schema
    assert "answer_markdown" in data
    assert "itinerary" in data
    assert "citations" in data
    assert "tools_used" in data
    assert "decisions" in data
    assert "violations" in data
    assert "has_blocking_violations" in data

    # Verify deserialized content matches stored state
    assert data["answer_markdown"] == "# Paris Trip Itinerary\n\nStub answer for testing."
    assert data["decisions"] == ["Selected budget flights", "Chose central hotel"]

    # Verify citations
    assert len(data["citations"]) == 1
    assert data["citations"][0]["choice_id"] == "flight_1"
    assert data["citations"][0]["source"] == "adapter.flights"

    # Verify tools_used is aggregated correctly
    assert len(data["tools_used"]) == 1
    assert data["tools_used"][0]["name"] == "adapter.flights"
    assert data["tools_used"][0]["count"] == 2
    assert data["tools_used"][0]["total_ms"] == 300

    # Verify violations (should be empty for this test)
    assert data["violations"] == []
    assert data["has_blocking_violations"] is False


def test_qa_plan_by_run_id_404_for_missing_run(client: TestClient, test_db: Any) -> None:
    """Test GET /qa/plan/{run_id} returns 404 for nonexistent run."""
    response = client.get("/qa/plan/00000000-0000-0000-0000-999999999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_qa_plan_by_run_id_400_for_invalid_uuid(client: TestClient, test_db: Any) -> None:
    """Test GET /qa/plan/{run_id} returns 400 for malformed UUID."""
    response = client.get("/qa/plan/not-a-valid-uuid")

    assert response.status_code == 400
    assert "Invalid run_id format" in response.json()["detail"]


def test_qa_plan_by_run_id_409_for_non_completed_run(client: TestClient, test_db: Any) -> None:
    """Test GET /qa/plan/{run_id} returns 409 for pending run."""
    response = client.get("/qa/plan/00000000-0000-0000-0000-000000000200")

    assert response.status_code == 409
    assert "Run not completed yet" in response.json()["detail"]


def test_qa_plan_by_run_id_enforces_tenancy(client: TestClient, test_db: Any) -> None:
    """Test GET /qa/plan/{run_id} returns 404 for run owned by different org/user.

    Uses default test org/user (org_id=...001, user_id=...002) to query run
    owned by org2/user2 (org_id=...003, user_id=...004).
    """
    # Try to access run owned by org2/user2
    response = client.get("/qa/plan/00000000-0000-0000-0000-000000000300")

    # Should return 404 (not found due to tenancy filter)
    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_qa_plan_by_run_id_stable_structure(client: TestClient, test_db: Any) -> None:
    """Test GET /qa/plan/{run_id} returns consistent structure on repeated calls."""
    response1 = client.get("/qa/plan/00000000-0000-0000-0000-000000000100")
    response2 = client.get("/qa/plan/00000000-0000-0000-0000-000000000100")

    assert response1.status_code == 200
    assert response2.status_code == 200

    data1 = response1.json()
    data2 = response2.json()

    # Both should have same schema
    assert set(data1.keys()) == set(data2.keys())

    # Content should be identical (no randomness in retrieval)
    assert data1["answer_markdown"] == data2["answer_markdown"]
    assert data1["citations"] == data2["citations"]
    assert data1["tools_used"] == data2["tools_used"]
