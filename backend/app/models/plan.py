"""Plan models - generated travel plan with ranked choices."""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.models.common import ChoiceKind, Provenance, TimeWindow


class ChoiceFeatures(BaseModel):
    """Extracted features from a choice (required for selector)."""

    cost_usd_cents: int
    travel_seconds: int | None = None
    indoor: bool | None = None
    themes: list[str] = Field(default_factory=list)


class Choice(BaseModel):
    """A single choice alternative with features."""

    kind: ChoiceKind
    option_ref: str
    features: ChoiceFeatures
    score: float | None = None
    provenance: Provenance


class Slot(BaseModel):
    """Time slot with ranked choices."""

    window: TimeWindow
    choices: Annotated[list[Choice], Field(min_length=1)]
    locked: bool = False

    @field_validator("choices")
    @classmethod
    def validate_choices_not_empty(cls, v: list[Choice]) -> list[Choice]:
        """Ensure at least one choice exists."""
        if not v:
            raise ValueError("choices must contain at least one alternative")
        return v


class DayPlan(BaseModel):
    """Plan for a single day."""

    date: date
    slots: list[Slot]

    @model_validator(mode="after")
    def validate_non_overlapping_slots(self) -> "DayPlan":
        """Ensure slots do not overlap."""
        if len(self.slots) < 2:
            return self

        sorted_slots = sorted(self.slots, key=lambda s: s.window.start)
        for i in range(len(sorted_slots) - 1):
            current_end = sorted_slots[i].window.end
            next_start = sorted_slots[i + 1].window.start
            if current_end > next_start:
                raise ValueError(f"Overlapping slots: {current_end} > {next_start} on {self.date}")
        return self


class Assumptions(BaseModel):
    """Planning assumptions and constants."""

    fx_rate_usd_eur: float
    daily_spend_est_cents: int
    transit_buffer_minutes: int = 15
    airport_buffer_minutes: int = 120


class PlanV1(BaseModel):
    """Complete travel plan with days and assumptions."""

    days: Annotated[list[DayPlan], Field(min_length=4, max_length=7)]
    assumptions: Assumptions
    rng_seed: int

    @field_validator("days")
    @classmethod
    def validate_days_length(cls, v: list[DayPlan]) -> list[DayPlan]:
        """Ensure 4-7 days."""
        if not 4 <= len(v) <= 7:
            raise ValueError(f"days must be 4-7, got {len(v)}")
        return v
