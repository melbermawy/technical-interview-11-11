"""Rate limiting utilities."""

from datetime import datetime

import redis

from backend.app.db.context import RequestContext
from backend.app.db.repositories import RetryAfter


def make_rate_limit_key(ctx: RequestContext, bucket: str) -> str:
    """Create rate limit key from context and bucket.

    Args:
        ctx: Request context
        bucket: Bucket name (e.g., "agent_run", "crud")

    Returns:
        Rate limit key
    """
    return f"{ctx.org_id}:{ctx.user_id}:{bucket}"


class RedisRateLimiter:
    """Redis-based rate limiter using INCR + EXPIRE pattern."""

    def __init__(self, redis_client: redis.Redis, max_requests: int, window_seconds: int = 60) -> None:
        """Initialize rate limiter.

        Args:
            redis_client: Redis client
            max_requests: Maximum requests per window
            window_seconds: Window size in seconds (default 60)
        """
        self._redis = redis_client
        self._max_requests = max_requests
        self._window_seconds = window_seconds

    def check_quota(self, key: str, now: datetime) -> RetryAfter | None:
        """Check if quota is available.

        Uses Redis INCR + EXPIRE for atomic counting.

        Args:
            key: Rate limit key
            now: Current timestamp

        Returns:
            RetryAfter if over quota, None if allowed
        """
        # Use a window-aligned key
        window_start = int(now.timestamp() / self._window_seconds) * self._window_seconds
        redis_key = f"ratelimit:{key}:{window_start}"

        # Atomic increment
        count = self._redis.incr(redis_key)

        # Set expiry on first request
        if count == 1:
            self._redis.expire(redis_key, self._window_seconds)

        if count > self._max_requests:
            # Over quota - calculate retry-after
            ttl = self._redis.ttl(redis_key)
            return RetryAfter(seconds=max(1, ttl))

        return None
