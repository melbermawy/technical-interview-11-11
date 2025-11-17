"""Minimal auth dependency for PR-4A.

Stub implementation that extracts org_id/user_id from bearer token or uses test defaults.
Real JWT validation will be added in PR-10.
"""

import uuid
from typing import Annotated

from fastapi import Header, HTTPException, status

from backend.app.db.context import RequestContext


async def get_current_context(
    authorization: Annotated[str | None, Header()] = None,
) -> RequestContext:
    """Extract request context from authorization header.

    For PR-4A: Stub implementation that either:
    - Parses a simple "Bearer <org_id>:<user_id>" format for testing
    - Returns test defaults if no header

    Real JWT validation will be implemented in PR-10.

    Args:
        authorization: Authorization header (e.g., "Bearer <token>")

    Returns:
        RequestContext with org_id and user_id

    Raises:
        HTTPException: If authorization is invalid
    """
    if not authorization:
        # For PR-4A testing: allow no auth, use test IDs
        return RequestContext(
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[7:]  # Strip "Bearer "

    # Stub: parse "org_id:user_id" format for testing
    if ":" in token:
        try:
            org_id_str, user_id_str = token.split(":", 1)
            return RequestContext(
                org_id=uuid.UUID(org_id_str),
                user_id=uuid.UUID(user_id_str),
            )
        except (ValueError, AttributeError) as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token format (expected org_id:user_id)",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

    # If not in test format, reject
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid bearer token (JWT validation not yet implemented)",
        headers={"WWW-Authenticate": "Bearer"},
    )
