"""Repository for run event operations."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.context import RequestContext
from backend.app.models.events import NodeName, Phase, RunEvent

if TYPE_CHECKING:
    from backend.app.db.models import RunEvent as RunEventDB


async def append_run_event(
    session: AsyncSession,
    run_id: uuid.UUID,
    org_id: uuid.UUID,
    sequence: int,
    node: NodeName,
    phase: Phase,
    summary: str,
    payload: dict | None = None,
) -> uuid.UUID:
    """Append a new run event.

    Args:
        session: Database session
        run_id: Agent run ID
        org_id: Organization ID (for tenancy)
        sequence: Monotonic sequence number
        node: Node name
        phase: Node phase (started/completed)
        summary: Human-readable summary
        payload: Optional payload dict

    Returns:
        Event ID
    """
    from backend.app.db.models import RunEvent as RunEventDB

    event = RunEventDB(
        id=uuid.uuid4(),
        run_id=run_id,
        org_id=org_id,
        timestamp=datetime.utcnow(),
        sequence=sequence,
        node=node,
        phase=phase,
        summary=summary,
        payload=payload or {},
    )
    session.add(event)
    await session.flush()
    return event.id


async def list_run_events(
    session: AsyncSession,
    run_id: uuid.UUID,
    ctx: RequestContext,
    since_ts: datetime | None = None,
) -> list[RunEvent]:
    """List run events, optionally filtering by timestamp.

    Args:
        session: Database session
        run_id: Agent run ID
        ctx: Request context (enforces tenancy)
        since_ts: Optional timestamp filter (events after this time)

    Returns:
        List of run events ordered by sequence
    """
    from backend.app.db.models import RunEvent as RunEventDB

    query = (
        select(RunEventDB)
        .where(RunEventDB.run_id == run_id)
        .where(RunEventDB.org_id == ctx.org_id)
        .order_by(RunEventDB.sequence)
    )

    if since_ts is not None:
        query = query.where(RunEventDB.timestamp > since_ts)

    result = await session.execute(query)
    rows = result.scalars().all()

    return [
        RunEvent(
            id=row.id,
            run_id=row.run_id,
            org_id=row.org_id,
            timestamp=row.timestamp,
            sequence=row.sequence,
            node=row.node,  # type: ignore
            phase=row.phase,  # type: ignore
            summary=row.summary,
            payload=row.payload,
        )
        for row in rows
    ]
