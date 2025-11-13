"""Tenancy-safe query helpers."""

from sqlalchemy.orm import Query, Session

from backend.app.db.context import RequestContext
from backend.app.db.models import AgentRun, Itinerary


def query_agent_runs(session: Session, ctx: RequestContext) -> Query:
    """Query agent_run table with org/user scoping enforced.

    Args:
        session: SQLAlchemy session
        ctx: Request context with org_id and user_id

    Returns:
        Query filtered by org_id and user_id
    """
    return session.query(AgentRun).filter(
        AgentRun.org_id == ctx.org_id, AgentRun.user_id == ctx.user_id
    )


def query_itineraries(session: Session, ctx: RequestContext) -> Query:
    """Query itinerary table with org/user scoping enforced.

    Args:
        session: SQLAlchemy session
        ctx: Request context with org_id and user_id

    Returns:
        Query filtered by org_id and user_id
    """
    return session.query(Itinerary).filter(
        Itinerary.org_id == ctx.org_id, Itinerary.user_id == ctx.user_id
    )
