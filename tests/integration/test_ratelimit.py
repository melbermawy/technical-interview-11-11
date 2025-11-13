"""Tests for rate limiting."""

import uuid
from datetime import datetime, timedelta

from backend.app.db.context import RequestContext
from backend.app.db.inmemory import InMemoryRateLimiter
from backend.app.middleware.ratelimit import RateLimitMiddleware, create_default_bucket_map
from backend.app.ratelimit import make_rate_limit_key


def test_rate_limiter_allows_under_quota() -> None:
    """Test rate limiter allows requests under quota."""
    limiter = InMemoryRateLimiter(max_requests=5, window_seconds=60)
    now = datetime.now()

    key = "test:key:bucket"

    # First 5 requests should succeed
    for i in range(5):
        retry_after = limiter.check_quota(key, now + timedelta(seconds=i))
        assert retry_after is None


def test_rate_limiter_blocks_over_quota() -> None:
    """Test rate limiter blocks requests over quota."""
    limiter = InMemoryRateLimiter(max_requests=3, window_seconds=60)
    now = datetime.now()

    key = "test:key:bucket"

    # First 3 requests succeed
    for _ in range(3):
        retry_after = limiter.check_quota(key, now)
        assert retry_after is None

    # 4th request should be blocked
    retry_after = limiter.check_quota(key, now)
    assert retry_after is not None
    assert retry_after.seconds > 0


def test_rate_limiter_resets_after_window() -> None:
    """Test rate limiter resets quota after window expires."""
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)
    now = datetime.now()

    key = "test:key:bucket"

    # Use up quota
    limiter.check_quota(key, now)
    limiter.check_quota(key, now)

    # Next request blocked
    retry_after = limiter.check_quota(key, now)
    assert retry_after is not None

    # After window expires, quota resets
    future = now + timedelta(seconds=61)
    retry_after = limiter.check_quota(key, future)
    assert retry_after is None


def test_rate_limiter_separate_keys() -> None:
    """Test rate limiter tracks separate keys independently."""
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)
    now = datetime.now()

    key1 = "test:user1:bucket"
    key2 = "test:user2:bucket"

    # Use up quota for key1
    limiter.check_quota(key1, now)
    limiter.check_quota(key1, now)

    # key1 is blocked
    retry_after = limiter.check_quota(key1, now)
    assert retry_after is not None

    # key2 still has quota
    retry_after = limiter.check_quota(key2, now)
    assert retry_after is None


def test_make_rate_limit_key() -> None:
    """Test rate limit key generation."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    ctx = RequestContext(org_id=org_id, user_id=user_id)

    key = make_rate_limit_key(ctx, "agent_run")

    assert str(org_id) in key
    assert str(user_id) in key
    assert "agent_run" in key


def test_rate_limit_middleware_allows() -> None:
    """Test rate limit middleware allows requests under quota."""
    limiter = InMemoryRateLimiter(max_requests=5, window_seconds=60)
    bucket_map = {"/plan": "agent_run"}
    middleware = RateLimitMiddleware(limiter, bucket_map)

    ctx = RequestContext(org_id=uuid.uuid4(), user_id=uuid.uuid4())
    now = datetime.now()

    # First 5 requests should be allowed
    for _ in range(5):
        allowed, retry_after = middleware.check_rate_limit("/plan", ctx, now)
        assert allowed is True
        assert retry_after == 0


def test_rate_limit_middleware_blocks() -> None:
    """Test rate limit middleware blocks requests over quota."""
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)
    bucket_map = {"/plan": "agent_run"}
    middleware = RateLimitMiddleware(limiter, bucket_map)

    ctx = RequestContext(org_id=uuid.uuid4(), user_id=uuid.uuid4())
    now = datetime.now()

    # First 2 requests allowed
    middleware.check_rate_limit("/plan", ctx, now)
    middleware.check_rate_limit("/plan", ctx, now)

    # 3rd request blocked
    allowed, retry_after = middleware.check_rate_limit("/plan", ctx, now)
    assert allowed is False
    assert retry_after > 0


def test_rate_limit_middleware_no_limit_for_unmapped_path() -> None:
    """Test rate limit middleware allows unmapped paths."""
    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=60)
    bucket_map = {"/plan": "agent_run"}
    middleware = RateLimitMiddleware(limiter, bucket_map)

    ctx = RequestContext(org_id=uuid.uuid4(), user_id=uuid.uuid4())
    now = datetime.now()

    # Unmapped path should be allowed (no rate limit)
    allowed, retry_after = middleware.check_rate_limit("/some/other/path", ctx, now)
    assert allowed is True
    assert retry_after == 0


def test_create_default_bucket_map() -> None:
    """Test default bucket map creation."""
    bucket_map = create_default_bucket_map()

    assert "/plan" in bucket_map
    assert bucket_map["/plan"] == "agent_run"
    assert "/itinerary" in bucket_map
    assert bucket_map["/itinerary"] == "crud"
