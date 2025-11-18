"""Integration tests for docs API routes (PR-10B)."""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.db.models import Base, Org, User
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
            password_hash="stub",
        )
        session.add(user)

        await session.commit()

    yield test_engine


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


def test_create_doc_returns_201(client: TestClient, test_db: Any) -> None:
    """Test that POST /docs creates a document and returns 201."""
    payload = {
        "title": "Travel Policy",
        "text": "All flights must be economy class. Book in advance.",
        "kind": "policy",
    }

    response = client.post("/docs", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert "doc_id" in data
    assert data["title"] == "Travel Policy"
    assert data["kind"] == "policy"
    assert "created_at" in data


def test_create_doc_invalid_kind_returns_422(client: TestClient, test_db: Any) -> None:
    """Test that invalid kind field returns 422."""
    payload = {
        "title": "Test Doc",
        "text": "Content here",
        "kind": "invalid_kind",  # Not in allowed values
    }

    response = client.post("/docs", json=payload)

    assert response.status_code == 422


def test_create_doc_empty_title_returns_422(client: TestClient, test_db: Any) -> None:
    """Test that empty title returns 422."""
    payload = {
        "title": "",  # Empty title
        "text": "Content here",
        "kind": "policy",
    }

    response = client.post("/docs", json=payload)

    assert response.status_code == 422


def test_list_docs_returns_all_docs(client: TestClient, test_db: Any) -> None:
    """Test that GET /docs returns all user docs."""
    # Create first doc
    client.post(
        "/docs",
        json={"title": "Doc 1", "text": "Content 1", "kind": "policy"},
    )

    # Create second doc
    client.post(
        "/docs",
        json={"title": "Doc 2", "text": "Content 2", "kind": "notes"},
    )

    # List all docs
    response = client.get("/docs")

    assert response.status_code == 200
    data = response.json()
    assert "docs" in data
    assert len(data["docs"]) == 2


def test_list_docs_filter_by_kind(client: TestClient, test_db: Any) -> None:
    """Test that GET /docs?kind=policy filters by document kind."""
    # Create policy doc
    client.post(
        "/docs",
        json={"title": "Policy Doc", "text": "Content 1", "kind": "policy"},
    )

    # Create notes doc
    client.post(
        "/docs",
        json={"title": "Notes Doc", "text": "Content 2", "kind": "notes"},
    )

    # Filter by policy
    response = client.get("/docs?kind=policy")

    assert response.status_code == 200
    data = response.json()
    assert len(data["docs"]) == 1
    assert data["docs"][0]["kind"] == "policy"


def test_search_docs_returns_matches(client: TestClient, test_db: Any) -> None:
    """Test that GET /docs/search returns relevant chunks."""
    # Create doc
    client.post(
        "/docs",
        json={
            "title": "Travel Policy",
            "text": "All flights must be economy class. Book in advance for best rates.",
            "kind": "policy",
        },
    )

    # Search for "flights economy"
    response = client.get("/docs/search?query=flights%20economy")

    assert response.status_code == 200
    data = response.json()
    assert "matches" in data
    assert "query" in data
    assert data["query"] == "flights economy"
    assert len(data["matches"]) >= 1


def test_search_docs_respects_limit(client: TestClient, test_db: Any) -> None:
    """Test that GET /docs/search respects limit parameter."""
    # Create doc with multiple chunks
    long_text = "\\n\\n".join([f"Paragraph {i} about travel policy." for i in range(20)])
    client.post(
        "/docs",
        json={
            "title": "Long Policy",
            "text": long_text,
            "kind": "policy",
        },
    )

    # Search with limit=3
    response = client.get("/docs/search?query=travel%20policy&limit=3")

    assert response.status_code == 200
    data = response.json()
    assert len(data["matches"]) <= 3


def test_search_docs_returns_empty_for_no_matches(client: TestClient, test_db: Any) -> None:
    """Test that search returns empty list when no matches found."""
    # Create doc
    client.post(
        "/docs",
        json={
            "title": "Travel Policy",
            "text": "Company policy about expenses.",
            "kind": "policy",
        },
    )

    # Search for unrelated terms
    response = client.get("/docs/search?query=quantum%20physics%20unicorns")

    assert response.status_code == 200
    data = response.json()
    assert len(data["matches"]) == 0


def test_search_docs_missing_query_returns_422(client: TestClient, test_db: Any) -> None:
    """Test that search without query parameter returns 422."""
    response = client.get("/docs/search")

    assert response.status_code == 422
