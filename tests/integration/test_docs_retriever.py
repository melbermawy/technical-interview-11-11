"""Integration tests for document retriever (PR-10A)."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.db.models import Base, Org, User
from backend.app.docs.ingest import ingest_document
from backend.app.docs.retriever import search_docs


@pytest_asyncio.fixture
async def test_engine() -> AsyncEngine:
    """Create test async engine."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=NullPool,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return engine


@pytest.mark.asyncio
async def test_search_returns_matching_chunks(test_engine: AsyncEngine) -> None:
    """Test that search returns only chunks matching the query."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSession(test_engine) as session:
        # Create org and user
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add_all([org, user])
        await session.commit()

    # Ingest policy doc
    async with AsyncSession(test_engine) as session:
        await ingest_document(
            org_id=org_id,
            user_id=user_id,
            title="Travel Policy",
            text="Company travel policy requires advance booking. All flights must be economy class.",
            kind="policy",
            session=session,
        )

    # Ingest unrelated doc
    async with AsyncSession(test_engine) as session:
        await ingest_document(
            org_id=org_id,
            user_id=user_id,
            title="Random Notes",
            text="Random notes about something completely different. Nothing about travel here.",
            kind="notes",
            session=session,
        )

    # Search for "travel policy"
    async with AsyncSession(test_engine) as session:
        matches = await search_docs(
            org_id=org_id,
            user_id=user_id,
            query="travel policy",
            limit=5,
            session=session,
        )

    # Should match the policy doc
    assert len(matches) >= 1
    # Top match should contain "travel" or "policy"
    top_chunk_text = matches[0].chunk.text.lower()
    assert "travel" in top_chunk_text or "policy" in top_chunk_text


@pytest.mark.asyncio
async def test_search_ranks_by_match_count(test_engine: AsyncEngine) -> None:
    """Test that chunks with more query token matches rank higher."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSession(test_engine) as session:
        # Create org and user
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add_all([org, user])
        await session.commit()

    # Ingest doc with high match count
    async with AsyncSession(test_engine) as session:
        await ingest_document(
            org_id=org_id,
            user_id=user_id,
            title="Policy Doc",
            text="Travel policy document. Travel rules and travel guidelines for travel expenses.",
            kind="policy",
            session=session,
        )

    # Ingest doc with low match count
    async with AsyncSession(test_engine) as session:
        await ingest_document(
            org_id=org_id,
            user_id=user_id,
            title="Notes Doc",
            text="Some notes. One mention of travel here.",
            kind="notes",
            session=session,
        )

    # Search for "travel"
    async with AsyncSession(test_engine) as session:
        matches = await search_docs(
            org_id=org_id,
            user_id=user_id,
            query="travel",
            limit=5,
            session=session,
        )

    # Should have at least 2 matches
    assert len(matches) >= 2

    # First match should have higher score than second
    assert matches[0].score > matches[1].score


@pytest.mark.asyncio
async def test_search_enforces_org_tenancy(test_engine: AsyncEngine) -> None:
    """Test that search only returns chunks for the specified org."""
    org1_id = uuid.uuid4()
    org2_id = uuid.uuid4()
    user1_id = uuid.uuid4()
    user2_id = uuid.uuid4()

    async with AsyncSession(test_engine) as session:
        # Create 2 orgs and users
        org1 = Org(org1_id=org1_id, name="Org 1")
        org2 = Org(org2_id=org2_id, name="Org 2")
        user1 = User(user_id=user1_id, org_id=org1_id, email="user1@example.com")
        user2 = User(user_id=user2_id, org_id=org2_id, email="user2@example.com")
        session.add_all([org1, org2, user1, user2])
        await session.commit()

    # Ingest doc for org1
    async with AsyncSession(test_engine) as session:
        await ingest_document(
            org_id=org1_id,
            user_id=user1_id,
            title="Org1 Policy",
            text="Org1 travel policy content",
            kind="policy",
            session=session,
        )

    # Ingest doc for org2
    async with AsyncSession(test_engine) as session:
        await ingest_document(
            org_id=org2_id,
            user_id=user2_id,
            title="Org2 Policy",
            text="Org2 travel policy content",
            kind="policy",
            session=session,
        )

    # Search as org1 - should only see org1 docs
    async with AsyncSession(test_engine) as session:
        matches = await search_docs(
            org_id=org1_id,
            user_id=user1_id,
            query="travel policy",
            limit=10,
            session=session,
        )

    # Should only get org1 chunks
    assert len(matches) >= 1
    for match in matches:
        # Verify chunk belongs to org1 (by checking text contains "Org1")
        assert "org1" in match.chunk.text.lower()


@pytest.mark.asyncio
async def test_search_is_deterministic(test_engine: AsyncEngine) -> None:
    """Test that search returns same results for same query."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSession(test_engine) as session:
        # Create org and user
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add_all([org, user])
        await session.commit()

    # Ingest doc
    async with AsyncSession(test_engine) as session:
        await ingest_document(
            org_id=org_id,
            user_id=user_id,
            title="Policy",
            text="Travel policy with multiple paragraphs.\n\nSecond paragraph here.\n\nThird paragraph.",
            kind="policy",
            session=session,
        )

    # Search twice
    async with AsyncSession(test_engine) as session:
        matches1 = await search_docs(
            org_id=org_id, user_id=user_id, query="policy travel", limit=5, session=session
        )

    async with AsyncSession(test_engine) as session:
        matches2 = await search_docs(
            org_id=org_id, user_id=user_id, query="policy travel", limit=5, session=session
        )

    # Should be identical
    assert len(matches1) == len(matches2)
    for m1, m2 in zip(matches1, matches2):
        assert m1.chunk.chunk_id == m2.chunk.chunk_id
        assert m1.score == m2.score


@pytest.mark.asyncio
async def test_search_respects_limit(test_engine: AsyncEngine) -> None:
    """Test that search respects the limit parameter."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSession(test_engine) as session:
        # Create org and user
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add_all([org, user])
        await session.commit()

    # Ingest doc with many paragraphs (will create many chunks)
    async with AsyncSession(test_engine) as session:
        text = "\n\n".join([f"Paragraph {i} about travel policy." for i in range(20)])
        await ingest_document(
            org_id=org_id,
            user_id=user_id,
            title="Long Policy",
            text=text,
            kind="policy",
            session=session,
        )

    # Search with limit=3
    async with AsyncSession(test_engine) as session:
        matches = await search_docs(
            org_id=org_id, user_id=user_id, query="travel policy", limit=3, session=session
        )

    # Should return at most 3 matches
    assert len(matches) <= 3


@pytest.mark.asyncio
async def test_search_returns_empty_for_no_matches(test_engine: AsyncEngine) -> None:
    """Test that search returns empty list when no chunks match."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSession(test_engine) as session:
        # Create org and user
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add_all([org, user])
        await session.commit()

    # Ingest doc
    async with AsyncSession(test_engine) as session:
        await ingest_document(
            org_id=org_id,
            user_id=user_id,
            title="Policy",
            text="Company policy about expenses.",
            kind="policy",
            session=session,
        )

    # Search for something completely unrelated
    async with AsyncSession(test_engine) as session:
        matches = await search_docs(
            org_id=org_id,
            user_id=user_id,
            query="quantum physics unicorns",
            limit=5,
            session=session,
        )

    # Should return empty
    assert len(matches) == 0
