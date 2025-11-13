"""Intent models - user input and preferences."""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from backend.app.models.common import TimeWindow


class DateWindow(BaseModel):
    """Date range with timezone."""

    start: date
    end: date
    tz: str = Field(..., description="IANA timezone, e.g., 'Europe/Paris'")

    @field_validator("end")
    @classmethod
    def validate_end_after_start(cls, v: date, info: ValidationInfo) -> date:
        """Ensure end >= start."""
        if "start" in info.data and v < info.data["start"]:
            raise ValueError("end must be >= start")
        return v


class LockedSlot(BaseModel):
    """User-pinned activity slot."""

    day_offset: int = Field(..., ge=0, description="0-indexed from trip start")
    window: TimeWindow
    activity_id: str


class Preferences(BaseModel):
    """User preferences and constraints."""

    kid_friendly: bool = False
    themes: list[str] = Field(default_factory=list)
    avoid_overnight: bool = False
    locked_slots: list[LockedSlot] = Field(default_factory=list)


class IntentV1(BaseModel):
    """User intent for trip planning."""

    city: str
    date_window: DateWindow
    budget_usd_cents: Annotated[int, Field(gt=0)]
    airports: Annotated[list[str], Field(min_length=1)]
    prefs: Preferences

    @field_validator("airports")
    @classmethod
    def validate_airports_not_empty(cls, v: list[str]) -> list[str]:
        """Ensure at least one airport."""
        if not v:
            raise ValueError("airports must contain at least one IATA code")
        return v
