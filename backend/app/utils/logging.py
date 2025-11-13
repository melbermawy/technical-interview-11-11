"""Structured logging for tool execution - PR-3."""

import logging
from typing import Any

from backend.app.tools.executor import ToolContext

logger = logging.getLogger(__name__)


class StructuredToolLogger:
    """Structured logger for tool execution."""

    def log_attempt(
        self,
        ctx: ToolContext,
        attempt: int,
        outcome: str,
        latency_ms: float,
        cache_hit: bool = False,
        error_reason: str | None = None,
    ) -> None:
        """Log tool execution attempt with structured data."""
        log_data: dict[str, Any] = {
            "trace_id": ctx.trace_id,
            "run_id": ctx.run_id,
            "tool": ctx.tool_name,
            "attempt": attempt,
            "outcome": outcome,
            "latency_ms": round(latency_ms, 2),
            "cache_hit": cache_hit,
        }

        if error_reason:
            log_data["error_reason"] = error_reason

        log_msg = f"Tool execution: {ctx.tool_name} - {outcome}"

        if outcome in ("success", "cache_hit"):
            logger.info(log_msg, extra={"structured": log_data})
        else:
            logger.warning(log_msg, extra={"structured": log_data})
