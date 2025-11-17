"""Tests for canonical feature mapper."""

from datetime import datetime

import pytest

from backend.app.adapters.fixtures import (
    fetch_attractions,
    fetch_flights,
    fetch_fx_rate,
    fetch_lodging,
)
from backend.app.features.mapping import (
    FxIndex,
    build_choice_features_for_itinerary,
    features_for_attraction_block,
    features_for_flight_option,
    features_for_lodging,
    features_for_transit_leg,
)
from backend.app.models.common import ChoiceKind, Geo, TransitMode
from backend.app.models.tool_results import Provenance, TransitLeg


def test_fx_index_converts_to_base_currency() -> None:
    """Test that FxIndex converts amounts to base currency."""
    # Use real fixture data
    fx_result = fetch_fx_rate(from_currency="EUR", to_currency="USD")
    fx_rates = fx_result.value

    fx_index = FxIndex(fx_rates, base_currency="USD")

    # Convert 100 EUR cents to USD
    result = fx_index.convert_to_base(10000, "EUR")
    assert result == 10800  # 100 EUR * 1.08 = 108 USD

    # Convert USD to USD (should be no-op)
    result = fx_index.convert_to_base(10000, "USD")
    assert result == 10000


def test_fx_index_defaults_for_unknown_currency() -> None:
    """Test that FxIndex defaults to 1.0 rate for unknown currency pairs."""
    fx_index = FxIndex([], base_currency="USD")

    # Unknown currency should use default rate of 1.0
    result = fx_index.convert_to_base(10000, "XXX")
    assert result == 10000


def test_features_for_flight_option_extracts_features() -> None:
    """Test that features_for_flight_option extracts cost and duration."""
    # Use real fixture data
    flight_result = fetch_flights(origin="JFK", dest="CDG")
    flight = flight_result.value[0]  # Get first flight

    fx_index = FxIndex([], base_currency="USD")
    choice = features_for_flight_option(flight, fx_index)

    # Verify Choice structure
    assert choice.kind == ChoiceKind.flight
    assert choice.option_ref == flight.flight_id
    assert choice.score is None  # Scoring happens in selector
    assert choice.provenance == flight.provenance

    # Verify features
    assert choice.features.cost_usd_cents == flight.price_usd_cents
    assert choice.features.travel_seconds == flight.duration_seconds
    assert choice.features.indoor is None  # Not applicable for flights
    assert choice.features.themes == []


def test_features_for_lodging_calculates_total_cost() -> None:
    """Test that features_for_lodging calculates total cost for multiple nights."""
    # Use real fixture data
    lodging_result = fetch_lodging(city="paris")
    budget_lodging = [
        lodge for lodge in lodging_result.value if lodge.lodging_id == "hotel_paris_budget_1"
    ][0]

    fx_index = FxIndex([], base_currency="USD")
    choice = features_for_lodging(budget_lodging, fx_index, num_nights=3)

    # Verify Choice structure
    assert choice.kind == ChoiceKind.lodging
    assert choice.option_ref == "hotel_paris_budget_1"
    assert choice.provenance == budget_lodging.provenance

    # Verify features
    assert choice.features.cost_usd_cents == 25500  # 8500 * 3 nights
    assert choice.features.travel_seconds is None  # Not applicable
    assert choice.features.indoor is True  # Hotels are indoor
    assert choice.features.themes == ["budget"]  # Tier as theme


def test_features_for_attraction_extracts_themes() -> None:
    """Test that features_for_attraction extracts venue type and kid_friendly as themes."""
    # Use real fixture data
    attraction_result = fetch_attractions(city="paris")
    louvre = [a for a in attraction_result.value if a.id == "louvre"][0]

    choice = features_for_attraction_block(louvre)

    # Verify Choice structure
    assert choice.kind == ChoiceKind.attraction
    assert choice.option_ref == "louvre"
    assert choice.provenance == louvre.provenance

    # Verify features
    assert choice.features.cost_usd_cents == 1700
    assert choice.features.indoor is True
    assert "museum" in choice.features.themes
    assert "kid_friendly" in choice.features.themes


def test_features_for_transit_leg_uses_mode_heuristic() -> None:
    """Test that features_for_transit_leg uses mode-based cost heuristic."""
    prov = Provenance(
        source="tool.fixtures.transit",
        ref_id="fixtures.transit/metro",
        fetched_at=datetime.utcnow(),
        cache_hit=False,
    )
    transit = TransitLeg(
        mode=TransitMode.metro,
        from_geo=Geo(lat=48.8566, lon=2.3522),
        to_geo=Geo(lat=48.8606, lon=2.3376),
        duration_seconds=600,
        last_departure=None,
        provenance=prov,
    )

    fx_index = FxIndex([], base_currency="USD")
    choice = features_for_transit_leg(transit, fx_index)

    # Verify Choice structure
    assert choice.kind == ChoiceKind.transit
    assert choice.provenance == prov

    # Verify features
    assert choice.features.cost_usd_cents == 250  # Metro heuristic
    assert choice.features.travel_seconds == 600
    assert choice.features.indoor is True  # Metro is indoor
    assert "metro" in choice.features.themes


def test_features_for_transit_walk_has_zero_cost() -> None:
    """Test that walking has zero cost."""
    prov = Provenance(
        source="tool.fixtures.transit",
        ref_id="fixtures.transit/walk",
        fetched_at=datetime.utcnow(),
        cache_hit=False,
    )
    transit = TransitLeg(
        mode=TransitMode.walk,
        from_geo=Geo(lat=48.8566, lon=2.3522),
        to_geo=Geo(lat=48.8606, lon=2.3376),
        duration_seconds=1200,
        last_departure=None,
        provenance=prov,
    )

    fx_index = FxIndex([], base_currency="USD")
    choice = features_for_transit_leg(transit, fx_index)

    # Verify walk has zero cost
    assert choice.features.cost_usd_cents == 0
    assert choice.features.indoor is False  # Walk is outdoor


@pytest.mark.asyncio
async def test_build_choice_features_for_itinerary_handles_none_inputs() -> None:
    """Test that main entrypoint handles None inputs gracefully."""
    # Call with no inputs
    choices = await build_choice_features_for_itinerary()

    # Should return empty list
    assert choices == []


@pytest.mark.asyncio
async def test_build_choice_features_for_itinerary_maps_flights() -> None:
    """Test that main entrypoint maps flight options correctly."""
    # Get real fixture data
    flight_result = fetch_flights(origin="JFK", dest="CDG")

    # Build choices
    choices = await build_choice_features_for_itinerary(flights=flight_result)

    # Verify we got choices for all flights
    assert len(choices) == 2
    assert all(c.kind == ChoiceKind.flight for c in choices)
    assert all(c.features.cost_usd_cents > 0 for c in choices)
    assert all(c.features.travel_seconds and c.features.travel_seconds > 0 for c in choices)
    assert all(c.provenance.source == "tool.fixtures.flights" for c in choices)


@pytest.mark.asyncio
async def test_build_choice_features_for_itinerary_maps_lodging() -> None:
    """Test that main entrypoint maps lodging options correctly."""
    # Get real fixture data
    lodging_result = fetch_lodging(city="paris")

    # Build choices for 3 nights
    choices = await build_choice_features_for_itinerary(lodging=lodging_result, num_nights=3)

    # Verify we got choices for all lodging options
    assert len(choices) == 3
    assert all(c.kind == ChoiceKind.lodging for c in choices)
    assert all(c.features.indoor is True for c in choices)
    assert all(c.features.cost_usd_cents > 0 for c in choices)
    # Budget hotel: 8500 * 3 = 25500
    budget_choice = [c for c in choices if "budget" in c.features.themes][0]
    assert budget_choice.features.cost_usd_cents == 25500


@pytest.mark.asyncio
async def test_build_choice_features_for_itinerary_maps_attractions() -> None:
    """Test that main entrypoint maps attraction options correctly."""
    # Get real fixture data
    attraction_result = fetch_attractions(city="paris")

    # Build choices
    choices = await build_choice_features_for_itinerary(attractions=attraction_result)

    # Verify we got choices for all attractions
    assert len(choices) == 4
    assert all(c.kind == ChoiceKind.attraction for c in choices)
    assert all(c.provenance.source == "tool.fixtures.attractions" for c in choices)

    # Check Louvre specifically
    louvre = [c for c in choices if c.option_ref == "louvre"][0]
    assert louvre.features.cost_usd_cents == 1700
    assert louvre.features.indoor is True
    assert "museum" in louvre.features.themes


@pytest.mark.asyncio
async def test_build_choice_features_for_itinerary_uses_fx_rates() -> None:
    """Test that main entrypoint uses FX rates for currency conversion."""
    # Get FX rate
    fx_result = fetch_fx_rate(from_currency="EUR", to_currency="USD")

    # Get lodging
    lodging_result = fetch_lodging(city="paris")

    # Build choices with FX rates
    choices = await build_choice_features_for_itinerary(
        lodging=lodging_result, fx_rates=fx_result, num_nights=1
    )

    # Verify FX index was built and used (though our fixtures use USD already)
    assert len(choices) == 3
    assert all(c.features.cost_usd_cents > 0 for c in choices)


@pytest.mark.asyncio
async def test_build_choice_features_for_itinerary_combines_multiple_types() -> None:
    """Test that main entrypoint combines multiple tool result types."""
    # Get fixture data for multiple types
    flight_result = fetch_flights(origin="JFK", dest="CDG")
    lodging_result = fetch_lodging(city="paris")
    attraction_result = fetch_attractions(city="paris")

    # Build choices
    choices = await build_choice_features_for_itinerary(
        flights=flight_result,
        lodging=lodging_result,
        attractions=attraction_result,
        num_nights=2,
    )

    # Verify we got all choices combined
    # 2 flights + 3 lodging + 4 attractions = 9 total
    assert len(choices) == 9

    # Verify each type is present
    flight_choices = [c for c in choices if c.kind == ChoiceKind.flight]
    lodging_choices = [c for c in choices if c.kind == ChoiceKind.lodging]
    attraction_choices = [c for c in choices if c.kind == ChoiceKind.attraction]

    assert len(flight_choices) == 2
    assert len(lodging_choices) == 3
    assert len(attraction_choices) == 4

    # Verify provenance is preserved for each type
    assert all(c.provenance.source == "tool.fixtures.flights" for c in flight_choices)
    assert all(c.provenance.source == "tool.fixtures.lodging" for c in lodging_choices)
    assert all(c.provenance.source == "tool.fixtures.attractions" for c in attraction_choices)


def test_flight_choice_uses_element_level_provenance() -> None:
    """Test that Choice provenance comes from element (flight), not outer ToolResult."""
    # Get real fixture data
    flight_result = fetch_flights(origin="JFK", dest="CDG")
    flight = flight_result.value[0]

    # Create Choice via mapper
    fx_index = FxIndex([], base_currency="USD")
    choice = features_for_flight_option(flight, fx_index)

    # Verify Choice uses element-level provenance
    assert choice.provenance == flight.provenance
    assert choice.provenance.source == "tool.fixtures.flights"
    assert choice.provenance.ref_id == flight.provenance.ref_id
    # Element provenance should match the flight's specific provenance, not just generic tool result


def test_lodging_choice_uses_element_level_provenance() -> None:
    """Test that Choice provenance comes from element (lodging), not outer ToolResult."""
    # Get real fixture data
    lodging_result = fetch_lodging(city="paris")
    budget_lodging = [
        lodge for lodge in lodging_result.value if lodge.lodging_id == "hotel_paris_budget_1"
    ][0]

    # Create Choice via mapper
    fx_index = FxIndex([], base_currency="USD")
    choice = features_for_lodging(budget_lodging, fx_index, num_nights=2)

    # Verify Choice uses element-level provenance
    assert choice.provenance == budget_lodging.provenance
    assert choice.provenance.source == "tool.fixtures.lodging"
    assert choice.provenance.ref_id == budget_lodging.provenance.ref_id
    # This ensures "no evidence, no claim" - Choice traces to specific option
