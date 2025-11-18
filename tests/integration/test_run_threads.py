"""Unit tests for run thread helper (PR-9B)."""

import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.db.models import AgentRun, Base, Org, User
from backend.app.orchestration.threads import get_run_thread


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
async def test_get_run_thread_returns_base_and_children(test_engine: AsyncEngine) -> None:
    """Test that get_run_thread returns base run and all children."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSession(test_engine) as session:
        # Create org and user
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add(org)
        session.add(user)

        # Create base run
        base_run_id = uuid.uuid4()
        base_run = AgentRun(
            run_id=base_run_id,
            org_id=org_id,
            user_id=user_id,
            parent_run_id=None,
            scenario_label=None,
            intent={"city": "Paris"},
            status="completed",
            trace_id="trace_base",
            created_at=datetime.utcnow(),
        )
        session.add(base_run)

        # Create 2 child runs
        child1_id = uuid.uuid4()
        child1 = AgentRun(
            run_id=child1_id,
            org_id=org_id,
            user_id=user_id,
            parent_run_id=base_run_id,
            scenario_label="Budget +$500",
            intent={"city": "Paris", "budget": 3000},
            status="pending",
            trace_id="trace_child1",
            created_at=datetime.utcnow() + timedelta(seconds=1),
        )
        session.add(child1)

        child2_id = uuid.uuid4()
        child2 = AgentRun(
            run_id=child2_id,
            org_id=org_id,
            user_id=user_id,
            parent_run_id=base_run_id,
            scenario_label="Shift dates +7 days",
            intent={"city": "Paris", "dates": "later"},
            status="pending",
            trace_id="trace_child2",
            created_at=datetime.utcnow() + timedelta(seconds=2),
        )
        session.add(child2)

        await session.commit()

        # Test: fetch thread from base run ID
        base, children = await get_run_thread(session, base_run_id, org_id=org_id, user_id=user_id)

        assert base.run_id == base_run_id
        assert base.parent_run_id is None
        assert len(children) == 2
        assert children[0].run_id == child1_id
        assert children[1].run_id == child2_id
        assert children[0].scenario_label == "Budget +$500"
        assert children[1].scenario_label == "Shift dates +7 days"


@pytest.mark.asyncio
async def test_get_run_thread_normalizes_from_child_id(test_engine: AsyncEngine) -> None:
    """Test that get_run_thread resolves to base when given child ID."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSession(test_engine) as session:
        # Create org and user
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add(org)
        session.add(user)

        # Create base run
        base_run_id = uuid.uuid4()
        base_run = AgentRun(
            run_id=base_run_id,
            org_id=org_id,
            user_id=user_id,
            parent_run_id=None,
            scenario_label=None,
            intent={"city": "Tokyo"},
            status="completed",
            trace_id="trace_base",
            created_at=datetime.utcnow(),
        )
        session.add(base_run)

        # Create child run
        child_id = uuid.uuid4()
        child = AgentRun(
            run_id=child_id,
            org_id=org_id,
            user_id=user_id,
            parent_run_id=base_run_id,
            scenario_label="What-if scenario",
            intent={"city": "Tokyo", "budget": 5000},
            status="pending",
            trace_id="trace_child",
            created_at=datetime.utcnow() + timedelta(seconds=1),
        )
        session.add(child)

        await session.commit()

        # Test: fetch thread from child ID - should still return base run
        base, children = await get_run_thread(session, child_id, org_id=org_id, user_id=user_id)

        assert base.run_id == base_run_id  # Normalized to base, not child
        assert base.parent_run_id is None
        assert len(children) == 1
        assert children[0].run_id == child_id


@pytest.mark.asyncio
async def test_get_run_thread_orders_children_by_created_at(test_engine: AsyncEngine) -> None:
    """Test that children are ordered by created_at ascending."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSession(test_engine) as session:
        # Create org and user
        org = Org(org_id=org_id, name="Test Org")
        user = User(user_id=user_id, org_id=org_id, email="test@example.com")
        session.add(org)
        session.add(user)

        # Create base run
        base_run_id = uuid.uuid4()
        base_run = AgentRun(
            run_id=base_run_id,
            org_id=org_id,
            user_id=user_id,
            parent_run_id=None,
            scenario_label=None,
            intent={"city": "London"},
            status="completed",
            trace_id="trace_base",
            created_at=datetime.utcnow(),
        )
        session.add(base_run)

        # Create children with different timestamps (added out of order)
        child2_id = uuid.uuid4()
        child2 = AgentRun(
            run_id=child2_id,
            org_id=org_id,
            user_id=user_id,
            parent_run_id=base_run_id,
            scenario_label="Second",
            intent={"city": "London"},
            status="pending",
            trace_id="trace_child2",
            created_at=datetime.utcnow() + timedelta(seconds=20),
        )
        session.add(child2)

        child1_id = uuid.uuid4()
        child1 = AgentRun(
            run_id=child1_id,
            org_id=org_id,
            user_id=user_id,
            parent_run_id=base_run_id,
            scenario_label="First",
            intent={"city": "London"},
            status="pending",
            trace_id="trace_child1",
            created_at=datetime.utcnow() + timedelta(seconds=10),
        )
        session.add(child1)

        child3_id = uuid.uuid4()
        child3 = AgentRun(
            run_id=child3_id,
            org_id=org_id,
            user_id=user_id,
            parent_run_id=base_run_id,
            scenario_label="Third",
            intent={"city": "London"},
            status="pending",
            trace_id="trace_child3",
            created_at=datetime.utcnow() + timedelta(seconds=30),
        )
        session.add(child3)

        await session.commit()

        # Test: children should be ordered by created_at
        base, children = await get_run_thread(session, base_run_id, org_id=org_id, user_id=user_id)

        assert len(children) == 3
        assert children[0].scenario_label == "First"
        assert children[1].scenario_label == "Second"
        assert children[2].scenario_label == "Third"


@pytest.mark.asyncio
async def test_get_run_thread_enforces_org_tenancy(test_engine: AsyncEngine) -> None:
    """Test that get_run_thread enforces org tenancy."""
    org1_id = uuid.uuid4()
    org2_id = uuid.uuid4()
    user1_id = uuid.uuid4()
    user2_id = uuid.uuid4()

    async with AsyncSession(test_engine) as session:
        # Create 2 orgs and users
        org1 = Org(org_id=org1_id, name="Org 1")
        org2 = Org(org_id=org2_id, name="Org 2")
        user1 = User(user_id=user1_id, org_id=org1_id, email="user1@example.com")
        user2 = User(user_id=user2_id, org_id=org2_id, email="user2@example.com")
        session.add_all([org1, org2, user1, user2])

        # Create run in org1
        run_id = uuid.uuid4()
        run = AgentRun(
            run_id=run_id,
            org_id=org1_id,
            user_id=user1_id,
            parent_run_id=None,
            scenario_label=None,
            intent={"city": "Paris"},
            status="completed",
            trace_id="trace_org1",
            created_at=datetime.utcnow(),
        )
        session.add(run)

        await session.commit()

        # Test: attempt to access from org2 - should raise ValueError
        with pytest.raises(ValueError, match="not found or access denied"):
            await get_run_thread(session, run_id, org_id=org2_id, user_id=user2_id)


@pytest.mark.asyncio
async def test_get_run_thread_enforces_user_tenancy(test_engine: AsyncEngine) -> None:
    """Test that get_run_thread enforces user tenancy within same org."""
    org_id = uuid.uuid4()
    user1_id = uuid.uuid4()
    user2_id = uuid.uuid4()

    async with AsyncSession(test_engine) as session:
        # Create org and 2 users
        org = Org(org_id=org_id, name="Test Org")
        user1 = User(user_id=user1_id, org_id=org_id, email="user1@example.com")
        user2 = User(user_id=user2_id, org_id=org_id, email="user2@example.com")
        session.add_all([org, user1, user2])

        # Create run for user1
        run_id = uuid.uuid4()
        run = AgentRun(
            run_id=run_id,
            org_id=org_id,
            user_id=user1_id,
            parent_run_id=None,
            scenario_label=None,
            intent={"city": "Berlin"},
            status="completed",
            trace_id="trace_user1",
            created_at=datetime.utcnow(),
        )
        session.add(run)

        await session.commit()

        # Test: attempt to access as user2 - should raise ValueError
        with pytest.raises(ValueError, match="not found or access denied"):
            await get_run_thread(session, run_id, org_id=org_id, user_id=user2_id)
