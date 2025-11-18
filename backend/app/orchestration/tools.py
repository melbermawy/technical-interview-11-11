"""Tool runner with structured logging (PR-11A)."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

from backend.app.models.tools import JsonValue, ToolCallLog
from backend.app.orchestration.state import GraphState

T = TypeVar("T")


async def run_tool(
    *,
    name: str,
    state: GraphState,
    call: Callable[[], Awaitable[T]],
    input_summary: dict[str, JsonValue] | None = None,
    output_counter: Callable[[T], dict[str, JsonValue]] | None = None,
) -> T:
    """Execute a tool call with structured logging.

    Wraps any async tool call to capture timing, success/failure, and
    small input/output summaries. Appends a ToolCallLog to state.tool_calls.

    Args:
        name: Tool name (e.g. "adapter.flights", "docs.search")
        state: GraphState to append log entry to
        call: Async callable that executes the tool
        input_summary: Optional dict of key input parameters (non-PII scalars only)
        output_counter: Optional function to extract summary from result

    Returns:
        Result from the tool call

    Raises:
        Exception: Re-raises any exception from the tool call after logging
    """
    started_at = datetime.now(UTC)
    success = False
    error: str | None = None
    result: T | None = None

    try:
        result = await call()
        success = True
    except Exception as e:
        success = False
        error = str(e)
        raise
    finally:
        finished_at = datetime.now(UTC)
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        # Build summaries
        final_input_summary = input_summary if input_summary is not None else {}
        final_output_summary: dict[str, JsonValue] = {}
        if success and output_counter is not None and result is not None:
            final_output_summary = output_counter(result)

        # Create and append log entry
        log = ToolCallLog(
            name=name,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            success=success,
            error=error,
            input_summary=final_input_summary,
            output_summary=final_output_summary,
        )
        state.tool_calls.append(log)

    # Type checker knows result can't be None here since we either
    # assigned it in try block or raised in except block
    assert result is not None
    return result
