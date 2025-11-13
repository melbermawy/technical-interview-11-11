"""HTTP idempotency middleware."""

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from backend.app.db.repositories import IdempotencyStatus, IdempotencyStore, StoredResponse


class IdempotencyMiddleware:
    """Middleware for HTTP-level idempotency.

    Implements idempotency semantics per SPEC §9.3:
    - Reads Idempotency-Key header for write endpoints
    - Stores full response envelope (status, headers, body) in IdempotencyStore
    - Replays completed responses exactly with X-Idempotent-Replay header
    - Returns 409 for pending requests
    """

    def __init__(self, store: IdempotencyStore, ttl_seconds: int = 24 * 3600) -> None:
        """Initialize idempotency middleware.

        Args:
            store: Idempotency store implementation
            ttl_seconds: TTL for idempotency records (default 24h)
        """
        self._store = store
        self._ttl_seconds = ttl_seconds

    def wrap_handler(
        self, handler: Callable[[dict[str, Any]], dict[str, Any]], user_id: UUID
    ) -> Callable[[dict[str, Any], str | None], tuple[int, dict[str, Any], dict[str, str]]]:
        """Wrap a handler function with idempotency logic.

        Args:
            handler: Original handler function that returns a dict body
            user_id: User ID from auth

        Returns:
            Wrapped handler that takes (request, idempotency_key) and returns
            (status_code, body, headers)
        """

        def wrapped_handler(
            request: dict[str, Any], idempotency_key: str | None
        ) -> tuple[int, dict[str, Any], dict[str, str]]:
            """Wrapped handler with idempotency logic."""
            if idempotency_key is None:
                # No idempotency key - execute normally
                body = handler(request)
                return (200, body, {})

            # Check existing record
            record = self._store.get(idempotency_key, user_id)

            if record is None:
                # No existing record - create pending
                ttl_until = datetime.now() + timedelta(seconds=self._ttl_seconds)
                self._store.set_pending(idempotency_key, user_id, ttl_until)

                # Execute handler
                try:
                    body = handler(request)
                    status_code = 200
                    headers = {"Content-Type": "application/json"}

                    # Serialize body to bytes for storage
                    body_bytes = json.dumps(body).encode("utf-8")

                    # Store completed with full response envelope
                    stored_response = StoredResponse(
                        status_code=status_code,
                        headers=headers,
                        body=body_bytes,
                    )
                    self._store.set_completed(
                        idempotency_key, user_id, ttl_until, stored_response
                    )

                    return (status_code, body, headers)
                except Exception as e:
                    # Store error state
                    self._store.set_error(idempotency_key, user_id, ttl_until)
                    raise e

            elif record.status == IdempotencyStatus.completed:
                # Replay cached response exactly per SPEC §9.3
                if record.response is None:
                    # Should not happen, but handle gracefully
                    return (
                        500,
                        {"error": "Stored response missing for completed request"},
                        {},
                    )

                # Reconstruct original response from stored envelope
                stored = record.response
                body = json.loads(stored.body.decode("utf-8"))

                # Add replay header
                replay_headers = dict(stored.headers)
                replay_headers["X-Idempotent-Replay"] = "true"

                return (stored.status_code, body, replay_headers)

            elif record.status == IdempotencyStatus.pending:
                # Request still in progress - return 409 per specification
                return (
                    409,
                    {
                        "detail": "Request with this idempotency key is still in progress"
                    },
                    {},
                )

            else:  # error status
                # Previous request failed - return generic 500
                # Design choice: return generic error rather than replay the error details
                # This prevents information leakage and allows retry
                return (
                    500,
                    {
                        "detail": "Previous request with this idempotency key failed",
                        "key": idempotency_key,
                    },
                    {},
                )

        return wrapped_handler
