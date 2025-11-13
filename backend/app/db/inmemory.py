"""In-memory implementations of repository interfaces."""

import uuid
from datetime import datetime, timedelta

from backend.app.db.context import RequestContext
from backend.app.db.repositories import (
    AgentRunRecord,
    IdempotencyRecord,
    IdempotencyStatus,
    ItinerarySummary,
    RetryAfter,
    StoredResponse,
)
from backend.app.models.intent import IntentV1
from backend.app.models.itinerary import ItineraryV1


class InMemoryRunRepository:
    """In-memory implementation of RunRepository."""

    def __init__(self) -> None:
        self._runs: dict[uuid.UUID, AgentRunRecord] = {}

    def create_run(self, intent: IntentV1, ctx: RequestContext) -> uuid.UUID:
        """Create a new agent run."""
        run_id = uuid.uuid4()
        trace_id = f"trace-{run_id}"

        record = AgentRunRecord(
            run_id=run_id,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            intent=intent.model_dump(mode="json"),
            plan_snapshot=None,
            tool_log=None,
            cost_usd=None,
            trace_id=trace_id,
            status="running",
            created_at=datetime.now(),
            completed_at=None,
        )

        self._runs[run_id] = record
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
        if run_id not in self._runs:
            return

        record = self._runs[run_id]

        # Enforce tenancy
        if record.org_id != ctx.org_id or record.user_id != ctx.user_id:
            return

        # Update fields
        self._runs[run_id] = AgentRunRecord(
            run_id=record.run_id,
            org_id=record.org_id,
            user_id=record.user_id,
            intent=record.intent,
            plan_snapshot=plan_snapshot if plan_snapshot is not None else record.plan_snapshot,
            tool_log=tool_log if tool_log is not None else record.tool_log,
            cost_usd=cost_usd if cost_usd is not None else record.cost_usd,
            trace_id=record.trace_id,
            status=status,
            created_at=record.created_at,
            completed_at=datetime.now() if status in ("completed", "error") else record.completed_at,
        )

    def get_run(self, run_id: uuid.UUID, ctx: RequestContext) -> AgentRunRecord | None:
        """Get agent run by ID."""
        record = self._runs.get(run_id)

        if record is None:
            return None

        # Enforce tenancy
        if record.org_id != ctx.org_id or record.user_id != ctx.user_id:
            return None

        return record


class InMemoryItineraryRepository:
    """In-memory implementation of ItineraryRepository."""

    def __init__(self) -> None:
        self._itineraries: dict[uuid.UUID, tuple[RequestContext, ItineraryV1, uuid.UUID]] = {}

    def save_itinerary(
        self, run_id: uuid.UUID, itinerary: ItineraryV1, ctx: RequestContext
    ) -> uuid.UUID:
        """Save a new itinerary."""
        itinerary_id = uuid.uuid4()
        self._itineraries[itinerary_id] = (ctx, itinerary, run_id)
        return itinerary_id

    def get_itinerary(
        self, itinerary_id: uuid.UUID, ctx: RequestContext
    ) -> ItineraryV1 | None:
        """Get itinerary by ID."""
        data = self._itineraries.get(itinerary_id)

        if data is None:
            return None

        stored_ctx, itinerary, _ = data

        # Enforce tenancy
        if stored_ctx.org_id != ctx.org_id or stored_ctx.user_id != ctx.user_id:
            return None

        return itinerary

    def list_recent_itineraries(
        self, ctx: RequestContext, limit: int = 10
    ) -> list[ItinerarySummary]:
        """List recent itineraries for user."""
        results: list[ItinerarySummary] = []

        for itinerary_id, (stored_ctx, itinerary, run_id) in self._itineraries.items():
            # Enforce tenancy
            if stored_ctx.org_id != ctx.org_id or stored_ctx.user_id != ctx.user_id:
                continue

            # Extract summary data
            summary = ItinerarySummary(
                itinerary_id=itinerary_id,
                run_id=run_id,
                created_at=itinerary.created_at,
                city=itinerary.intent.city,
                date_start=str(itinerary.intent.date_window.start),
                date_end=str(itinerary.intent.date_window.end),
                total_cost_cents=itinerary.cost_breakdown.total_usd_cents,
            )
            results.append(summary)

        # Sort by created_at descending
        results.sort(key=lambda x: x.created_at, reverse=True)

        return results[:limit]


class InMemoryIdempotencyStore:
    """In-memory implementation of IdempotencyStore."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, uuid.UUID], IdempotencyRecord] = {}

    def get(self, key: str, user_id: uuid.UUID) -> IdempotencyRecord | None:
        """Get idempotency record."""
        record = self._records.get((key, user_id))

        if record is None:
            return None

        # Check if expired
        if datetime.now() > record.ttl_until:
            del self._records[(key, user_id)]
            return None

        return record

    def set_pending(self, key: str, user_id: uuid.UUID, ttl_until: datetime) -> None:
        """Set idempotency record to pending."""
        record = IdempotencyRecord(
            key=key,
            user_id=user_id,
            ttl_until=ttl_until,
            status=IdempotencyStatus.pending,
            response=None,
        )
        self._records[(key, user_id)] = record

    def set_completed(
        self, key: str, user_id: uuid.UUID, ttl_until: datetime, response: StoredResponse
    ) -> None:
        """Set idempotency record to completed with full response envelope."""
        record = IdempotencyRecord(
            key=key,
            user_id=user_id,
            ttl_until=ttl_until,
            status=IdempotencyStatus.completed,
            response=response,
        )
        self._records[(key, user_id)] = record

    def set_error(self, key: str, user_id: uuid.UUID, ttl_until: datetime) -> None:
        """Set idempotency record to error."""
        record = IdempotencyRecord(
            key=key,
            user_id=user_id,
            ttl_until=ttl_until,
            status=IdempotencyStatus.error,
            response=None,
        )
        self._records[(key, user_id)] = record


class InMemoryRateLimiter:
    """In-memory implementation of RateLimiter using fixed window."""

    def __init__(self, max_requests: int, window_seconds: int = 60) -> None:
        """Initialize rate limiter.

        Args:
            max_requests: Maximum requests per window
            window_seconds: Window size in seconds (default 60)
        """
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._windows: dict[str, tuple[datetime, int]] = {}

    def check_quota(self, key: str, now: datetime) -> RetryAfter | None:
        """Check if quota is available."""
        # Get or create window
        if key in self._windows:
            window_start, count = self._windows[key]

            # Check if window expired
            if now >= window_start + timedelta(seconds=self._window_seconds):
                # New window
                self._windows[key] = (now, 1)
                return None

            # Within same window
            if count >= self._max_requests:
                # Over quota
                seconds_remaining = int(
                    (window_start + timedelta(seconds=self._window_seconds) - now).total_seconds()
                )
                return RetryAfter(seconds=max(1, seconds_remaining))

            # Increment count
            self._windows[key] = (window_start, count + 1)
            return None
        else:
            # First request
            self._windows[key] = (now, 1)
            return None
