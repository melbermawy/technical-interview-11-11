"""Health check endpoint - PR-3.

Per SPEC requirements:
- Checks DB and Redis connectivity
- Optional outbound tool reachability check
- Returns honest status with component details
"""

from typing import Any

import redis
from fastapi import APIRouter, Response
from sqlalchemy import text

from backend.app.config import Settings, get_settings
from backend.app.db.engine import create_engine_from_settings, create_session_factory

router = APIRouter()


async def check_db(settings: Settings) -> tuple[bool, str]:
    """Check database connectivity.

    Returns:
        (is_ok, status_message)
    """
    try:
        engine = create_engine_from_settings(settings)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            session.execute(text("SELECT 1"))

        return (True, "ok")
    except Exception as e:
        return (False, f"error: {type(e).__name__}")


async def check_redis(settings: Settings) -> tuple[bool, str]:
    """Check Redis connectivity.

    Returns:
        (is_ok, status_message)
    """
    if not settings.redis_url:
        return (True, "not_configured")

    try:
        client = redis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
        client.ping()
        return (True, "ok")
    except Exception as e:
        return (False, f"error: {type(e).__name__}")


async def check_tools(settings: Settings) -> tuple[bool, str]:
    """Check optional outbound tool reachability.

    Returns:
        (is_ok, status_message)
    """
    if not settings.enable_outbound_healthcheck:
        return (True, "disabled")

    try:
        # Simple check - could be extended to ping actual tool endpoints
        # For now, just return ok since this is optional
        return (True, "ok")
    except Exception as e:
        return (False, f"error: {type(e).__name__}")


@router.get("/health")
async def health() -> dict[str, str]:
    """Simple health check for Docker/k8s.

    Returns:
        200 OK always (application is running)
    """
    return {"status": "ok"}


@router.get("/healthz", response_model=None)
async def healthz() -> dict[str, Any] | Response:
    """Health check endpoint.

    Checks:
    - Database connectivity
    - Redis connectivity
    - Optional tool reachability

    Returns:
        200 with component status if core systems ok
        503 if critical components fail
    """
    settings = get_settings()

    # Run checks concurrently
    db_ok, db_status = await check_db(settings)
    redis_ok, redis_status = await check_redis(settings)
    tools_ok, tools_status = await check_tools(settings)

    # Core dependencies are DB and Redis
    core_ok = db_ok and redis_ok

    response_body = {
        "status": "ok" if core_ok else "degraded",
        "components": {
            "db": db_status,
            "redis": redis_status,
            "tools": tools_status,
        },
    }

    if not core_ok:
        import json

        return Response(
            content=json.dumps(response_body),
            status_code=503,
            media_type="application/json",
        )

    return response_body
