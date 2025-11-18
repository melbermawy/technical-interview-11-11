"""Violation models - constraint violations found during verification."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# JSON-serializable value types for violation details
JsonValue = str | int | float | bool | None | dict[str, Any] | list[Any]


class ViolationSeverity(str, Enum):
    """Severity levels for constraint violations."""

    ADVISORY = "advisory"
    BLOCKING = "blocking"


class ViolationKind(str, Enum):
    """Categories of verification constraints."""

    BUDGET = "budget"
    FEASIBILITY = "feasibility"
    WEATHER = "weather"
    PREFERENCES = "preferences"


class Violation(BaseModel):
    """A constraint violation detected during verification.

    Violations indicate that the current plan does not satisfy
    some constraint from the user's intent or physical/temporal feasibility.
    """

    kind: ViolationKind
    code: str  # Machine-usable short code, e.g., "OVER_BUDGET"
    message: str  # Human-readable description (1-2 sentences)
    severity: ViolationSeverity
    affected_choice_ids: list[str]  # Choice.option_ref values
    details: dict[str, JsonValue] = Field(default_factory=dict)
