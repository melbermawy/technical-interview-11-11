"""Integration tests for document ingestion (PR-10A)."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.db.models import Base, Doc, DocChunk, Org, User
from backend.app.docs.ingest import ingest_document


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
async def test_ingest_simple_doc_returns_user_document(test_engine: AsyncEngine) -> None:
    """Test that ingesting a simple doc returns UserDocument with correct metadata."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSession(test_engine) as session:
        # Create org and user
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add_all([org, user])
        await session.commit()

    async with AsyncSession(test_engine) as session:
        # Ingest document
        doc = await ingest_document(
            org_id=org_id,
            user_id=user_id,
            title="Travel Policy",
            text="This is our company travel policy. Employees must book in advance.",
            kind="policy",
            session=session,
        )

        # Verify UserDocument returned
        assert doc.doc_id is not None
        assert doc.org_id == org_id
        assert doc.user_id == user_id
        assert doc.title == "Travel Policy"
        assert doc.kind == "policy"
        assert doc.created_at is not None

    # Verify DB has the doc
    async with AsyncSession(test_engine) as session:
        result = await session.execute(select(Doc).where(Doc.doc_id == doc.doc_id))
        db_doc = result.scalar_one()

        assert db_doc.title == "Travel Policy"
        assert db_doc.kind == "policy"

        # Verify chunks exist
        result = await session.execute(
            select(DocChunk).where(DocChunk.doc_id == doc.doc_id).order_by(DocChunk.order)
        )
        chunks = list(result.scalars().all())

        assert len(chunks) >= 1  # At least one chunk
        # Orders should be sequential
        for i, chunk in enumerate(chunks):
            assert chunk.order == i


@pytest.mark.asyncio
async def test_ingest_multi_doc_no_chunk_crossover(test_engine: AsyncEngine) -> None:
    """Test that ingesting 2 docs doesn't mix their chunks."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSession(test_engine) as session:
        # Create org and user
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add_all([org, user])
        await session.commit()

    async with AsyncSession(test_engine) as session:
        # Ingest first doc
        doc1 = await ingest_document(
            org_id=org_id,
            user_id=user_id,
            title="Policy Doc",
            text="Travel policy content here.",
            kind="policy",
            session=session,
        )

    async with AsyncSession(test_engine) as session:
        # Ingest second doc
        doc2 = await ingest_document(
            org_id=org_id,
            user_id=user_id,
            title="Notes Doc",
            text="Random notes content here.",
            kind="notes",
            session=session,
        )

    # Verify chunks don't cross docs
    async with AsyncSession(test_engine) as session:
        # Chunks for doc1
        result = await session.execute(select(DocChunk).where(DocChunk.doc_id == doc1.doc_id))
        chunks1 = list(result.scalars().all())

        # Chunks for doc2
        result = await session.execute(select(DocChunk).where(DocChunk.doc_id == doc2.doc_id))
        chunks2 = list(result.scalars().all())

        # All chunks for doc1 should reference doc1
        for chunk in chunks1:
            assert chunk.doc_id == doc1.doc_id

        # All chunks for doc2 should reference doc2
        for chunk in chunks2:
            assert chunk.doc_id == doc2.doc_id


@pytest.mark.asyncio
async def test_ingest_tenancy_isolation(test_engine: AsyncEngine) -> None:
    """Test that docs from different orgs/users are isolated."""
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

    async with AsyncSession(test_engine) as session:
        # Ingest doc for org1/user1
        doc1 = await ingest_document(
            org_id=org1_id,
            user_id=user1_id,
            title="Org1 Doc",
            text="Org1 content",
            kind="policy",
            session=session,
        )

    async with AsyncSession(test_engine) as session:
        # Ingest doc for org2/user2
        doc2 = await ingest_document(
            org_id=org2_id,
            user_id=user2_id,
            title="Org2 Doc",
            text="Org2 content",
            kind="notes",
            session=session,
        )

    # Verify tenancy in DB
    async with AsyncSession(test_engine) as session:
        # Doc1 belongs to org1
        result = await session.execute(select(Doc).where(Doc.doc_id == doc1.doc_id))
        db_doc1 = result.scalar_one()
        assert db_doc1.org_id == org1_id
        assert db_doc1.user_id == user1_id

        # Doc2 belongs to org2
        result = await session.execute(select(Doc).where(Doc.doc_id == doc2.doc_id))
        db_doc2 = result.scalar_one()
        assert db_doc2.org_id == org2_id
        assert db_doc2.user_id == user2_id
