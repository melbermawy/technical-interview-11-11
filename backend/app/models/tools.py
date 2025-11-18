"""Tool call logging models (PR-11A)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# JSON-serializable value type (same as violations.py)
JsonValue = str | int | float | bool | None | dict[str, Any] | list[Any]


class ToolCallLog(BaseModel):
    """Log entry for a single tool call.

    Captures timing, success/failure, and small input/output summaries
    for observability without storing full payloads.
    """

    name: str = Field(..., description="Tool name (e.g. 'adapter.flights', 'docs.search')")
    started_at: datetime = Field(..., description="UTC timestamp when call started")
    finished_at: datetime = Field(..., description="UTC timestamp when call finished")
    duration_ms: int = Field(..., description="Duration in milliseconds")
    success: bool = Field(..., description="True if call succeeded, False if error")
    error: str | None = Field(None, description="Error message if call failed")
    input_summary: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Small summary of inputs (non-PII, key scalars only)",
    )
    output_summary: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Small summary of outputs (counts/aggregates only)",
    )
