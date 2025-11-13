"""Itinerary models - final output for user consumption."""

from datetime import date, datetime

from pydantic import BaseModel

from backend.app.models.common import ChoiceKind, Geo, Provenance, TimeWindow
from backend.app.models.intent import IntentV1


class Activity(BaseModel):
    """Single activity in itinerary."""

    window: TimeWindow
    kind: ChoiceKind
    name: str
    geo: Geo | None
    notes: str
    locked: bool


class DayItinerary(BaseModel):
    """Itinerary for a single day."""

    date: date
    activities: list[Activity]


class CostBreakdown(BaseModel):
    """Cost breakdown by category."""

    flights_usd_cents: int
    lodging_usd_cents: int
    attractions_usd_cents: int
    transit_usd_cents: int
    daily_spend_usd_cents: int
    total_usd_cents: int
    currency_disclaimer: str


class Decision(BaseModel):
    """Recorded decision with rationale."""

    node: str
    rationale: str
    alternatives_considered: int
    selected: str


class Citation(BaseModel):
    """Citation linking claim to provenance."""

    claim: str
    provenance: Provenance


class ItineraryV1(BaseModel):
    """Complete itinerary output."""

    itinerary_id: str
    intent: IntentV1
    days: list[DayItinerary]
    cost_breakdown: CostBreakdown
    decisions: list[Decision]
    citations: list[Citation]
    created_at: datetime
    trace_id: str
