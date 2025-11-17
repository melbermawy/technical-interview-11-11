"""Fixture-based adapters for flights, lodging, attractions, transit, and FX."""

import json
import math
from datetime import date, datetime, time
from pathlib import Path
from typing import Literal

from backend.app.adapters.provenance import provenance_for_fixture
from backend.app.models.common import Geo, Tier, TimeWindow, TransitMode
from backend.app.models.tool_results import (
    Attraction,
    FlightOption,
    FXRate,
    Lodging,
    TransitLeg,
    Window,
)
from backend.app.tools.executor import ToolResult

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def fetch_flights(
    origin: str,
    dest: str,
) -> ToolResult[list[FlightOption]]:
    """Fetch flight options from fixtures.

    Args:
        origin: Origin IATA code
        dest: Destination IATA code

    Returns:
        ToolResult wrapping list of FlightOption objects with provenance
    """
    # Load fixtures
    fixtures_path = FIXTURES_DIR / "flights.json"
    with open(fixtures_path) as f:
        data = json.load(f)

    # Look up route
    route_key = f"{origin}_{dest}"
    flights_data = data.get(route_key, [])

    # Build FlightOption objects
    flights = []
    for flight_data in flights_data:
        flight = FlightOption(
            flight_id=flight_data["flight_id"],
            origin=flight_data["origin"],
            dest=flight_data["dest"],
            departure=datetime.fromisoformat(flight_data["departure"]),
            arrival=datetime.fromisoformat(flight_data["arrival"]),
            duration_seconds=flight_data["duration_seconds"],
            price_usd_cents=flight_data["price_usd_cents"],
            overnight=flight_data["overnight"],
            provenance=provenance_for_fixture("fixtures.flights", route_key),
        )
        flights.append(flight)

    return ToolResult(
        value=flights,
        provenance=provenance_for_fixture("fixtures.flights", route_key),
    )


def fetch_lodging(
    city: str,
    tier_prefs: list[Tier] | None = None,
) -> ToolResult[list[Lodging]]:
    """Fetch lodging options from fixtures.

    Args:
        city: City name (lowercase)
        tier_prefs: Optional list of preferred tiers to filter by

    Returns:
        ToolResult wrapping list of Lodging objects with provenance
    """
    # Load fixtures
    fixtures_path = FIXTURES_DIR / "lodging.json"
    with open(fixtures_path) as f:
        data = json.load(f)

    # Look up city
    city_lower = city.lower()
    lodging_data = data.get(city_lower, [])

    # Filter by tier if specified
    if tier_prefs:
        tier_strs = [t.value if isinstance(t, Tier) else t for t in tier_prefs]
        lodging_data = [ld for ld in lodging_data if ld["tier"] in tier_strs]

    # Build Lodging objects
    lodgings = []
    for ld in lodging_data:
        lodging = Lodging(
            lodging_id=ld["lodging_id"],
            name=ld["name"],
            geo=Geo(**ld["geo"]),
            checkin_window=TimeWindow(
                start=time.fromisoformat(ld["checkin_window"]["start"]),
                end=time.fromisoformat(ld["checkin_window"]["end"]),
            ),
            checkout_window=TimeWindow(
                start=time.fromisoformat(ld["checkout_window"]["start"]),
                end=time.fromisoformat(ld["checkout_window"]["end"]),
            ),
            price_per_night_usd_cents=ld["price_per_night_usd_cents"],
            tier=Tier(ld["tier"]),
            kid_friendly=ld["kid_friendly"],
            provenance=provenance_for_fixture("fixtures.lodging", city_lower),
        )
        lodgings.append(lodging)

    return ToolResult(
        value=lodgings,
        provenance=provenance_for_fixture("fixtures.lodging", city_lower),
    )


def fetch_attractions(
    city: str,
    kid_friendly: bool | None = None,
) -> ToolResult[list[Attraction]]:
    """Fetch attractions from fixtures.

    Args:
        city: City name (lowercase)
        kid_friendly: Optional filter for kid-friendly venues

    Returns:
        ToolResult wrapping list of Attraction objects with provenance
    """
    # Load fixtures
    fixtures_path = FIXTURES_DIR / "attractions.json"
    with open(fixtures_path) as f:
        data = json.load(f)

    # Look up city
    city_lower = city.lower()
    attractions_data = data.get(city_lower, [])

    # Filter by kid_friendly if specified
    if kid_friendly is not None:
        attractions_data = [ad for ad in attractions_data if ad.get("kid_friendly") == kid_friendly]

    # Build Attraction objects
    attractions = []
    for ad in attractions_data:
        # Parse opening hours
        opening_hours: dict[Literal["0", "1", "2", "3", "4", "5", "6"], list[Window]] = {}
        for day_str, windows_data in ad["opening_hours"].items():
            windows = [
                Window(
                    start=datetime.fromisoformat(w["start"]),
                    end=datetime.fromisoformat(w["end"]),
                )
                for w in windows_data
            ]
            opening_hours[day_str] = windows

        attraction = Attraction(
            id=ad["id"],
            name=ad["name"],
            venue_type=ad["venue_type"],
            indoor=ad.get("indoor"),
            kid_friendly=ad.get("kid_friendly"),
            opening_hours=opening_hours,
            location=Geo(**ad["location"]),
            est_price_usd_cents=ad.get("est_price_usd_cents"),
            provenance=provenance_for_fixture("fixtures.attractions", city_lower),
        )
        attractions.append(attraction)

    return ToolResult(
        value=attractions,
        provenance=provenance_for_fixture("fixtures.attractions", city_lower),
    )


def calculate_transit(
    from_geo: Geo,
    to_geo: Geo,
    mode: TransitMode = TransitMode.metro,
) -> ToolResult[TransitLeg]:
    """Calculate transit leg using haversine distance and mode-specific speeds.

    Args:
        from_geo: Origin coordinates
        to_geo: Destination coordinates
        mode: Transit mode (default: metro)

    Returns:
        ToolResult wrapping TransitLeg with provenance
    """
    # Haversine distance calculation
    lat1, lon1 = math.radians(from_geo.lat), math.radians(from_geo.lon)
    lat2, lon2 = math.radians(to_geo.lat), math.radians(to_geo.lon)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    distance_km = 6371 * c

    # Mode speeds (km/h)
    speeds = {
        TransitMode.walk: 5.0,
        TransitMode.metro: 30.0,
        TransitMode.bus: 20.0,
        TransitMode.taxi: 25.0,
    }

    speed_kmh = speeds.get(mode, 20.0)
    duration_hours = distance_km / speed_kmh
    duration_seconds = int(duration_hours * 3600)

    # Public transit has last_departure
    last_departure = time(23, 30) if mode in [TransitMode.metro, TransitMode.bus] else None

    transit_leg = TransitLeg(
        mode=mode,
        from_geo=from_geo,
        to_geo=to_geo,
        duration_seconds=duration_seconds,
        last_departure=last_departure,
        provenance=provenance_for_fixture(
            "fixtures.transit",
            f"{mode.value}_{from_geo.lat:.4f}_{from_geo.lon:.4f}",
        ),
    )

    return ToolResult(
        value=transit_leg,
        provenance=provenance_for_fixture(
            "fixtures.transit",
            f"{mode.value}_{from_geo.lat:.4f}_{from_geo.lon:.4f}",
        ),
    )


def fetch_fx_rate(
    from_currency: str,
    to_currency: str = "USD",
) -> ToolResult[list[FXRate]]:
    """Fetch FX rates from fixtures.

    Args:
        from_currency: Source currency code (e.g., "EUR")
        to_currency: Target currency code (default: "USD")

    Returns:
        ToolResult wrapping list of FXRate objects with provenance
    """
    # Load fixtures
    fixtures_path = FIXTURES_DIR / "fx_rates.json"
    with open(fixtures_path) as f:
        data = json.load(f)

    # Look up specific rate
    rate_key = f"{from_currency}_{to_currency}"
    rate_data = data.get(rate_key)

    if not rate_data:
        # Default to 1.0 if not found
        rate_data = {"rate": 1.0, "as_of": date.today().isoformat()}

    fx_rate = FXRate(
        rate=rate_data["rate"],
        as_of=date.fromisoformat(rate_data["as_of"]),
        provenance=provenance_for_fixture("fixtures.fx", rate_key),
    )

    # Return as list for consistency with other adapters
    return ToolResult(
        value=[fx_rate],
        provenance=provenance_for_fixture("fixtures.fx", rate_key),
    )
