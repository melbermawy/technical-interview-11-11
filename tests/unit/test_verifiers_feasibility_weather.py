"""Tests for feasibility and weather verifiers (PR-7B)."""

from datetime import date, datetime

import pytest

from backend.app.models.common import ChoiceKind, Provenance
from backend.app.models.intent import DateWindow, IntentV1, Preferences
from backend.app.models.plan import Choice, ChoiceFeatures
from backend.app.models.tool_results import WeatherDay
from backend.app.models.violations import ViolationKind, ViolationSeverity
from backend.app.verification.verifiers import (
    run_verifiers,
    verify_feasibility,
    verify_weather,
)


def make_provenance(ref_id: str) -> Provenance:
    """Helper to create test provenance."""
    return Provenance(
        source="test",
        ref_id=ref_id,
        fetched_at=datetime.utcnow(),
        cache_hit=False,
    )


def make_choice(
    option_ref: str,
    kind: ChoiceKind = ChoiceKind.attraction,
    cost: int = 10000,
    travel_seconds: int | None = None,
    indoor: bool | None = None,
    themes: list[str] | None = None,
) -> Choice:
    """Helper to create test choice."""
    return Choice(
        kind=kind,
        option_ref=option_ref,
        features=ChoiceFeatures(
            cost_usd_cents=cost,
            travel_seconds=travel_seconds,
            indoor=indoor,
            themes=themes or [],
        ),
        score=None,
        provenance=make_provenance(option_ref),
    )


def make_weather(day_date: date, precip_prob: float) -> WeatherDay:
    """Helper to create test weather."""
    return WeatherDay(
        date=day_date,
        precip_prob=precip_prob,
        wind_kmh=10.0,
        temp_c_high=20.0,
        temp_c_low=10.0,
        provenance=make_provenance(f"weather-{day_date}"),
    )


@pytest.fixture
def base_intent() -> IntentV1:
    """Create a base intent for testing (4-day trip)."""
    return IntentV1(
        city="Paris",
        date_window=DateWindow(
            start=date(2025, 6, 10),
            end=date(2025, 6, 13),  # 4 days = 3 nights
            tz="Europe/Paris",
        ),
        budget_usd_cents=100000,  # $1,000
        airports=["JFK"],
        prefs=Preferences(
            kid_friendly=False,
            themes=["art"],
            avoid_overnight=False,
            locked_slots=[],
        ),
    )


# Feasibility verification tests


def test_verify_feasibility_returns_empty_when_no_issues(base_intent: IntentV1) -> None:
    """Test that verify_feasibility returns empty when everything is fine."""
    choices = [
        make_choice("flight1", kind=ChoiceKind.flight, travel_seconds=18000),  # 5 hours
        make_choice("lodging1", kind=ChoiceKind.lodging),
        make_choice("lodging2", kind=ChoiceKind.lodging),
        make_choice("lodging3", kind=ChoiceKind.lodging),  # 3 lodging for 3 nights
        make_choice("attraction1", kind=ChoiceKind.attraction),
    ]

    violations = verify_feasibility(base_intent, choices)

    assert violations == []


def test_verify_feasibility_emits_long_transit_warning(base_intent: IntentV1) -> None:
    """Test ADVISORY violation when transit exceeds 6 hours."""
    choices = [
        make_choice("transit1", kind=ChoiceKind.transit, travel_seconds=25000),  # ~7 hours
        make_choice("transit2", kind=ChoiceKind.transit, travel_seconds=30000),  # ~8 hours
        make_choice("attraction1", kind=ChoiceKind.attraction),
        # Add lodging to avoid NO_LODGING_FOR_MULTI_DAY violation
        make_choice("lodging1", kind=ChoiceKind.lodging),
        make_choice("lodging2", kind=ChoiceKind.lodging),
        make_choice("lodging3", kind=ChoiceKind.lodging),
    ]

    violations = verify_feasibility(base_intent, choices)

    assert len(violations) == 1
    violation = violations[0]

    assert violation.kind == ViolationKind.FEASIBILITY
    assert violation.code == "LONG_TRANSIT"
    assert violation.severity == ViolationSeverity.ADVISORY
    assert "6 hours" in violation.message.lower()
    assert set(violation.affected_choice_ids) == {"transit1", "transit2"}
    assert violation.details["threshold_seconds"] == 21600
    assert violation.details["num_long_segments"] == 2


def test_verify_feasibility_ignores_short_transit(base_intent: IntentV1) -> None:
    """Test that short transit segments don't trigger warnings."""
    choices = [
        make_choice("transit1", kind=ChoiceKind.transit, travel_seconds=10000),  # ~3 hours
        make_choice("transit2", kind=ChoiceKind.transit, travel_seconds=15000),  # ~4 hours
        # Add lodging to avoid NO_LODGING_FOR_MULTI_DAY violation
        make_choice("lodging1", kind=ChoiceKind.lodging),
        make_choice("lodging2", kind=ChoiceKind.lodging),
        make_choice("lodging3", kind=ChoiceKind.lodging),
    ]

    violations = verify_feasibility(base_intent, choices)

    assert violations == []


def test_verify_feasibility_warns_no_lodging_for_multi_day(base_intent: IntentV1) -> None:
    """Test ADVISORY violation when multi-day trip has no lodging."""
    choices = [
        make_choice("flight1", kind=ChoiceKind.flight),
        make_choice("attraction1", kind=ChoiceKind.attraction),
        # No lodging for 3-night trip
    ]

    violations = verify_feasibility(base_intent, choices)

    assert len(violations) == 1
    violation = violations[0]

    assert violation.kind == ViolationKind.FEASIBILITY
    assert violation.code == "NO_LODGING_FOR_MULTI_DAY"
    assert violation.severity == ViolationSeverity.ADVISORY
    assert "no lodging" in violation.message.lower()
    assert violation.affected_choice_ids == []
    assert violation.details["trip_days"] == 4
    assert violation.details["num_nights"] == 3
    assert violation.details["num_lodging"] == 0


def test_verify_feasibility_warns_too_much_lodging(base_intent: IntentV1) -> None:
    """Test ADVISORY violation when more lodging than nights."""
    choices = [
        make_choice("lodging1", kind=ChoiceKind.lodging),
        make_choice("lodging2", kind=ChoiceKind.lodging),
        make_choice("lodging3", kind=ChoiceKind.lodging),
        make_choice("lodging4", kind=ChoiceKind.lodging),
        make_choice("lodging5", kind=ChoiceKind.lodging),  # 5 lodging for 3 nights
    ]

    violations = verify_feasibility(base_intent, choices)

    assert len(violations) == 1
    violation = violations[0]

    assert violation.kind == ViolationKind.FEASIBILITY
    assert violation.code == "TOO_MUCH_LODGING"
    assert violation.severity == ViolationSeverity.ADVISORY
    assert "more lodging" in violation.message.lower()
    assert len(violation.affected_choice_ids) == 5
    assert violation.details["trip_days"] == 4
    assert violation.details["num_nights"] == 3
    assert violation.details["num_lodging"] == 5


def test_verify_feasibility_allows_single_day_trip_no_lodging() -> None:
    """Test that single-day trips don't require lodging."""
    # Single-day trip (same start and end date)
    intent = IntentV1(
        city="Paris",
        date_window=DateWindow(
            start=date(2025, 6, 10),
            end=date(2025, 6, 10),  # Same day = 0 nights
            tz="Europe/Paris",
        ),
        budget_usd_cents=50000,
        airports=["JFK"],
        prefs=Preferences(),
    )

    choices = [
        make_choice("flight1", kind=ChoiceKind.flight),
        make_choice("attraction1", kind=ChoiceKind.attraction),
        # No lodging needed
    ]

    violations = verify_feasibility(intent, choices)

    # Should not complain about missing lodging
    assert violations == []


def test_verify_feasibility_emits_multiple_violations(base_intent: IntentV1) -> None:
    """Test that multiple feasibility issues are all reported."""
    choices = [
        make_choice("transit1", kind=ChoiceKind.transit, travel_seconds=25000),  # Long transit
        # No lodging for 3-night trip
    ]

    violations = verify_feasibility(base_intent, choices)

    # Should have both LONG_TRANSIT and NO_LODGING_FOR_MULTI_DAY
    assert len(violations) == 2
    codes = {v.code for v in violations}
    assert codes == {"LONG_TRANSIT", "NO_LODGING_FOR_MULTI_DAY"}


# Weather verification tests


def test_verify_weather_returns_empty_when_no_weather_data(base_intent: IntentV1) -> None:
    """Test that verify_weather returns empty when no weather data provided."""
    choices = [
        make_choice("park1", kind=ChoiceKind.attraction, indoor=False),
    ]

    violations = verify_weather(base_intent, choices, weather=None)

    assert violations == []


def test_verify_weather_returns_empty_when_no_outdoor_choices(base_intent: IntentV1) -> None:
    """Test that verify_weather returns empty when all choices are indoor."""
    weather = [
        make_weather(date(2025, 6, 10), 0.9),  # Heavy rain
        make_weather(date(2025, 6, 11), 0.8),
    ]

    choices = [
        make_choice("museum1", kind=ChoiceKind.attraction, indoor=True),
        make_choice("theater1", kind=ChoiceKind.attraction, indoor=True),
    ]

    violations = verify_weather(base_intent, choices, weather)

    assert violations == []


def test_verify_weather_returns_empty_when_good_weather(base_intent: IntentV1) -> None:
    """Test that no violations when weather is good."""
    weather = [
        make_weather(date(2025, 6, 10), 0.2),  # Light chance
        make_weather(date(2025, 6, 11), 0.3),
    ]

    choices = [
        make_choice("park1", kind=ChoiceKind.attraction, indoor=False),
    ]

    violations = verify_weather(base_intent, choices, weather)

    assert violations == []


def test_verify_weather_warns_outdoor_in_bad_weather(base_intent: IntentV1) -> None:
    """Test ADVISORY violation when outdoor activities during heavy rain."""
    weather = [
        make_weather(date(2025, 6, 10), 0.2),  # Good
        make_weather(date(2025, 6, 11), 0.8),  # Heavy rain
        make_weather(date(2025, 6, 12), 0.9),  # Heavy rain
    ]

    choices = [
        make_choice("park1", kind=ChoiceKind.attraction, indoor=False),
        make_choice("garden1", kind=ChoiceKind.attraction, indoor=False),
    ]

    violations = verify_weather(base_intent, choices, weather)

    assert len(violations) == 1
    violation = violations[0]

    assert violation.kind == ViolationKind.WEATHER
    assert violation.code == "OUTDOOR_IN_BAD_WEATHER"
    assert violation.severity == ViolationSeverity.ADVISORY
    assert "outdoor" in violation.message.lower()
    assert "precipitation" in violation.message.lower()
    assert set(violation.affected_choice_ids) == {"park1", "garden1"}
    assert len(violation.details["bad_weather_dates"]) == 2
    assert violation.details["max_precip_prob"] == 0.9
    assert violation.details["num_outdoor_choices"] == 2


def test_verify_weather_detects_outdoor_from_themes(base_intent: IntentV1) -> None:
    """Test that outdoor detection works via themes when indoor=None."""
    weather = [
        make_weather(date(2025, 6, 10), 0.8),  # Heavy rain
    ]

    choices = [
        # indoor=None but has outdoor theme
        make_choice("venue1", kind=ChoiceKind.attraction, indoor=None, themes=["park", "nature"]),
        make_choice("venue2", kind=ChoiceKind.attraction, indoor=None, themes=["hiking"]),
        # indoor=None but no outdoor themes
        make_choice("venue3", kind=ChoiceKind.attraction, indoor=None, themes=["art", "culture"]),
    ]

    violations = verify_weather(base_intent, choices, weather)

    assert len(violations) == 1
    violation = violations[0]

    # Only venue1 and venue2 should be flagged
    assert set(violation.affected_choice_ids) == {"venue1", "venue2"}


def test_verify_weather_respects_explicit_indoor_true(base_intent: IntentV1) -> None:
    """Test that explicit indoor=True is never flagged even with outdoor themes."""
    weather = [
        make_weather(date(2025, 6, 10), 0.9),  # Heavy rain
    ]

    choices = [
        # Explicitly indoor, even with outdoor theme
        make_choice("venue1", kind=ChoiceKind.attraction, indoor=True, themes=["park"]),
    ]

    violations = verify_weather(base_intent, choices, weather)

    assert violations == []


def test_verify_weather_threshold_exactly_70_percent() -> None:
    """Test that precip_prob >= 0.7 triggers warning."""
    intent = IntentV1(
        city="Paris",
        date_window=DateWindow(
            start=date(2025, 6, 10),
            end=date(2025, 6, 10),
            tz="Europe/Paris",
        ),
        budget_usd_cents=50000,
        airports=["JFK"],
        prefs=Preferences(),
    )

    # Exactly 0.7 should trigger
    weather_at_threshold = [make_weather(date(2025, 6, 10), 0.7)]
    choices = [make_choice("park1", kind=ChoiceKind.attraction, indoor=False)]

    violations = verify_weather(intent, choices, weather_at_threshold)
    assert len(violations) == 1

    # Just below 0.7 should not trigger
    weather_below = [make_weather(date(2025, 6, 10), 0.69)]
    violations = verify_weather(intent, choices, weather_below)
    assert violations == []


# Integration tests


@pytest.mark.asyncio
async def test_run_verifiers_aggregates_all_verifiers(base_intent: IntentV1) -> None:
    """Test that run_verifiers combines all violation types."""
    weather = [
        make_weather(date(2025, 6, 10), 0.8),
        make_weather(date(2025, 6, 11), 0.9),
    ]

    choices = [
        # Over budget
        make_choice("choice1", cost=80000),
        make_choice("choice2", cost=50000),
        # Total: $1300 (over budget)
        # Missing themes (no "art")
        make_choice("choice3", themes=["food"]),
        # Long transit
        make_choice("transit1", kind=ChoiceKind.transit, travel_seconds=25000),
        # Outdoor in bad weather
        make_choice("park1", kind=ChoiceKind.attraction, indoor=False),
        # No lodging for 3-night trip
    ]

    violations = await run_verifiers(intent=base_intent, choices=choices, weather=weather)

    # Should have violations from all verifiers
    kinds = {v.kind for v in violations}
    assert ViolationKind.BUDGET in kinds
    assert ViolationKind.PREFERENCES in kinds
    assert ViolationKind.FEASIBILITY in kinds
    assert ViolationKind.WEATHER in kinds

    # Check specific codes
    codes = {v.code for v in violations}
    assert "OVER_BUDGET" in codes
    assert "PREFS_UNFULFILLED" in codes
    assert "LONG_TRANSIT" in codes
    assert "NO_LODGING_FOR_MULTI_DAY" in codes
    assert "OUTDOOR_IN_BAD_WEATHER" in codes


@pytest.mark.asyncio
async def test_run_verifiers_works_without_weather(base_intent: IntentV1) -> None:
    """Test that run_verifiers works when weather=None."""
    choices = [
        make_choice("choice1", cost=50000, themes=["art"]),
        make_choice("lodging1", kind=ChoiceKind.lodging),
        make_choice("lodging2", kind=ChoiceKind.lodging),
        make_choice("lodging3", kind=ChoiceKind.lodging),
    ]

    # Call without weather
    violations = await run_verifiers(intent=base_intent, choices=choices, weather=None)

    # Should not have weather violations
    kinds = {v.kind for v in violations}
    assert ViolationKind.WEATHER not in kinds


@pytest.mark.asyncio
async def test_graph_verifier_integration_with_weather(base_intent: IntentV1) -> None:
    """Test verifier node integration with weather in GraphState."""
    from uuid import uuid4

    from backend.app.orchestration.graph import verify_stub
    from backend.app.orchestration.state import GraphState

    weather = [
        make_weather(date(2025, 6, 10), 0.9),
    ]

    choices = [
        make_choice("park1", kind=ChoiceKind.attraction, indoor=False),
        make_choice("lodging1", kind=ChoiceKind.lodging),
        make_choice("lodging2", kind=ChoiceKind.lodging),
        make_choice("lodging3", kind=ChoiceKind.lodging),
    ]

    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=base_intent,
        choices=choices,
        weather=weather,
    )

    # Mock session
    class MockSession:
        def add(self, *args: object) -> None:
            pass

        async def execute(self, *args: object, **kwargs: object) -> None:
            pass

        async def commit(self) -> None:
            pass

        async def flush(self) -> None:
            pass

    session = MockSession()

    # Run verifier
    result_state = await verify_stub(state, session)  # type: ignore[arg-type]

    # Verify weather violation was detected
    weather_violations = [v for v in result_state.violations if v.kind == ViolationKind.WEATHER]
    assert len(weather_violations) == 1
    assert weather_violations[0].code == "OUTDOOR_IN_BAD_WEATHER"


@pytest.mark.asyncio
async def test_all_feasibility_and_weather_violations_are_advisory() -> None:
    """Test that feasibility and weather violations are never BLOCKING."""
    intent = IntentV1(
        city="Paris",
        date_window=DateWindow(
            start=date(2025, 6, 10),
            end=date(2025, 6, 14),  # 5 days
            tz="Europe/Paris",
        ),
        budget_usd_cents=100000,
        airports=["JFK"],
        prefs=Preferences(),
    )

    weather = [make_weather(date(2025, 6, 10), 1.0)]  # Worst weather

    choices = [
        # Trigger all feasibility violations
        make_choice("transit1", kind=ChoiceKind.transit, travel_seconds=30000),  # Long transit
        make_choice(
            "lodging1", kind=ChoiceKind.lodging
        ),  # Too little lodging (4 nights, 1 lodging)
        # Trigger weather violation
        make_choice("park1", kind=ChoiceKind.attraction, indoor=False),
    ]

    violations = await run_verifiers(intent=intent, choices=choices, weather=weather)

    # Find feasibility and weather violations
    feas_weather_violations = [
        v for v in violations if v.kind in [ViolationKind.FEASIBILITY, ViolationKind.WEATHER]
    ]

    # All should be ADVISORY
    assert len(feas_weather_violations) > 0
    for v in feas_weather_violations:
        assert v.severity == ViolationSeverity.ADVISORY
