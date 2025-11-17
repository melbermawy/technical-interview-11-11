"""Graph state model for orchestration."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from backend.app.models.intent import IntentV1
from backend.app.models.itinerary import Decision
from backend.app.models.plan import PlanV1
from backend.app.models.violations import Violation

RunStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]


@dataclass
class GraphState:
    """State for the agent graph execution.

    Aligned with SPEC §5 but kept minimal for PR-4A stub.
    """

    run_id: UUID
    org_id: UUID
    user_id: UUID
    status: RunStatus = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = field(default_factory=lambda: datetime.utcnow())

    # Graph data (all optional during execution)
    intent: IntentV1 | None = None
    plan: PlanV1 | None = None
    violations: list[Violation] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)

    # Debug/tracking
    rng_seed: int = 42
    sequence_counter: int = 0

    def next_sequence(self) -> int:
        """Get next sequence number for events."""
        seq = self.sequence_counter
        self.sequence_counter += 1
        return seq
