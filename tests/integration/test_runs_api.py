"""Tests for /runs API endpoints - PR-4A."""

import asyncio
import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
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


def test_create_run_without_auth_uses_defaults(client: TestClient) -> None:
    """Test POST /runs without auth uses test defaults.

    Per PR-4A: stub auth allows no header for testing.
    """
    response = client.post(
        "/runs",
        json={"prompt": "Plan a trip to Paris"},
    )

    assert response.status_code == 202
    data = response.json()
    assert "run_id" in data
    assert data["status"] == "accepted"

    # Verify run_id is valid UUID
    run_id = uuid.UUID(data["run_id"])
    assert run_id is not None


def test_create_run_with_invalid_auth_rejects(client: TestClient) -> None:
    """Test POST /runs with invalid auth format returns 401."""
    response = client.post(
        "/runs",
        json={"prompt": "Plan a trip to Paris"},
        headers={"Authorization": "Bearer invalid-format"},
    )

    assert response.status_code == 401
    assert "detail" in response.json()


def test_create_run_with_valid_token_format(client: TestClient) -> None:
    """Test POST /runs with valid org:user token format."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    response = client.post(
        "/runs",
        json={"prompt": "Plan a trip to Paris"},
        headers={"Authorization": f"Bearer {org_id}:{user_id}"},
    )

    assert response.status_code == 202
    data = response.json()
    assert "run_id" in data


def test_create_run_validates_request_body(client: TestClient) -> None:
    """Test POST /runs validates request body."""
    # Missing prompt
    response = client.post(
        "/runs",
        json={},
    )
    assert response.status_code == 422

    # Empty prompt
    response = client.post(
        "/runs",
        json={"prompt": ""},
    )
    assert response.status_code == 422

    # Invalid max_days
    response = client.post(
        "/runs",
        json={"prompt": "Test", "max_days": 2},  # Must be 4-7
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_sse_stream_without_auth_uses_defaults() -> None:
    """Test SSE stream without auth uses test defaults."""
    # Create a run first
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post(
            "/runs",
            json={"prompt": "Plan a trip to Paris"},
        )
        assert create_response.status_code == 202
        run_id = create_response.json()["run_id"]

        # Give background task time to start
        await asyncio.sleep(0.5)

        # Stream events
        async with client.stream(
            "GET",
            f"/runs/{run_id}/events/stream",
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream"

            # Read a few events
            event_count = 0
            async for line in response.aiter_lines():
                if line.startswith("event: run_event"):
                    event_count += 1
                if line.startswith("event: done"):
                    break
                if event_count >= 3:  # Read at least 3 events
                    break

            assert event_count >= 3, "Should have received multiple events"


@pytest.mark.asyncio
async def test_sse_stream_requires_valid_bearer_token() -> None:
    """Test SSE stream with invalid bearer token returns 401."""
    # Use a random UUID
    run_id = uuid.uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Try with invalid bearer format
        stream_response = await client.get(
            f"/runs/{run_id}/events/stream",
            headers={"Authorization": "Bearer invalid-token-format"},
        )

        # Should be 401 (unauthorized)
        assert stream_response.status_code == 401


@pytest.mark.asyncio
async def test_sse_stream_returns_404_when_run_does_not_exist() -> None:
    """Test SSE stream returns 404 when run doesn't exist."""
    # Use a random UUID that doesn't exist
    fake_run_id = uuid.uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        stream_response = await client.get(
            f"/runs/{fake_run_id}/events/stream",
        )

        # Should be 404 (not found)
        assert stream_response.status_code == 404
        assert "not found" in stream_response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_sse_stream_returns_403_for_cross_org_run() -> None:
    """Test SSE stream returns 403 when run belongs to different org."""
    # Create run with org A
    org_a = uuid.uuid4()
    user_a = uuid.uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post(
            "/runs",
            json={"prompt": "Test"},
            headers={"Authorization": f"Bearer {org_a}:{user_a}"},
        )
        assert create_response.status_code == 202
        run_id = create_response.json()["run_id"]

        # Try to stream with org B
        org_b = uuid.uuid4()
        user_b = uuid.uuid4()

        stream_response = await client.get(
            f"/runs/{run_id}/events/stream",
            headers={"Authorization": f"Bearer {org_b}:{user_b}"},
        )

        # Should be 403 (forbidden - cross-org access)
        assert stream_response.status_code == 403
        assert "access denied" in stream_response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_sse_stream_with_last_ts_filter() -> None:
    """Test SSE stream with last_ts query parameter."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create run
        create_response = await client.post(
            "/runs",
            json={"prompt": "Test"},
        )
        run_id = create_response.json()["run_id"]

        # Wait for some events
        await asyncio.sleep(1.0)

        # Get current timestamp
        from datetime import datetime

        last_ts = datetime.utcnow().isoformat()

        # Stream with last_ts (should only get events after this time)
        async with client.stream(
            "GET",
            f"/runs/{run_id}/events/stream?last_ts={last_ts}",
        ) as response:
            assert response.status_code == 200

            # Should still get done event eventually
            async for line in response.aiter_lines():
                if line.startswith("event: done"):
                    break

            # May or may not have gotten it yet depending on timing
            # This just verifies the endpoint accepts the parameter
