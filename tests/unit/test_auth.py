"""Unit tests for auth module - PR-4A."""

import uuid

import pytest
from fastapi import HTTPException

from backend.app.api.auth import get_current_context


@pytest.mark.asyncio
async def test_get_current_context_no_header_uses_defaults() -> None:
    """Test that missing auth header uses test defaults."""
    ctx = await get_current_context(authorization=None)

    assert ctx.org_id == uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert ctx.user_id == uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest.mark.asyncio
async def test_get_current_context_valid_token_format() -> None:
    """Test valid org:user token format."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    ctx = await get_current_context(authorization=f"Bearer {org_id}:{user_id}")

    assert ctx.org_id == org_id
    assert ctx.user_id == user_id


@pytest.mark.asyncio
async def test_get_current_context_invalid_bearer_format() -> None:
    """Test invalid bearer format raises 401."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_context(authorization="NotBearer token")

    assert exc_info.value.status_code == 401
    assert "Invalid authorization header format" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_current_context_invalid_uuid_format() -> None:
    """Test invalid UUID format raises 401."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_context(authorization="Bearer not-a-uuid:also-not")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_context_jwt_not_implemented() -> None:
    """Test JWT tokens (not yet implemented) raise 401."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_context(authorization="Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")

    assert exc_info.value.status_code == 401
    assert "JWT validation not yet implemented" in exc_info.value.detail
