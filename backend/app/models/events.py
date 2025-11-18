"""Run event models - what happened during graph execution."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


NodeName = Literal[
    "intent",
    "planner",
    "selector",
    "tool_exec",
    "verifier",
    "repair",
    "docs",
    "synth",
    "responder",
]

Phase = Literal["started", "completed"]


class RunEvent(BaseModel):
    """Event emitted during agent run execution.

    Per SPEC §8: Events track node execution and provide SSE stream content.
    """

    id: UUID
    run_id: UUID
    org_id: UUID
    timestamp: datetime
    sequence: int = Field(..., ge=0, description="Monotonic per run")
    node: NodeName
    phase: Phase
    summary: str = Field(..., description="Human-readable summary")
    payload: dict[str, Any] = Field(default_factory=dict)


class SSERunEvent(BaseModel):
    """Lightweight SSE event for streaming.

    Derived from RunEvent but omits large payloads for transmission.
    """

    run_id: str
    timestamp: str  # ISO8601
    sequence: int
    node: NodeName
    phase: Phase
    summary: str

    @classmethod
    def from_run_event(cls, event: RunEvent) -> "SSERunEvent":
        """Convert RunEvent to SSE format."""
        return cls(
            run_id=str(event.run_id),
            timestamp=event.timestamp.isoformat(),
            sequence=event.sequence,
            node=event.node,
            phase=event.phase,
            summary=event.summary,
        )
