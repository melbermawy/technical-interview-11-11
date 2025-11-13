"""Repository protocol interfaces for data access."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import UUID

from backend.app.db.context import RequestContext
from backend.app.models.intent import IntentV1
from backend.app.models.itinerary import ItineraryV1


@dataclass
class AgentRunRecord:
    """Agent run data record."""

    run_id: UUID
    org_id: UUID
    user_id: UUID
    intent: dict
    plan_snapshot: list[dict] | None
    tool_log: dict | None
    cost_usd: float | None
    trace_id: str
    status: str
    created_at: datetime
    completed_at: datetime | None


@dataclass
class ItinerarySummary:
    """Summary of an itinerary for listing."""

    itinerary_id: UUID
    run_id: UUID
    created_at: datetime
    city: str
    date_start: str
    date_end: str
    total_cost_cents: int


class RunRepository(Protocol):
    """Repository for agent run operations."""

    def create_run(self, intent: IntentV1, ctx: RequestContext) -> UUID:
        """Create a new agent run.

        Args:
            intent: User intent
            ctx: Request context with org/user IDs

        Returns:
            Run ID
        """
        ...

    def update_run(
        self,
        run_id: UUID,
        ctx: RequestContext,
        *,
        status: str,
        plan_snapshot: list[dict] | None = None,
        tool_log: dict | None = None,
        cost_usd: float | None = None,
    ) -> None:
        """Update an existing agent run.

        Args:
            run_id: Run ID
            ctx: Request context (enforces tenancy)
            status: Run status
            plan_snapshot: Optional plan snapshot list
            tool_log: Optional tool execution log
            cost_usd: Optional cost in USD
        """
        ...

    def get_run(self, run_id: UUID, ctx: RequestContext) -> AgentRunRecord | None:
        """Get agent run by ID.

        Args:
            run_id: Run ID
            ctx: Request context (enforces tenancy)

        Returns:
            Agent run record or None if not found
        """
        ...


class ItineraryRepository(Protocol):
    """Repository for itinerary operations."""

    def save_itinerary(
        self, run_id: UUID, itinerary: ItineraryV1, ctx: RequestContext
    ) -> UUID:
        """Save a new itinerary.

        Args:
            run_id: Associated agent run ID
            itinerary: Itinerary data
            ctx: Request context

        Returns:
            Itinerary ID
        """
        ...

    def get_itinerary(
        self, itinerary_id: UUID, ctx: RequestContext
    ) -> ItineraryV1 | None:
        """Get itinerary by ID.

        Args:
            itinerary_id: Itinerary ID
            ctx: Request context (enforces tenancy)

        Returns:
            Itinerary or None if not found
        """
        ...

    def list_recent_itineraries(
        self, ctx: RequestContext, limit: int = 10
    ) -> list[ItinerarySummary]:
        """List recent itineraries for user.

        Args:
            ctx: Request context (enforces tenancy)
            limit: Maximum number of results

        Returns:
            List of itinerary summaries
        """
        ...


class IdempotencyStatus(str, Enum):
    """Idempotency record status."""

    pending = "pending"
    completed = "completed"
    error = "error"


@dataclass
class StoredResponse:
    """Stored HTTP response envelope for idempotency replay.

    Per SPEC §9.3: Store full response to enable exact replay.
    """

    status_code: int
    headers: dict[str, str]
    body: bytes


@dataclass
class IdempotencyRecord:
    """Idempotency record."""

    key: str
    user_id: UUID
    ttl_until: datetime
    status: IdempotencyStatus
    response: StoredResponse | None


class IdempotencyStore(Protocol):
    """Store for HTTP idempotency records."""

    def get(self, key: str, user_id: UUID) -> IdempotencyRecord | None:
        """Get idempotency record.

        Args:
            key: Idempotency key
            user_id: User ID

        Returns:
            Record or None if not found
        """
        ...

    def set_pending(self, key: str, user_id: UUID, ttl_until: datetime) -> None:
        """Set idempotency record to pending.

        Args:
            key: Idempotency key
            user_id: User ID
            ttl_until: TTL timestamp
        """
        ...

    def set_completed(
        self, key: str, user_id: UUID, ttl_until: datetime, response: StoredResponse
    ) -> None:
        """Set idempotency record to completed with full response envelope.

        Args:
            key: Idempotency key
            user_id: User ID
            ttl_until: TTL timestamp
            response: Complete response envelope for replay
        """
        ...

    def set_error(self, key: str, user_id: UUID, ttl_until: datetime) -> None:
        """Set idempotency record to error.

        Args:
            key: Idempotency key
            user_id: User ID
            ttl_until: TTL timestamp
        """
        ...


@dataclass
class RetryAfter:
    """Rate limit retry-after information."""

    seconds: int


class RateLimiter(Protocol):
    """Rate limiter interface."""

    def check_quota(self, key: str, now: datetime) -> RetryAfter | None:
        """Check if quota is available.

        Args:
            key: Rate limit key
            now: Current timestamp

        Returns:
            RetryAfter if over quota, None if allowed
        """
        ...
