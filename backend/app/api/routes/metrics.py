"""Prometheus metrics endpoint - PR-3."""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter()


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics endpoint.

    Exposes all registered Prometheus metrics including:
    - tool_latency_ms{tool, outcome}
    - tool_errors_total{tool, reason}
    - tool_cache_hits_total{tool}
    """
    metrics_output = generate_latest()
    return Response(content=metrics_output, media_type=CONTENT_TYPE_LATEST)
