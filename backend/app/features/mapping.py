"""Canonical feature mapper: transforms tool results into ChoiceFeatures."""

from datetime import date

from backend.app.models.common import ChoiceKind
from backend.app.models.plan import Choice, ChoiceFeatures
from backend.app.models.tool_results import (
    Attraction,
    FlightOption,
    FXRate,
    Lodging,
    TransitLeg,
    WeatherDay,
)
from backend.app.tools.executor import ToolResult


class FxIndex:
    """Helper for currency conversion using FX rates."""

    def __init__(self, rates: list[FXRate], base_currency: str = "USD"):
        """Initialize FX index with rates.

        Args:
            rates: List of FX rates from tool adapters
            base_currency: Base currency for conversions (default: USD)
        """
        self.base_currency = base_currency
        self._rates: dict[tuple[str, str], float] = {}

        # Index rates by (from_currency, to_currency) pairs
        for rate in rates:
            # FXRate has: rate (float), as_of (date), provenance (Provenance)
            # We need to infer the currency pair from the provenance ref_id
            # Format: "fixtures.fx/EUR_USD" or similar
            if rate.provenance.ref_id:
                parts = rate.provenance.ref_id.split("/")
                if len(parts) == 2 and "_" in parts[1]:
                    from_curr, to_curr = parts[1].split("_", 1)
                    self._rates[(from_curr, to_curr)] = rate.rate

    def convert_to_base(self, amount_cents: int, from_currency: str) -> int:
        """Convert amount from given currency to base currency.

        Args:
            amount_cents: Amount in cents in source currency
            from_currency: Source currency code

        Returns:
            Amount in cents in base currency
        """
        if from_currency == self.base_currency:
            return amount_cents

        # Look up rate
        rate = self._rates.get((from_currency, self.base_currency))
        if rate is None:
            # Default: 1.0 if no rate found (per SPEC)
            rate = 1.0

        return int(amount_cents * rate)


def features_for_flight_option(
    flight: FlightOption,
    fx_index: FxIndex,
) -> Choice:
    """Map FlightOption to Choice with features.

    Args:
        flight: Flight option from adapter
        fx_index: FX rate index for currency conversion

    Returns:
        Choice with extracted features and provenance
    """
    # Extract cost (already in USD cents per fixture data)
    cost_usd_cents = fx_index.convert_to_base(flight.price_usd_cents, "USD")

    # Extract travel time
    travel_seconds = flight.duration_seconds

    features = ChoiceFeatures(
        cost_usd_cents=cost_usd_cents,
        travel_seconds=travel_seconds,
        indoor=None,  # Not applicable for flights
        themes=[],
    )

    return Choice(
        kind=ChoiceKind.flight,
        option_ref=flight.flight_id,
        features=features,
        score=None,  # Scoring happens in selector
        # Use element-level provenance for granular traceability
        provenance=flight.provenance,
    )


def features_for_lodging(
    lodging: Lodging,
    fx_index: FxIndex,
    num_nights: int = 1,
) -> Choice:
    """Map Lodging to Choice with features.

    Args:
        lodging: Lodging option from adapter
        fx_index: FX rate index for currency conversion
        num_nights: Number of nights to calculate total cost

    Returns:
        Choice with extracted features and provenance
    """
    # Calculate total cost for the stay
    cost_usd_cents = fx_index.convert_to_base(lodging.price_per_night_usd_cents * num_nights, "USD")

    features = ChoiceFeatures(
        cost_usd_cents=cost_usd_cents,
        travel_seconds=None,  # Not applicable for lodging
        indoor=True,  # Hotels are indoor
        themes=[lodging.tier.value] if lodging.tier else [],
    )

    return Choice(
        kind=ChoiceKind.lodging,
        option_ref=lodging.lodging_id,
        features=features,
        score=None,
        # Use element-level provenance for granular traceability
        provenance=lodging.provenance,
    )


def features_for_attraction_block(
    attraction: Attraction,
    weather_by_date: dict[date, WeatherDay] | None = None,
) -> Choice:
    """Map Attraction to Choice with features.

    Args:
        attraction: Attraction from adapter
        weather_by_date: Optional weather data indexed by date

    Returns:
        Choice with extracted features and provenance
    """
    # Extract cost
    cost_usd_cents = attraction.est_price_usd_cents or 0

    # Determine themes from venue type
    themes: list[str] = [attraction.venue_type]
    if attraction.kid_friendly:
        themes.append("kid_friendly")

    features = ChoiceFeatures(
        cost_usd_cents=cost_usd_cents,
        travel_seconds=None,  # Visit duration not in model
        indoor=attraction.indoor,
        themes=themes,
    )

    return Choice(
        kind=ChoiceKind.attraction,
        option_ref=attraction.id,
        features=features,
        score=None,
        # Use element-level provenance for granular traceability
        provenance=attraction.provenance,
    )


def features_for_transit_leg(
    transit: TransitLeg,
    fx_index: FxIndex,
) -> Choice:
    """Map TransitLeg to Choice with features.

    Args:
        transit: Transit leg from adapter
        fx_index: FX rate index for currency conversion

    Returns:
        Choice with extracted features and provenance
    """
    # Transit cost estimation (simplified - could be refined with actual pricing)
    # For now, use a simple heuristic based on mode
    mode_costs = {
        "walk": 0,
        "metro": 250,  # ~$2.50
        "bus": 200,  # ~$2.00
        "taxi": 1500,  # ~$15.00
    }
    cost_usd_cents = mode_costs.get(transit.mode.value, 0)

    features = ChoiceFeatures(
        cost_usd_cents=cost_usd_cents,
        travel_seconds=transit.duration_seconds,
        indoor=transit.mode.value in ["metro", "bus"],  # Partially indoor
        themes=[transit.mode.value],
    )

    return Choice(
        kind=ChoiceKind.transit,
        option_ref=f"{transit.mode.value}_{transit.from_geo.lat:.4f}_{transit.from_geo.lon:.4f}",
        features=features,
        score=None,
        # Use element-level provenance for granular traceability
        provenance=transit.provenance,
    )


async def build_choice_features_for_itinerary(
    *,
    flights: ToolResult[list[FlightOption]] | None = None,
    lodging: ToolResult[list[Lodging]] | None = None,
    attractions: ToolResult[list[Attraction]] | None = None,
    transit: ToolResult[list[TransitLeg]] | None = None,
    weather: ToolResult[list[WeatherDay]] | None = None,
    fx_rates: ToolResult[list[FXRate]] | None = None,
    base_currency: str = "USD",
    num_nights: int = 1,
) -> list[Choice]:
    """Build list of Choice objects with features from tool results.

    This is the main entrypoint for the canonical feature mapper.
    Given tool results, it extracts features and returns Choice objects
    ready for the selector to rank and score.

    Args:
        flights: Flight options from adapter
        lodging: Lodging options from adapter
        attractions: Attraction options from adapter
        transit: Transit leg options from adapter
        weather: Weather data by date
        fx_rates: FX rates for currency conversion
        base_currency: Base currency for cost normalization
        num_nights: Number of nights for lodging cost calculation

    Returns:
        List of Choice objects with extracted features and provenance
    """
    choices: list[Choice] = []

    # Build FX index
    fx_rate_list: list[FXRate] = []
    if fx_rates and fx_rates.value:
        # ToolResult[list[FXRate]] wraps a list of FXRate objects
        fx_rate_list = fx_rates.value
    fx_index = FxIndex(fx_rate_list, base_currency)

    # Build weather index
    weather_by_date: dict[date, WeatherDay] = {}
    if weather and weather.value:
        for wd in weather.value:
            weather_by_date[wd.date] = wd

    # Map flights
    if flights and flights.value:
        for flight in flights.value:
            choice = features_for_flight_option(flight, fx_index)
            choices.append(choice)

    # Map lodging
    if lodging and lodging.value:
        for lodge in lodging.value:
            choice = features_for_lodging(lodge, fx_index, num_nights)
            choices.append(choice)

    # Map attractions
    if attractions and attractions.value:
        for attraction in attractions.value:
            choice = features_for_attraction_block(attraction, weather_by_date)
            choices.append(choice)

    # Map transit
    if transit and transit.value:
        for leg in transit.value:
            choice = features_for_transit_leg(leg, fx_index)
            choices.append(choice)

    return choices
