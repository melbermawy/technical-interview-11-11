"""Tests for idempotency with full response replay."""

import uuid
from datetime import datetime, timedelta

from backend.app.db.inmemory import InMemoryIdempotencyStore
from backend.app.db.repositories import IdempotencyStatus, StoredResponse
from backend.app.middleware.idempotency import IdempotencyMiddleware


def test_idempotency_store_pending() -> None:
    """Test setting and getting pending status."""
    store = InMemoryIdempotencyStore()
    user_id = uuid.uuid4()
    key = "test-key-123"
    ttl_until = datetime.now() + timedelta(hours=1)

    # Initially no record
    record = store.get(key, user_id)
    assert record is None

    # Set pending
    store.set_pending(key, user_id, ttl_until)

    # Get record
    record = store.get(key, user_id)
    assert record is not None
    assert record.key == key
    assert record.user_id == user_id
    assert record.status == IdempotencyStatus.pending
    assert record.response is None


def test_idempotency_store_completed_with_response() -> None:
    """Test setting completed status with full response envelope."""
    store = InMemoryIdempotencyStore()
    user_id = uuid.uuid4()
    key = "test-key-456"
    ttl_until = datetime.now() + timedelta(hours=1)

    response = StoredResponse(
        status_code=201,
        headers={"Content-Type": "application/json", "X-Custom": "test"},
        body=b'{"result": "success", "data": [1, 2, 3]}',
    )

    store.set_completed(key, user_id, ttl_until, response)

    record = store.get(key, user_id)
    assert record is not None
    assert record.status == IdempotencyStatus.completed
    assert record.response is not None
    assert record.response.status_code == 201
    assert record.response.headers["X-Custom"] == "test"
    assert record.response.body == b'{"result": "success", "data": [1, 2, 3]}'


def test_idempotency_store_ttl_expiry() -> None:
    """Test that expired records are not returned."""
    store = InMemoryIdempotencyStore()
    user_id = uuid.uuid4()
    key = "test-key-expired"
    ttl_until = datetime.now() - timedelta(seconds=1)  # Already expired

    store.set_pending(key, user_id, ttl_until)

    # Get should return None for expired record
    record = store.get(key, user_id)
    assert record is None


def test_idempotency_middleware_first_request() -> None:
    """Test idempotency middleware on first request."""
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(store, ttl_seconds=3600)
    user_id = uuid.uuid4()

    # Define a simple handler
    def handler(request: dict) -> dict:
        return {"result": "success", "data": request["input"]}

    wrapped = middleware.wrap_handler(handler, user_id)

    # First request with idempotency key
    status, body, headers = wrapped({"input": "test"}, "key-001")

    assert status == 200
    assert body["result"] == "success"
    assert body["data"] == "test"
    assert "X-Idempotent-Replay" not in headers

    # Check record was stored with full response
    record = store.get("key-001", user_id)
    assert record is not None
    assert record.status == IdempotencyStatus.completed
    assert record.response is not None
    assert record.response.status_code == 200


def test_idempotency_replay_returns_identical_body_and_status() -> None:
    """Test that replay returns exact same body and status code."""
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(store, ttl_seconds=3600)
    user_id = uuid.uuid4()

    call_count = 0

    def handler(request: dict) -> dict:
        nonlocal call_count
        call_count += 1
        return {"result": "success", "count": call_count, "items": [1, 2, 3]}

    wrapped = middleware.wrap_handler(handler, user_id)

    # First request
    status1, body1, headers1 = wrapped({"input": "test"}, "key-002")
    assert status1 == 200
    assert call_count == 1
    assert body1["count"] == 1
    assert body1["items"] == [1, 2, 3]
    assert "X-Idempotent-Replay" not in headers1

    # Second request with same key - should replay exactly
    status2, body2, headers2 = wrapped({"input": "test"}, "key-002")
    assert status2 == 200
    assert call_count == 1  # Handler not called again
    assert body2["count"] == 1  # Same count as first response
    assert body2["items"] == [1, 2, 3]  # Same items
    assert body2 == body1  # Exact equality
    assert headers2.get("X-Idempotent-Replay") == "true"


def test_idempotency_replay_preserves_headers() -> None:
    """Test that replay preserves custom headers from original response."""
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(store, ttl_seconds=3600)
    user_id = uuid.uuid4()

    def handler(request: dict) -> dict:
        return {"result": "ok"}

    wrapped = middleware.wrap_handler(handler, user_id)

    # First request
    status1, body1, headers1 = wrapped({"input": "test"}, "key-003")
    assert status1 == 200
    assert headers1.get("Content-Type") == "application/json"

    # Second request - should preserve Content-Type and add replay header
    status2, body2, headers2 = wrapped({"input": "test"}, "key-003")
    assert status2 == 200
    assert headers2.get("Content-Type") == "application/json"
    assert headers2.get("X-Idempotent-Replay") == "true"


def test_idempotency_middleware_pending_request() -> None:
    """Test idempotency middleware returns 409 for pending."""
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(store, ttl_seconds=3600)
    user_id = uuid.uuid4()
    key = "key-004"

    # Manually set pending
    ttl_until = datetime.now() + timedelta(hours=1)
    store.set_pending(key, user_id, ttl_until)

    def handler(request: dict) -> dict:
        return {"result": "success"}

    wrapped = middleware.wrap_handler(handler, user_id)

    # Request should return 409
    status, body, headers = wrapped({"input": "test"}, key)
    assert status == 409
    assert "still in progress" in body["detail"]


def test_idempotency_middleware_error_state() -> None:
    """Test idempotency middleware handles error state."""
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(store, ttl_seconds=3600)
    user_id = uuid.uuid4()
    key = "key-005"

    # Manually set error
    ttl_until = datetime.now() + timedelta(hours=1)
    store.set_error(key, user_id, ttl_until)

    def handler(request: dict) -> dict:
        return {"result": "success"}

    wrapped = middleware.wrap_handler(handler, user_id)

    # Request should return 500
    status, body, headers = wrapped({"input": "test"}, key)
    assert status == 500
    assert "failed" in body["detail"]


def test_idempotency_without_key() -> None:
    """Test that requests without idempotency key execute normally."""
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(store, ttl_seconds=3600)
    user_id = uuid.uuid4()

    call_count = 0

    def handler(request: dict) -> dict:
        nonlocal call_count
        call_count += 1
        return {"result": "success", "count": call_count}

    wrapped = middleware.wrap_handler(handler, user_id)

    # Multiple requests without key should all execute
    status1, body1, headers1 = wrapped({"input": "test"}, None)
    assert status1 == 200
    assert body1["count"] == 1

    status2, body2, headers2 = wrapped({"input": "test"}, None)
    assert status2 == 200
    assert body2["count"] == 2  # Handler called again
