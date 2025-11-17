"""Common types and enums shared across all models."""

from datetime import datetime, time
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Geo(BaseModel):
    """Geographic coordinates (WGS84)."""

    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class TimeWindow(BaseModel):
    """Time window in local time."""

    start: time
    end: time


class Money(BaseModel):
    """Monetary amount in cents."""

    amount_cents: int = Field(..., gt=0)
    currency: str = "USD"


class ChoiceKind(str, Enum):
    """Type of activity choice."""

    flight = "flight"
    lodging = "lodging"
    attraction = "attraction"
    transit = "transit"
    meal = "meal"


class Tier(str, Enum):
    """Lodging tier."""

    budget = "budget"
    mid = "mid"
    luxury = "luxury"


class TransitMode(str, Enum):
    """Transit mode."""

    walk = "walk"
    metro = "metro"
    bus = "bus"
    taxi = "taxi"


class ViolationKind(str, Enum):
    """Violation type."""

    budget_exceeded = "budget_exceeded"
    timing_infeasible = "timing_infeasible"
    venue_closed = "venue_closed"
    weather_unsuitable = "weather_unsuitable"
    pref_violated = "pref_violated"


class Provenance(BaseModel):
    """Provenance metadata for tool results."""

    source: str  # Tool-specific identifier (e.g., "tool.weather.open_meteo", "rag", "user")
    ref_id: str | None = None
    source_url: str | None = None
    fetched_at: datetime
    cache_hit: bool | None = None
    response_digest: str | None = None
