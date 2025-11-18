"""Graph state model for orchestration."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from backend.app.models.intent import IntentV1
from backend.app.models.itinerary import Decision
from backend.app.models.plan import Choice, PlanV1
from backend.app.models.tool_results import WeatherDay
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
    # Normalized candidate options (flight, lodging, attraction, transit, etc),
    # each with ChoiceFeatures and Provenance attached
    choices: list[Choice] | None = None
    weather: list[WeatherDay] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    has_blocking_violations: bool = False
    decisions: list[Decision] = field(default_factory=list)
    # Selector decision logs with score breakdowns (PR-6B)
    selector_logs: list[dict[str, Any]] = field(default_factory=list)

    # Debug/tracking
    rng_seed: int = 42
    sequence_counter: int = 0

    def next_sequence(self) -> int:
        """Get next sequence number for events."""
        seq = self.sequence_counter
        self.sequence_counter += 1
        return seq
