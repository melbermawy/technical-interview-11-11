"""Real planner node implementation for PR-6A."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.adapters.fixtures import (
    calculate_transit,
    fetch_attractions,
    fetch_flights,
    fetch_fx_rate,
    fetch_lodging,
)
from backend.app.adapters.weather import fetch_weather
from backend.app.config import get_settings
from backend.app.db.run_events import append_run_event
from backend.app.features.mapping import build_choice_features_for_itinerary
from backend.app.models.common import ChoiceKind, Geo, TransitMode
from backend.app.models.plan import Choice
from backend.app.orchestration.state import GraphState


def apply_fanout_cap(choices: list[Choice], cap: int) -> list[Choice]:
    """Apply deterministic fan-out cap to choices.

    Fan-out policy:
    1. Group by ChoiceKind in priority order: flight, lodging, attraction, transit
    2. Within each group, sort by stable key:
       - Flights: (cost, travel_time, option_ref)
       - Lodging: (cost, option_ref)
       - Attractions: (cost, option_ref)
       - Transit: (travel_time, option_ref)
    3. Take items in priority order until cap is reached

    Args:
        choices: List of Choice objects to cap
        cap: Maximum number of choices to return

    Returns:
        Capped list of choices (deterministic ordering)
    """
    if len(choices) <= cap:
        return choices

    # Group by kind
    by_kind: dict[ChoiceKind, list[Choice]] = {
        ChoiceKind.flight: [],
        ChoiceKind.lodging: [],
        ChoiceKind.attraction: [],
        ChoiceKind.transit: [],
    }

    for choice in choices:
        if choice.kind in by_kind:
            by_kind[choice.kind].append(choice)

    # Sort each group by stable key
    def flight_key(c: Choice) -> tuple[int, int, str]:
        return (
            c.features.cost_usd_cents,
            c.features.travel_seconds or 0,
            c.option_ref,
        )

    def lodging_key(c: Choice) -> tuple[int, str]:
        return (c.features.cost_usd_cents, c.option_ref)

    def attraction_key(c: Choice) -> tuple[int, str]:
        return (c.features.cost_usd_cents, c.option_ref)

    def transit_key(c: Choice) -> tuple[int, str]:
        return (c.features.travel_seconds or 0, c.option_ref)

    by_kind[ChoiceKind.flight].sort(key=flight_key)
    by_kind[ChoiceKind.lodging].sort(key=lodging_key)
    by_kind[ChoiceKind.attraction].sort(key=attraction_key)
    by_kind[ChoiceKind.transit].sort(key=transit_key)

    # Take items in priority order until cap
    result: list[Choice] = []
    for kind in [
        ChoiceKind.flight,
        ChoiceKind.lodging,
        ChoiceKind.attraction,
        ChoiceKind.transit,
    ]:
        for choice in by_kind[kind]:
            if len(result) >= cap:
                return result
            result.append(choice)

    return result


async def plan_real(
    state: GraphState, session: AsyncSession, http_client: httpx.AsyncClient | None = None
) -> GraphState:
    """Real planner - calls adapters and builds choices with fan-out cap.

    Args:
        state: Current graph state with IntentV1
        session: Database session for event persistence
        http_client: Optional HTTP client for weather adapter (injected for testing)

    Returns:
        Updated graph state with choices populated
    """
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="planner",
        phase="started",
        summary="Calling adapters to gather travel options",
    )

    if not state.intent:
        raise ValueError("Cannot plan without intent")

    intent = state.intent
    settings = get_settings()

    # Calculate num_nights from date window
    num_nights = (intent.date_window.end - intent.date_window.start).days

    # Call adapters to get tool results
    # For flights, use first airport as origin (simplified for PR-6A)
    origin = intent.airports[0] if intent.airports else "JFK"
    # Assume destination based on city (simplified mapping)
    city_to_airport = {
        "paris": "CDG",
        "tokyo": "NRT",
        "new_york": "JFK",
    }
    dest = city_to_airport.get(intent.city.lower(), "CDG")

    # Fetch all tool results
    flights = fetch_flights(origin=origin, dest=dest)
    lodging = fetch_lodging(city=intent.city.lower(), tier_prefs=None)
    kid_friendly_filter = intent.prefs.kid_friendly if intent.prefs.kid_friendly else None
    attractions = fetch_attractions(city=intent.city.lower(), kid_friendly=kid_friendly_filter)
    fx_rates = fetch_fx_rate(from_currency="EUR", to_currency="USD")

    # Fetch weather (async)
    # Use a simple location for the city (Paris coords as example)
    city_coords = {
        "paris": Geo(lat=48.8566, lon=2.3522),
        "tokyo": Geo(lat=35.6762, lon=139.6503),
        "new_york": Geo(lat=40.7128, lon=-74.0060),
    }
    location = city_coords.get(intent.city.lower(), Geo(lat=48.8566, lon=2.3522))

    # Create http_client if not provided
    close_client = False
    if http_client is None:
        http_client = httpx.AsyncClient()
        close_client = True

    try:
        weather = await fetch_weather(
            location=location,
            start_date=intent.date_window.start,
            end_date=intent.date_window.end,
            client=http_client,
        )
    finally:
        if close_client:
            await http_client.aclose()

    # Optional: fetch transit (for now, just create one sample transit leg)
    # This is a placeholder - real implementation would generate based on attractions
    transit_leg = calculate_transit(
        from_geo=location,
        to_geo=Geo(lat=location.lat + 0.01, lon=location.lon + 0.01),
        mode=TransitMode.metro,
    )
    # Wrap single transit leg in a list-based ToolResult
    from backend.app.tools.executor import ToolResult

    transit = ToolResult(
        value=[transit_leg.value],
        provenance=transit_leg.provenance,
    )

    # Build choices using feature mapper
    all_choices = await build_choice_features_for_itinerary(
        flights=flights,
        lodging=lodging,
        attractions=attractions,
        transit=transit,
        weather=weather,
        fx_rates=fx_rates,
        base_currency="USD",
        num_nights=num_nights,
    )

    # Apply fan-out cap
    capped_choices = apply_fanout_cap(all_choices, settings.fanout_cap)

    # Store in state
    state.choices = capped_choices

    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="planner",
        phase="completed",
        summary=f"Generated {len(capped_choices)} choice options (capped from {len(all_choices)})",
    )

    return state
