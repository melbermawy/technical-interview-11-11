"""Integration tests for POST /qa/plan endpoint (PR-8B)."""

import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.db.models import Base, Org, User
from backend.app.main import app


@pytest_asyncio.fixture
async def test_engine():
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
async def test_db(test_engine):
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
            password_hash="stub",
        )
        session.add(user)

        await session.commit()

    yield test_engine


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def test_qa_plan_returns_200_with_valid_intent(client: TestClient, test_db) -> None:
    """Test POST /qa/plan returns 200 with valid intent."""
    intent_payload = {
        "city": "Paris",
        "date_window": {
            "start": "2025-06-10",
            "end": "2025-06-14",
            "tz": "Europe/Paris",
        },
        "budget_usd_cents": 100000,
        "airports": ["CDG"],
        "prefs": {
            "themes": ["art", "food"],
        },
    }

    response = client.post("/qa/plan", json=intent_payload)

    assert response.status_code == 200
    data = response.json()

    # Verify QAPlanResponse schema
    assert "answer_markdown" in data
    assert "itinerary" in data
    assert "citations" in data
    assert "tools_used" in data
    assert "decisions" in data

    # Verify answer_markdown is non-empty
    assert isinstance(data["answer_markdown"], str)
    assert len(data["answer_markdown"]) > 0

    # Since no OPENAI_API_KEY, should get stub response
    assert "stub" in data["answer_markdown"].lower()

    # Verify itinerary structure
    assert "days" in data["itinerary"]
    assert "total_cost_usd" in data["itinerary"]
    assert isinstance(data["itinerary"]["total_cost_usd"], int)

    # Verify citations is a list (may be empty)
    assert isinstance(data["citations"], list)

    # Verify tools_used is a list (may be empty)
    assert isinstance(data["tools_used"], list)

    # Verify decisions is a list (may be empty)
    assert isinstance(data["decisions"], list)


def test_qa_plan_validates_intent_schema(client: TestClient, test_db) -> None:
    """Test POST /qa/plan returns 422 for invalid intent."""
    # Missing required fields
    invalid_payload = {
        "city": "Paris",
        # Missing date_window, budget_usd_cents, airports
    }

    response = client.post("/qa/plan", json=invalid_payload)

    assert response.status_code == 422


def test_qa_plan_minimal_intent(client: TestClient, test_db) -> None:
    """Test POST /qa/plan with minimal intent (no themes in prefs)."""
    intent_payload = {
        "city": "Tokyo",
        "date_window": {
            "start": "2025-07-01",
            "end": "2025-07-05",
            "tz": "Asia/Tokyo",
        },
        "budget_usd_cents": 200000,
        "airports": ["NRT"],
        "prefs": {},
    }

    response = client.post("/qa/plan", json=intent_payload)

    assert response.status_code == 200
    data = response.json()

    assert data["answer_markdown"]
    assert "itinerary" in data
    assert isinstance(data["itinerary"]["total_cost_usd"], int)


def test_qa_plan_response_has_stable_structure(client: TestClient, test_db) -> None:
    """Test POST /qa/plan returns consistent response structure."""
    intent_payload = {
        "city": "London",
        "date_window": {
            "start": "2025-08-10",
            "end": "2025-08-12",
            "tz": "Europe/London",
        },
        "budget_usd_cents": 150000,
        "airports": ["LHR"],
        "prefs": {
            "themes": ["history"],
        },
    }

    # Make two requests
    response1 = client.post("/qa/plan", json=intent_payload)
    response2 = client.post("/qa/plan", json=intent_payload)

    assert response1.status_code == 200
    assert response2.status_code == 200

    data1 = response1.json()
    data2 = response2.json()

    # Both should have same schema
    assert set(data1.keys()) == set(data2.keys())
    assert set(data1["itinerary"].keys()) == set(data2["itinerary"].keys())


def test_qa_plan_uses_stub_synthesis_without_api_key(client: TestClient, test_db) -> None:
    """Test POST /qa/plan uses stub LLM client when no OPENAI_API_KEY."""
    intent_payload = {
        "city": "Berlin",
        "date_window": {
            "start": "2025-09-01",
            "end": "2025-09-03",
            "tz": "Europe/Berlin",
        },
        "budget_usd_cents": 80000,
        "airports": ["TXL"],
        "prefs": {
            "themes": ["architecture"],
        },
    }

    response = client.post("/qa/plan", json=intent_payload)

    assert response.status_code == 200
    data = response.json()

    # Verify stub marker is present
    answer = data["answer_markdown"]
    assert "stub" in answer.lower() or "placeholder" in answer.lower()


def test_qa_plan_populates_tools_used(client: TestClient, test_db) -> None:
    """Test POST /qa/plan populates tools_used from provenance."""
    intent_payload = {
        "city": "Rome",
        "date_window": {
            "start": "2025-10-15",
            "end": "2025-10-18",
            "tz": "Europe/Rome",
        },
        "budget_usd_cents": 120000,
        "airports": ["FCO"],
        "prefs": {
            "themes": ["history", "food"],
        },
    }

    response = client.post("/qa/plan", json=intent_payload)

    assert response.status_code == 200
    data = response.json()

    # tools_used should be a list of objects with name, count, total_ms
    tools_used = data["tools_used"]
    assert isinstance(tools_used, list)

    # Each tool should have required fields
    for tool in tools_used:
        assert "name" in tool
        assert "count" in tool
        assert "total_ms" in tool
        assert isinstance(tool["count"], int)
        assert tool["count"] > 0


def test_qa_plan_without_auth_uses_default_context(client: TestClient, test_db) -> None:
    """Test POST /qa/plan without auth header uses test defaults."""
    intent_payload = {
        "city": "Barcelona",
        "date_window": {
            "start": "2025-11-01",
            "end": "2025-11-04",
            "tz": "Europe/Madrid",
        },
        "budget_usd_cents": 90000,
        "airports": ["BCN"],
        "prefs": {},
    }

    # No Authorization header
    response = client.post("/qa/plan", json=intent_payload)

    # Should succeed with test defaults per auth.py stub
    assert response.status_code == 200
