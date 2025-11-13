"""Models package - re-exports for convenience."""

from backend.app.models.common import (
    ChoiceKind,
    Geo,
    Money,
    Provenance,
    Tier,
    TimeWindow,
    TransitMode,
    ViolationKind,
)
from backend.app.models.intent import DateWindow, IntentV1, LockedSlot, Preferences
from backend.app.models.itinerary import (
    Activity,
    Citation,
    CostBreakdown,
    DayItinerary,
    Decision,
    ItineraryV1,
)
from backend.app.models.plan import Assumptions, Choice, ChoiceFeatures, DayPlan, PlanV1, Slot
from backend.app.models.tool_results import (
    Attraction,
    FlightOption,
    Lodging,
    TransitLeg,
    WeatherDay,
    Window,
)
from backend.app.models.violations import Violation

__all__ = [
    # Common
    "Geo",
    "TimeWindow",
    "Money",
    "ChoiceKind",
    "Tier",
    "TransitMode",
    "ViolationKind",
    "Provenance",
    # Intent
    "IntentV1",
    "DateWindow",
    "Preferences",
    "LockedSlot",
    # Plan
    "PlanV1",
    "DayPlan",
    "Slot",
    "Choice",
    "ChoiceFeatures",
    "Assumptions",
    # Tool results
    "FlightOption",
    "Lodging",
    "Attraction",
    "Window",
    "WeatherDay",
    "TransitLeg",
    # Violations
    "Violation",
    # Itinerary
    "ItineraryV1",
    "DayItinerary",
    "Activity",
    "CostBreakdown",
    "Decision",
    "Citation",
]
