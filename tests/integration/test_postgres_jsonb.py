"""PostgreSQL-specific integration test for JSONB column types (PR-15).

This test requires a real PostgreSQL instance and validates that JSONB columns
work correctly (SQLite doesn't support JSONB).

Run with: DATABASE_URL='postgresql://...' pytest -m postgres
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import AgentRun, Org, User


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_jsonb_final_state_storage(postgres_session: AsyncSession) -> None:
    """Test that final_state_json JSONB column works in PostgreSQL."""
    # Create org
    org = Org(
        org_id=uuid.uuid4(),
        name="Test Org JSONB",
    )
    postgres_session.add(org)

    # Create user
    user = User(
        user_id=uuid.uuid4(),
        org_id=org.org_id,
        email="jsonb_test@example.com",
        password_hash="dummy",
    )
    postgres_session.add(user)

    # Create agent_run with final_state_json
    run_id = uuid.uuid4()
    final_state = {
        "run_id": str(run_id),
        "org_id": str(org.org_id),
        "user_id": str(user.user_id),
        "status": "succeeded",
        "intent": {"city": "Paris", "budget_usd_cents": 200000},
        "plan": {
            "days": [
                {"date": "2025-06-10", "slots": []},
                {"date": "2025-06-11", "slots": []},
                {"date": "2025-06-12", "slots": []},
                {"date": "2025-06-13", "slots": []},
            ]
        },
        "choices": [],
        "weather": [],
        "violations": [],
        "decisions": [],
        "citations": [],
        "doc_matches": [],
        "tool_calls": [],
    }

    agent_run = AgentRun(
        run_id=run_id,
        org_id=org.org_id,
        user_id=user.user_id,
        status="succeeded",
        final_state_json=final_state,
    )
    postgres_session.add(agent_run)
    await postgres_session.commit()

    # Query back and verify JSONB storage
    result = await postgres_session.execute(select(AgentRun).where(AgentRun.run_id == run_id))
    retrieved_run = result.scalar_one()

    assert retrieved_run.final_state_json is not None
    assert retrieved_run.final_state_json["status"] == "succeeded"
    assert retrieved_run.final_state_json["intent"]["city"] == "Paris"
    assert len(retrieved_run.final_state_json["plan"]["days"]) == 4


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_jsonb_query_operations(postgres_session: AsyncSession) -> None:
    """Test PostgreSQL JSONB query operators (not available in SQLite)."""
    from sqlalchemy import text

    # Create org and user
    org = Org(org_id=uuid.uuid4(), name="JSONB Query Org")
    postgres_session.add(org)
    user = User(
        user_id=uuid.uuid4(),
        org_id=org.org_id,
        email="jsonb_query@example.com",
        password_hash="dummy",
    )
    postgres_session.add(user)

    # Create multiple runs with different statuses
    run_succeeded = AgentRun(
        run_id=uuid.uuid4(),
        org_id=org.org_id,
        user_id=user.user_id,
        status="succeeded",
        final_state_json={"status": "succeeded", "result": "complete"},
    )
    run_failed = AgentRun(
        run_id=uuid.uuid4(),
        org_id=org.org_id,
        user_id=user.user_id,
        status="failed",
        final_state_json={"status": "failed", "error": "timeout"},
    )
    postgres_session.add_all([run_succeeded, run_failed])
    await postgres_session.commit()

    # Use JSONB query operator to find runs with status='succeeded' in JSON
    result = await postgres_session.execute(
        text(
            "SELECT run_id FROM agent_run WHERE "
            "final_state_json->>'status' = :status AND org_id = :org_id"
        ).bindparams(status="succeeded", org_id=org.org_id)
    )
    rows = result.all()

    assert len(rows) == 1
    assert rows[0][0] == run_succeeded.run_id
