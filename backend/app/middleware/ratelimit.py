"""Rate limiting middleware."""

from datetime import datetime

from backend.app.db.context import RequestContext
from backend.app.db.repositories import RateLimiter
from backend.app.ratelimit import make_rate_limit_key


class RateLimitMiddleware:
    """Middleware for rate limiting HTTP requests.

    Maps request paths to buckets and enforces rate limits.
    """

    def __init__(self, limiter: RateLimiter, bucket_map: dict[str, str]) -> None:
        """Initialize rate limit middleware.

        Args:
            limiter: Rate limiter implementation
            bucket_map: Mapping from path patterns to bucket names
        """
        self._limiter = limiter
        self._bucket_map = bucket_map

    def check_rate_limit(
        self, path: str, ctx: RequestContext, now: datetime | None = None
    ) -> tuple[bool, int]:
        """Check if request is allowed under rate limit.

        Args:
            path: Request path
            ctx: Request context
            now: Current time (for testing)

        Returns:
            Tuple of (allowed, retry_after_seconds)
        """
        if now is None:
            now = datetime.now()

        # Determine bucket from path
        bucket = self._get_bucket(path)

        if bucket is None:
            # No rate limit for this path
            return (True, 0)

        # Check quota
        key = make_rate_limit_key(ctx, bucket)
        retry_after = self._limiter.check_quota(key, now)

        if retry_after is None:
            return (True, 0)

        return (False, retry_after.seconds)

    def _get_bucket(self, path: str) -> str | None:
        """Get bucket name for path.

        Args:
            path: Request path

        Returns:
            Bucket name or None if no rate limit
        """
        for pattern, bucket in self._bucket_map.items():
            if pattern in path:
                return bucket

        return None


def create_default_bucket_map() -> dict[str, str]:
    """Create default bucket mapping.

    Returns:
        Dictionary mapping path patterns to bucket names
    """
    return {
        "/plan": "agent_run",
        "/itinerary": "crud",
        "/run": "crud",
    }
