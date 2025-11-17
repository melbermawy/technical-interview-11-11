"""Tests for fixture-based adapters."""

from backend.app.adapters.fixtures import (
    calculate_transit,
    fetch_attractions,
    fetch_flights,
    fetch_fx_rate,
    fetch_lodging,
)
from backend.app.models.common import Geo, Tier, TransitMode


def test_fetch_flights_returns_options() -> None:
    """Test that fetch_flights returns FlightOption objects with provenance."""
    result = fetch_flights(origin="JFK", dest="CDG")

    # Verify ToolResult structure
    assert result.value is not None
    assert result.provenance is not None
    assert result.provenance.source == "tool.fixtures.flights"
    assert result.provenance.ref_id is not None
    assert "fixtures.flights" in result.provenance.ref_id
    assert result.provenance.cache_hit is False

    # Verify flights
    flights = result.value
    assert len(flights) == 2

    # Check first flight
    flight1 = flights[0]
    assert flight1.flight_id == "AF007"
    assert flight1.origin == "JFK"
    assert flight1.dest == "CDG"
    assert flight1.price_usd_cents == 45000
    assert flight1.overnight is True
    assert flight1.provenance.source == "tool.fixtures.flights"


def test_fetch_flights_returns_empty_for_unknown_route() -> None:
    """Test that fetch_flights returns empty list for unknown routes."""
    result = fetch_flights(origin="XXX", dest="YYY")

    flights = result.value
    assert len(flights) == 0


def test_fetch_lodging_returns_options() -> None:
    """Test that fetch_lodging returns Lodging objects with provenance."""
    result = fetch_lodging(city="paris")

    # Verify ToolResult structure
    assert result.value is not None
    assert result.provenance is not None
    assert result.provenance.source == "tool.fixtures.lodging"
    assert result.provenance.ref_id is not None
    assert "fixtures.lodging" in result.provenance.ref_id

    # Verify lodging options
    lodgings = result.value
    assert len(lodgings) == 3

    # Check budget option
    budget_lodging = [lodging for lodging in lodgings if lodging.tier == Tier.budget][0]
    assert budget_lodging.lodging_id == "hotel_paris_budget_1"
    assert budget_lodging.name == "Hotel de la Paix"
    assert budget_lodging.price_per_night_usd_cents == 8500
    assert budget_lodging.kid_friendly is True
    assert budget_lodging.provenance.source == "tool.fixtures.lodging"


def test_fetch_lodging_filters_by_tier() -> None:
    """Test that fetch_lodging filters by tier preferences."""
    result = fetch_lodging(city="paris", tier_prefs=[Tier.luxury])

    lodgings = result.value
    assert len(lodgings) == 1
    assert lodgings[0].tier == Tier.luxury


def test_fetch_attractions_returns_options() -> None:
    """Test that fetch_attractions returns Attraction objects with provenance."""
    result = fetch_attractions(city="paris")

    # Verify ToolResult structure
    assert result.value is not None
    assert result.provenance is not None
    assert result.provenance.source == "tool.fixtures.attractions"

    # Verify attractions
    attractions = result.value
    assert len(attractions) == 4

    # Check Louvre
    louvre = [a for a in attractions if a.id == "louvre"][0]
    assert louvre.name == "Louvre Museum"
    assert louvre.venue_type == "museum"
    assert louvre.indoor is True
    assert louvre.kid_friendly is True
    assert louvre.est_price_usd_cents == 1700
    assert louvre.provenance.source == "tool.fixtures.attractions"

    # Check opening hours structure
    assert "1" in louvre.opening_hours  # Monday
    assert len(louvre.opening_hours["1"]) > 0


def test_fetch_attractions_filters_by_kid_friendly() -> None:
    """Test that fetch_attractions filters by kid_friendly flag."""
    result = fetch_attractions(city="paris", kid_friendly=True)

    attractions = result.value
    # All paris fixtures are kid_friendly=True
    assert len(attractions) == 4
    for attraction in attractions:
        assert attraction.kid_friendly is True


def test_calculate_transit_computes_duration() -> None:
    """Test that calculate_transit computes duration using haversine."""
    from_geo = Geo(lat=48.8566, lon=2.3522)  # Paris center
    to_geo = Geo(lat=48.8606, lon=2.3376)  # ~1.5km away

    result = calculate_transit(from_geo=from_geo, to_geo=to_geo, mode=TransitMode.metro)

    # Verify ToolResult structure
    assert result.value is not None
    assert result.provenance is not None
    assert result.provenance.source == "tool.fixtures.transit"

    # Verify transit leg
    leg = result.value
    assert leg.mode == TransitMode.metro
    assert leg.from_geo == from_geo
    assert leg.to_geo == to_geo
    assert leg.duration_seconds > 0
    assert leg.duration_seconds < 600  # Should be < 10 min for short distance
    assert leg.last_departure is not None  # Metro has last_departure
    assert leg.provenance.source == "tool.fixtures.transit"


def test_calculate_transit_walk_has_no_last_departure() -> None:
    """Test that walk mode has no last_departure."""
    from_geo = Geo(lat=48.8566, lon=2.3522)
    to_geo = Geo(lat=48.8606, lon=2.3376)

    result = calculate_transit(from_geo=from_geo, to_geo=to_geo, mode=TransitMode.walk)

    leg = result.value
    assert leg.mode == TransitMode.walk
    assert leg.last_departure is None  # Walk has no schedule


def test_fetch_fx_rate_returns_rate() -> None:
    """Test that fetch_fx_rate returns list of FXRate with provenance."""
    result = fetch_fx_rate(from_currency="EUR", to_currency="USD")

    # Verify ToolResult structure
    assert result.value is not None
    assert result.provenance is not None
    assert result.provenance.source == "tool.fixtures.fx"
    assert result.provenance.ref_id is not None
    assert "fixtures.fx" in result.provenance.ref_id

    # Verify FX rate list
    fx_rates = result.value
    assert len(fx_rates) == 1
    fx_rate = fx_rates[0]
    assert fx_rate.rate == 1.08
    assert fx_rate.as_of is not None
    assert fx_rate.provenance.source == "tool.fixtures.fx"


def test_fetch_fx_rate_defaults_for_unknown_pair() -> None:
    """Test that fetch_fx_rate returns default for unknown currency pairs."""
    result = fetch_fx_rate(from_currency="XXX", to_currency="USD")

    fx_rates = result.value
    assert len(fx_rates) == 1
    fx_rate = fx_rates[0]
    assert fx_rate.rate == 1.0  # Default rate
