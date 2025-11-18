"""What-if replanning models (PR-9A)."""

from pydantic import BaseModel, Field


class WhatIfPatch(BaseModel):
    """Structured patch for creating what-if child runs.

    Defines minimal, explicit transformations to apply to a base IntentV1.
    All fields are optional; an empty patch produces identical intent.
    """

    # Budget adjustments (mutually exclusive; new_budget_usd_cents wins if both set)
    new_budget_usd_cents: int | None = Field(
        default=None, gt=0, description="Explicit budget override in cents"
    )
    budget_delta_usd_cents: int | None = Field(
        default=None, description="Additive budget adjustment (can be negative, clamped at 0)"
    )

    # Theme adjustments
    add_themes: list[str] | None = Field(
        default=None, description="Themes to add to intent.prefs.themes (deduplicated)"
    )
    remove_themes: list[str] | None = Field(
        default=None, description="Themes to remove from intent.prefs.themes"
    )

    # Date adjustments
    shift_days: int | None = Field(
        default=None, description="Days to shift date_window (can be negative)"
    )

    # Scenario metadata
    notes: str | None = Field(
        default=None, max_length=500, description="Free-form description of the what-if scenario"
    )
