"""SQL implementations of repository interfaces."""

import base64
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from backend.app.db.context import RequestContext
from backend.app.db.models import AgentRun, Idempotency, Itinerary
from backend.app.db.queries import query_agent_runs, query_itineraries
from backend.app.db.repositories import (
    AgentRunRecord,
    IdempotencyRecord,
    IdempotencyStatus,
    ItinerarySummary,
    StoredResponse,
)
from backend.app.models.intent import IntentV1
from backend.app.models.itinerary import ItineraryV1


class SqlRunRepository:
    """SQL implementation of RunRepository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_run(self, intent: IntentV1, ctx: RequestContext) -> uuid.UUID:
        """Create a new agent run."""
        run_id = uuid.uuid4()
        trace_id = f"trace-{run_id}"

        run = AgentRun(
            run_id=run_id,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            intent=intent.model_dump(mode="json"),
            trace_id=trace_id,
            status="running",
        )

        self._session.add(run)
        self._session.commit()

        return run_id

    def update_run(
        self,
        run_id: uuid.UUID,
        ctx: RequestContext,
        *,
        status: str,
        plan_snapshot: list[dict] | None = None,
        tool_log: dict | None = None,
        cost_usd: float | None = None,
    ) -> None:
        """Update an existing agent run."""
        run = (
            query_agent_runs(self._session, ctx).filter(AgentRun.run_id == run_id).first()
        )

        if run is None:
            return

        run.status = status
        if plan_snapshot is not None:
            run.plan_snapshot = plan_snapshot
        if tool_log is not None:
            run.tool_log = tool_log
        if cost_usd is not None:
            run.cost_usd = cost_usd

        if status in ("completed", "error"):
            run.completed_at = datetime.now()

        self._session.commit()

    def get_run(self, run_id: uuid.UUID, ctx: RequestContext) -> AgentRunRecord | None:
        """Get agent run by ID."""
        run = (
            query_agent_runs(self._session, ctx).filter(AgentRun.run_id == run_id).first()
        )

        if run is None:
            return None

        return AgentRunRecord(
            run_id=run.run_id,
            org_id=run.org_id,
            user_id=run.user_id,
            intent=run.intent,
            plan_snapshot=run.plan_snapshot,
            tool_log=run.tool_log,
            cost_usd=float(run.cost_usd) if run.cost_usd else None,
            trace_id=run.trace_id,
            status=run.status,
            created_at=run.created_at,
            completed_at=run.completed_at,
        )


class SqlItineraryRepository:
    """SQL implementation of ItineraryRepository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save_itinerary(
        self, run_id: uuid.UUID, itinerary: ItineraryV1, ctx: RequestContext
    ) -> uuid.UUID:
        """Save a new itinerary."""
        itinerary_id = uuid.uuid4()

        itin = Itinerary(
            itinerary_id=itinerary_id,
            org_id=ctx.org_id,
            run_id=run_id,
            user_id=ctx.user_id,
            data=itinerary.model_dump(mode="json"),
        )

        self._session.add(itin)
        self._session.commit()

        return itinerary_id

    def get_itinerary(
        self, itinerary_id: uuid.UUID, ctx: RequestContext
    ) -> ItineraryV1 | None:
        """Get itinerary by ID."""
        itin = (
            query_itineraries(self._session, ctx)
            .filter(Itinerary.itinerary_id == itinerary_id)
            .first()
        )

        if itin is None:
            return None

        return ItineraryV1.model_validate(itin.data)

    def list_recent_itineraries(
        self, ctx: RequestContext, limit: int = 10
    ) -> list[ItinerarySummary]:
        """List recent itineraries for user."""
        itins = (
            query_itineraries(self._session, ctx)
            .order_by(Itinerary.created_at.desc())
            .limit(limit)
            .all()
        )

        results: list[ItinerarySummary] = []

        for itin in itins:
            # Extract summary data from JSONB
            data = itin.data
            intent_data = data.get("intent", {})
            date_window = intent_data.get("date_window", {})
            cost_breakdown = data.get("cost_breakdown", {})

            summary = ItinerarySummary(
                itinerary_id=itin.itinerary_id,
                run_id=itin.run_id,
                created_at=itin.created_at,
                city=intent_data.get("city", ""),
                date_start=date_window.get("start", ""),
                date_end=date_window.get("end", ""),
                total_cost_cents=cost_breakdown.get("total_usd_cents", 0),
            )
            results.append(summary)

        return results


class SqlIdempotencyStore:
    """SQL implementation of IdempotencyStore."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, key: str, user_id: uuid.UUID) -> IdempotencyRecord | None:
        """Get idempotency record."""
        record = (
            self._session.query(Idempotency)
            .filter(Idempotency.key == key, Idempotency.user_id == user_id)
            .first()
        )

        if record is None:
            return None

        # Check if expired
        if datetime.now() > record.ttl_until:
            self._session.delete(record)
            self._session.commit()
            return None

        # Deserialize response envelope if present
        response = None
        if record.response_envelope:
            envelope = record.response_envelope
            response = StoredResponse(
                status_code=envelope["status_code"],
                headers=envelope["headers"],
                body=base64.b64decode(envelope["body_base64"]),
            )

        return IdempotencyRecord(
            key=record.key,
            user_id=record.user_id,
            ttl_until=record.ttl_until,
            status=IdempotencyStatus(record.status),
            response=response,
        )

    def set_pending(self, key: str, user_id: uuid.UUID, ttl_until: datetime) -> None:
        """Set idempotency record to pending."""
        record = Idempotency(
            key=key,
            user_id=user_id,
            ttl_until=ttl_until,
            status=IdempotencyStatus.pending.value,
            response_envelope=None,
        )

        self._session.merge(record)
        self._session.commit()

    def set_completed(
        self, key: str, user_id: uuid.UUID, ttl_until: datetime, response: StoredResponse
    ) -> None:
        """Set idempotency record to completed with full response envelope."""
        # Serialize response envelope to JSONB
        envelope = {
            "status_code": response.status_code,
            "headers": response.headers,
            "body_base64": base64.b64encode(response.body).decode("ascii"),
        }

        record = Idempotency(
            key=key,
            user_id=user_id,
            ttl_until=ttl_until,
            status=IdempotencyStatus.completed.value,
            response_envelope=envelope,
        )

        self._session.merge(record)
        self._session.commit()

    def set_error(self, key: str, user_id: uuid.UUID, ttl_until: datetime) -> None:
        """Set idempotency record to error."""
        record = Idempotency(
            key=key,
            user_id=user_id,
            ttl_until=ttl_until,
            status=IdempotencyStatus.error.value,
            response_envelope=None,
        )

        self._session.merge(record)
        self._session.commit()
