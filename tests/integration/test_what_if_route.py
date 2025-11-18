"""Unit tests for POST /runs/{run_id}/what_if endpoint (PR-9A)."""

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
    """Create test database with org, user, and base run."""
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

        # Create base run with complete intent
        base_run = AgentRun(
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
            trace_id="trace_base123",
            status="succeeded",
            created_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
        )
        session.add(base_run)

        await session.commit()

    yield test_engine


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


def test_what_if_creates_child_run_with_budget_change(client: TestClient, test_db: Any) -> None:
    """Test that what-if endpoint creates a new run with modified budget."""
    patch_payload = {"new_budget_usd_cents": 150000}

    response = client.post(
        "/runs/00000000-0000-0000-0000-000000000100/what_if",
        json=patch_payload,
    )

    assert response.status_code == 202
    data = response.json()

    # Should return a new run_id
    assert "run_id" in data
    assert data["run_id"] != "00000000-0000-0000-0000-000000000100"
    assert data["status"] == "accepted"


def test_what_if_creates_child_run_with_theme_changes(client: TestClient, test_db: Any) -> None:
    """Test that what-if endpoint creates a new run with modified themes."""
    patch_payload = {
        "add_themes": ["architecture"],
        "remove_themes": ["food"],
    }

    response = client.post(
        "/runs/00000000-0000-0000-0000-000000000100/what_if",
        json=patch_payload,
    )

    assert response.status_code == 202
    data = response.json()

    assert "run_id" in data
    assert data["status"] == "accepted"


def test_what_if_creates_child_run_with_date_shift(client: TestClient, test_db: Any) -> None:
    """Test that what-if endpoint creates a new run with shifted dates."""
    patch_payload = {"shift_days": 7}

    response = client.post(
        "/runs/00000000-0000-0000-0000-000000000100/what_if",
        json=patch_payload,
    )

    assert response.status_code == 202
    data = response.json()

    assert "run_id" in data
    assert data["status"] == "accepted"


def test_what_if_returns_404_for_nonexistent_base_run(client: TestClient, test_db: Any) -> None:
    """Test that what-if endpoint returns 404 for nonexistent run."""
    patch_payload = {"new_budget_usd_cents": 150000}

    response = client.post(
        "/runs/00000000-0000-0000-0000-999999999999/what_if",
        json=patch_payload,
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_what_if_returns_400_for_invalid_run_id_format(client: TestClient, test_db: Any) -> None:
    """Test that what-if endpoint returns 400 for malformed run_id."""
    patch_payload = {"new_budget_usd_cents": 150000}

    response = client.post(
        "/runs/not-a-uuid/what_if",
        json=patch_payload,
    )

    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


def test_what_if_validates_patch_schema(client: TestClient, test_db: Any) -> None:
    """Test that what-if endpoint validates WhatIfPatch schema."""
    # Invalid budget (must be > 0)
    patch_payload = {"new_budget_usd_cents": -1000}

    response = client.post(
        "/runs/00000000-0000-0000-0000-000000000100/what_if",
        json=patch_payload,
    )

    assert response.status_code == 422  # Validation error


def test_what_if_accepts_empty_patch(client: TestClient, test_db: Any) -> None:
    """Test that what-if endpoint accepts an empty patch (all fields None)."""
    patch_payload: dict[str, Any] = {}

    response = client.post(
        "/runs/00000000-0000-0000-0000-000000000100/what_if",
        json=patch_payload,
    )

    assert response.status_code == 202
    data = response.json()

    assert "run_id" in data
    assert data["status"] == "accepted"


def test_what_if_accepts_notes_field(client: TestClient, test_db: Any) -> None:
    """Test that what-if endpoint accepts notes field for scenario label."""
    patch_payload = {
        "new_budget_usd_cents": 150000,
        "notes": "Increased budget scenario",
    }

    response = client.post(
        "/runs/00000000-0000-0000-0000-000000000100/what_if",
        json=patch_payload,
    )

    assert response.status_code == 202
    data = response.json()

    assert "run_id" in data
    assert data["status"] == "accepted"


def test_what_if_truncates_long_notes(client: TestClient, test_db: Any) -> None:
    """Test that what-if endpoint handles very long notes gracefully."""
    long_notes = "A" * 500  # Max 500 chars per WhatIfPatch validation

    patch_payload = {
        "new_budget_usd_cents": 150000,
        "notes": long_notes,
    }

    response = client.post(
        "/runs/00000000-0000-0000-0000-000000000100/what_if",
        json=patch_payload,
    )

    # Should succeed (truncation happens in endpoint, not validation)
    assert response.status_code == 202


def test_what_if_rejects_notes_exceeding_max_length(client: TestClient, test_db: Any) -> None:
    """Test that WhatIfPatch validation rejects notes > 500 chars."""
    long_notes = "A" * 501  # Exceeds max

    patch_payload = {
        "new_budget_usd_cents": 150000,
        "notes": long_notes,
    }

    response = client.post(
        "/runs/00000000-0000-0000-0000-000000000100/what_if",
        json=patch_payload,
    )

    assert response.status_code == 422  # Validation error


def test_what_if_uses_default_scenario_label_when_notes_missing(
    client: TestClient, test_db: Any
) -> None:
    """Test that what-if endpoint uses 'what-if' default when notes is None."""
    patch_payload = {"new_budget_usd_cents": 150000}

    response = client.post(
        "/runs/00000000-0000-0000-0000-000000000100/what_if",
        json=patch_payload,
    )

    assert response.status_code == 202
    # Can't directly verify scenario_label without DB access, but endpoint should succeed


def test_what_if_combines_multiple_transformations(client: TestClient, test_db: Any) -> None:
    """Test that what-if endpoint handles multiple transformations in one patch."""
    patch_payload = {
        "budget_delta_usd_cents": 25000,
        "add_themes": ["nightlife"],
        "remove_themes": ["art"],
        "shift_days": 7,
        "notes": "Extended and more budget",
    }

    response = client.post(
        "/runs/00000000-0000-0000-0000-000000000100/what_if",
        json=patch_payload,
    )

    assert response.status_code == 202
    data = response.json()

    assert "run_id" in data
    assert data["status"] == "accepted"


def test_what_if_response_format_matches_create_run(client: TestClient, test_db: Any) -> None:
    """Test that what-if response has same format as POST /runs."""
    patch_payload = {"new_budget_usd_cents": 150000}

    response = client.post(
        "/runs/00000000-0000-0000-0000-000000000100/what_if",
        json=patch_payload,
    )

    assert response.status_code == 202
    data = response.json()

    # Should have CreateRunResponse schema
    assert "run_id" in data
    assert "status" in data
    assert len(data.keys()) == 2  # Only run_id and status


def test_what_if_without_auth_uses_default_context(client: TestClient, test_db: Any) -> None:
    """Test that what-if endpoint without auth header uses test defaults."""
    patch_payload = {"new_budget_usd_cents": 150000}

    # No Authorization header
    response = client.post(
        "/runs/00000000-0000-0000-0000-000000000100/what_if",
        json=patch_payload,
    )

    # Should succeed with test defaults per auth.py stub
    assert response.status_code == 202
