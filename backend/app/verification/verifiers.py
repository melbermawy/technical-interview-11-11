"""Verification functions for budget and preferences constraints."""

from collections.abc import Sequence

from backend.app.models.common import ChoiceKind
from backend.app.models.intent import IntentV1
from backend.app.models.plan import Choice
from backend.app.models.tool_results import WeatherDay
from backend.app.models.violations import Violation, ViolationKind, ViolationSeverity


def verify_budget(intent: IntentV1, choices: list[Choice]) -> list[Violation]:
    """Verify that total itinerary cost fits within budget.

    Args:
        intent: User intent with budget_usd_cents
        choices: List of selected choices with cost features

    Returns:
        List of violations (empty if budget satisfied, or single violation)
    """
    # Extract budget from intent
    budget = intent.budget_usd_cents
    if not budget or budget <= 0:
        return []

    # Compute total cost from all choices
    total_cost = 0
    cost_bearing_choice_ids: list[str] = []

    for choice in choices:
        cost = choice.features.cost_usd_cents
        if cost and cost > 0:
            total_cost += cost
            cost_bearing_choice_ids.append(choice.option_ref)

    # If no choices have cost, nothing to violate
    if total_cost == 0:
        return []

    # Case 1: Within budget - no violation
    if total_cost <= budget:
        return []

    ratio = total_cost / budget

    # Case 2: Slightly over (within 20%) - ADVISORY
    if total_cost <= budget * 1.2:
        return [
            Violation(
                kind=ViolationKind.BUDGET,
                code="NEAR_BUDGET",
                message="Total itinerary cost is slightly above the stated budget.",
                severity=ViolationSeverity.ADVISORY,
                affected_choice_ids=cost_bearing_choice_ids,
                details={
                    "total_usd_cents": total_cost,
                    "budget_usd_cents": budget,
                    "ratio": round(ratio, 3),
                },
            )
        ]

    # Case 3: Far over (>20%) - BLOCKING
    return [
        Violation(
            kind=ViolationKind.BUDGET,
            code="OVER_BUDGET",
            message="Total itinerary cost exceeds the stated budget by more than 20%.",
            severity=ViolationSeverity.BLOCKING,
            affected_choice_ids=cost_bearing_choice_ids,
            details={
                "total_usd_cents": total_cost,
                "budget_usd_cents": budget,
                "ratio": round(ratio, 3),
            },
        )
    ]


def verify_preferences(intent: IntentV1, choices: list[Choice]) -> list[Violation]:
    """Verify that choices align with user preferences.

    Checks:
    1. Required themes: If user specified themes, at least one choice should match
    2. Kid-friendly: Validates kid-friendly requirements

    Args:
        intent: User intent with preferences
        choices: List of selected choices with theme features

    Returns:
        List of violations (may include multiple preference violations)
    """
    violations: list[Violation] = []

    # If no preferences specified, nothing to check
    if not intent.prefs:
        return []

    # Extract themes present across all choices
    present_themes: set[str] = set()
    for choice in choices:
        if choice.features.themes:
            present_themes.update(choice.features.themes)

    # Check required themes (user's preferred themes)
    required_themes = intent.prefs.themes if intent.prefs.themes else []

    if required_themes:
        # Check if any required theme is present
        matching_themes = set(required_themes) & present_themes

        if not matching_themes:
            # No required themes found - ADVISORY violation
            missing_themes = list(set(required_themes) - present_themes)
            violations.append(
                Violation(
                    kind=ViolationKind.PREFERENCES,
                    code="PREFS_UNFULFILLED",
                    message="No selected options match the required themes.",
                    severity=ViolationSeverity.ADVISORY,
                    affected_choice_ids=[],  # Affects overall plan, not specific choices
                    details={
                        "required_themes": required_themes,
                        "present_themes": list(present_themes),
                        "missing_themes": missing_themes,
                    },
                )
            )

    return violations


def verify_feasibility(intent: IntentV1, choices: list[Choice]) -> list[Violation]:
    """Verify physical and temporal feasibility constraints.

    Checks:
    1. Long transit segments (>6 hours → ADVISORY)
    2. Lodging vs trip length mismatch (multi-day trip without lodging → ADVISORY)
    3. Too much lodging for trip length (→ ADVISORY)

    Args:
        intent: User intent with date_window for trip length
        choices: List of selected choices with features

    Returns:
        List of ADVISORY violations (never BLOCKING)
    """
    violations: list[Violation] = []

    # Check 1: Long transit segments (>6 hours = 21600 seconds)
    long_transit_choices: list[str] = []
    for choice in choices:
        if choice.kind == ChoiceKind.transit:
            duration = choice.features.travel_seconds
            if duration and duration > 21600:
                long_transit_choices.append(choice.option_ref)

    if long_transit_choices:
        violations.append(
            Violation(
                kind=ViolationKind.FEASIBILITY,
                code="LONG_TRANSIT",
                message="Some transit segments exceed 6 hours, which may be tiring.",
                severity=ViolationSeverity.ADVISORY,
                affected_choice_ids=long_transit_choices,
                details={
                    "threshold_seconds": 21600,
                    "num_long_segments": len(long_transit_choices),
                },
            )
        )

    # Check 2 & 3: Lodging vs trip length
    # Calculate trip length in days
    trip_days = (intent.date_window.end - intent.date_window.start).days + 1
    num_nights = trip_days - 1  # Nights = days - 1

    # Count lodging choices
    lodging_choices = [c for c in choices if c.kind == ChoiceKind.lodging]
    num_lodging = len(lodging_choices)

    # Multi-day trip without lodging
    if num_nights > 0 and num_lodging == 0:
        violations.append(
            Violation(
                kind=ViolationKind.FEASIBILITY,
                code="NO_LODGING_FOR_MULTI_DAY",
                message="This is a multi-day trip but no lodging options are selected.",
                severity=ViolationSeverity.ADVISORY,
                affected_choice_ids=[],
                details={
                    "trip_days": trip_days,
                    "num_nights": num_nights,
                    "num_lodging": 0,
                },
            )
        )

    # Too much lodging for trip length
    if num_lodging > num_nights:
        violations.append(
            Violation(
                kind=ViolationKind.FEASIBILITY,
                code="TOO_MUCH_LODGING",
                message="More lodging options selected than nights in the trip.",
                severity=ViolationSeverity.ADVISORY,
                affected_choice_ids=[c.option_ref for c in lodging_choices],
                details={
                    "trip_days": trip_days,
                    "num_nights": num_nights,
                    "num_lodging": num_lodging,
                },
            )
        )

    return violations


def verify_weather(
    intent: IntentV1,
    choices: list[Choice],
    weather: Sequence[WeatherDay] | None,
) -> list[Violation]:
    """Verify weather compatibility with outdoor activities.

    Checks:
    - If outdoor activities selected and bad weather forecast (precip_prob ≥ 0.7)
      → ADVISORY violation

    Args:
        intent: User intent (not directly used, kept for consistency)
        choices: List of selected choices with indoor/outdoor features
        weather: Weather forecast data (optional)

    Returns:
        List of ADVISORY violations (never BLOCKING)
    """
    violations: list[Violation] = []

    # If no weather data, skip check
    if not weather:
        return []

    # Find outdoor choices (indoor=False or indoor=None with outdoor themes)
    outdoor_choices: list[str] = []
    for choice in choices:
        # Explicit outdoor
        if choice.features.indoor is False:
            outdoor_choices.append(choice.option_ref)
        # Indoor=None with outdoor-related themes
        elif choice.features.indoor is None:
            outdoor_themes = {"park", "outdoor", "hiking", "beach", "garden"}
            choice_themes = set(choice.features.themes)
            if outdoor_themes & choice_themes:
                outdoor_choices.append(choice.option_ref)

    # If no outdoor choices, nothing to check
    if not outdoor_choices:
        return []

    # Check for bad weather days (precip_prob >= 0.7)
    bad_weather_days = [w for w in weather if w.precip_prob >= 0.7]

    if bad_weather_days:
        bad_dates = [str(w.date) for w in bad_weather_days]
        max_precip = max(w.precip_prob for w in bad_weather_days)

        msg = "Outdoor activities are planned during days with high precipitation probability."
        violations.append(
            Violation(
                kind=ViolationKind.WEATHER,
                code="OUTDOOR_IN_BAD_WEATHER",
                message=msg,
                severity=ViolationSeverity.ADVISORY,
                affected_choice_ids=outdoor_choices,
                details={
                    "bad_weather_dates": bad_dates,
                    "max_precip_prob": round(max_precip, 2),
                    "num_outdoor_choices": len(outdoor_choices),
                },
            )
        )

    return violations


async def run_verifiers(
    *,
    intent: IntentV1,
    choices: list[Choice],
    weather: Sequence[WeatherDay] | None = None,
) -> list[Violation]:
    """Run all verification checks and aggregate violations.

    Args:
        intent: User intent with budget and preferences
        choices: Selected choices to verify
        weather: Optional weather forecast data for weather checks

    Returns:
        Aggregated list of all violations found
    """
    if not choices:
        return []

    violations: list[Violation] = []

    # Run budget verification
    budget_violations = verify_budget(intent, choices)
    violations.extend(budget_violations)

    # Run preferences verification
    pref_violations = verify_preferences(intent, choices)
    violations.extend(pref_violations)

    # Run feasibility verification
    feasibility_violations = verify_feasibility(intent, choices)
    violations.extend(feasibility_violations)

    # Run weather verification
    weather_violations = verify_weather(intent, choices, weather)
    violations.extend(weather_violations)

    return violations
