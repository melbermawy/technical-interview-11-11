"""Unit tests for docs_node (PR-10B)."""

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.db.models import Base, Doc, DocChunk, Org, User
from backend.app.models.intent import DateWindow, IntentV1, Preferences
from backend.app.orchestration.docs_node import docs_node
from backend.app.orchestration.state import GraphState


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
async def test_docs_node_populates_doc_matches(test_engine: AsyncEngine) -> None:
    """Test that docs_node retrieves and populates state.doc_matches."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    run_id = uuid.uuid4()

    # Create org, user, doc, and chunks
    async with AsyncSession(test_engine) as session:
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add_all([org, user])
        await session.commit()

    # Create doc with chunks matching "Paris" and "art"
    async with AsyncSession(test_engine) as session:
        doc_id = uuid.uuid4()
        doc = Doc(
            doc_id=doc_id,
            org_id=org_id,
            user_id=user_id,
            title="Travel Policy",
            kind="policy",
            created_at=date(2025, 1, 1),
        )
        session.add(doc)

        chunk = DocChunk(
            chunk_id=uuid.uuid4(),
            doc_id=doc_id,
            order=0,
            text="All travel to Paris must follow company art museum guidelines.",
            section_label=None,
        )
        session.add(chunk)
        await session.commit()

    # Create state with intent (Paris + art)
    state = GraphState(
        run_id=run_id,
        org_id=org_id,
        user_id=user_id,
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10),
                end=date(2025, 6, 14),
                tz="Europe/Paris",
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(themes=["art"]),
        ),
    )

    # Run docs_node
    async with AsyncSession(test_engine) as session:
        result_state = await docs_node(state, session)

    # Verify doc_matches populated
    assert len(result_state.doc_matches) >= 1
    assert "Paris" in result_state.doc_matches[0].text or "art" in result_state.doc_matches[0].text


@pytest.mark.asyncio
async def test_docs_node_skips_when_no_intent(test_engine: AsyncEngine) -> None:
    """Test that docs_node skips retrieval when no intent is present."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    run_id = uuid.uuid4()

    # Create org and user
    async with AsyncSession(test_engine) as session:
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add_all([org, user])
        await session.commit()

    # Create state with NO intent
    state = GraphState(
        run_id=run_id,
        org_id=org_id,
        user_id=user_id,
        intent=None,  # No intent
    )

    # Run docs_node
    async with AsyncSession(test_engine) as session:
        result_state = await docs_node(state, session)

    # Verify doc_matches is empty
    assert len(result_state.doc_matches) == 0


@pytest.mark.asyncio
async def test_docs_node_enforces_tenancy(test_engine: AsyncEngine) -> None:
    """Test that docs_node only retrieves docs from the correct org/user."""
    org1_id = uuid.uuid4()
    org2_id = uuid.uuid4()
    user1_id = uuid.uuid4()
    user2_id = uuid.uuid4()
    run_id = uuid.uuid4()

    # Create 2 orgs and users
    async with AsyncSession(test_engine) as session:
        org1 = Org(org_id=org1_id, name="Org 1")
        org2 = Org(org_id=org2_id, name="Org 2")
        user1 = User(user_id=user1_id, org_id=org1_id, email="user1@example.com")
        user2 = User(user_id=user2_id, org_id=org2_id, email="user2@example.com")
        session.add_all([org1, org2, user1, user2])
        await session.commit()

    # Create doc for org1
    async with AsyncSession(test_engine) as session:
        doc1_id = uuid.uuid4()
        doc1 = Doc(
            doc_id=doc1_id,
            org_id=org1_id,
            user_id=user1_id,
            title="Org1 Policy",
            kind="policy",
            created_at=date(2025, 1, 1),
        )
        session.add(doc1)

        chunk1 = DocChunk(
            chunk_id=uuid.uuid4(),
            doc_id=doc1_id,
            order=0,
            text="Org1 travel policy for Paris art museums.",
            section_label=None,
        )
        session.add(chunk1)
        await session.commit()

    # Create doc for org2
    async with AsyncSession(test_engine) as session:
        doc2_id = uuid.uuid4()
        doc2 = Doc(
            doc_id=doc2_id,
            org_id=org2_id,
            user_id=user2_id,
            title="Org2 Policy",
            kind="policy",
            created_at=date(2025, 1, 1),
        )
        session.add(doc2)

        chunk2 = DocChunk(
            chunk_id=uuid.uuid4(),
            doc_id=doc2_id,
            order=0,
            text="Org2 travel policy for Paris art museums.",
            section_label=None,
        )
        session.add(chunk2)
        await session.commit()

    # Create state for org1
    state = GraphState(
        run_id=run_id,
        org_id=org1_id,
        user_id=user1_id,
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10),
                end=date(2025, 6, 14),
                tz="Europe/Paris",
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(themes=["art"]),
        ),
    )

    # Run docs_node
    async with AsyncSession(test_engine) as session:
        result_state = await docs_node(state, session)

    # Verify only org1 chunks returned
    assert len(result_state.doc_matches) >= 1
    for chunk in result_state.doc_matches:
        assert "Org1" in chunk.text


@pytest.mark.asyncio
async def test_docs_node_returns_top_5_chunks(test_engine: AsyncEngine) -> None:
    """Test that docs_node limits results to top 5 chunks."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    run_id = uuid.uuid4()

    # Create org and user
    async with AsyncSession(test_engine) as session:
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add_all([org, user])
        await session.commit()

    # Create doc with 10 chunks all matching "Paris"
    async with AsyncSession(test_engine) as session:
        doc_id = uuid.uuid4()
        doc = Doc(
            doc_id=doc_id,
            org_id=org_id,
            user_id=user_id,
            title="Long Policy",
            kind="policy",
            created_at=date(2025, 1, 1),
        )
        session.add(doc)

        for i in range(10):
            chunk = DocChunk(
                chunk_id=uuid.uuid4(),
                doc_id=doc_id,
                order=i,
                text=f"Paragraph {i}: Paris travel policy here.",
                section_label=None,
            )
            session.add(chunk)
        await session.commit()

    # Create state with Paris intent
    state = GraphState(
        run_id=run_id,
        org_id=org_id,
        user_id=user_id,
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10),
                end=date(2025, 6, 14),
                tz="Europe/Paris",
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(themes=[]),
        ),
    )

    # Run docs_node
    async with AsyncSession(test_engine) as session:
        result_state = await docs_node(state, session)

    # Verify limited to 5 chunks
    assert len(result_state.doc_matches) <= 5


@pytest.mark.asyncio
async def test_docs_node_logs_tool_call(test_engine: AsyncEngine) -> None:
    """Test that docs_node logs the docs.search tool call (PR-11A)."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    run_id = uuid.uuid4()

    # Create org and user
    async with AsyncSession(test_engine) as session:
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add_all([org, user])
        await session.commit()

    # Create state with Paris intent
    state = GraphState(
        run_id=run_id,
        org_id=org_id,
        user_id=user_id,
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10),
                end=date(2025, 6, 14),
                tz="Europe/Paris",
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(themes=["art"]),
        ),
    )

    # Run docs_node
    async with AsyncSession(test_engine) as session:
        result_state = await docs_node(state, session)

    # Verify tool call logged
    assert len(result_state.tool_calls) == 1
    log = result_state.tool_calls[0]

    assert log.name == "docs.search"
    assert log.success is True
    assert log.error is None
    assert log.duration_ms >= 0
    assert "query" in log.input_summary
    assert "limit" in log.input_summary
    assert log.input_summary["limit"] == 5
    assert "count" in log.output_summary
