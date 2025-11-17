"""Weather adapter using Open-Meteo API (keyless, free tier)."""

from datetime import date

import httpx

from backend.app.adapters.provenance import provenance_for_http
from backend.app.models.common import Geo
from backend.app.models.tool_results import WeatherDay
from backend.app.tools.executor import ToolResult


async def fetch_weather(
    location: Geo,
    start_date: date,
    end_date: date,
    base_url: str = "https://api.open-meteo.com/v1/forecast",
    client: httpx.AsyncClient | None = None,
) -> ToolResult[list[WeatherDay]]:
    """Fetch weather forecast from Open-Meteo API.

    Args:
        location: Geographic coordinates
        start_date: First date to fetch
        end_date: Last date to fetch (inclusive)
        base_url: Open-Meteo API base URL
        client: Optional httpx client (for testing with mocks)

    Returns:
        ToolResult wrapping list of WeatherDay objects with provenance

    Raises:
        httpx.HTTPError: On network or HTTP errors
    """
    # Build query params for Open-Meteo API
    # Docs: https://open-meteo.com/en/docs
    params: dict[str, str | float] = {
        "latitude": location.lat,
        "longitude": location.lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": (
            "temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,wind_speed_10m_max"
        ),
        "timezone": "UTC",
    }

    # Build full URL for provenance
    url = f"{base_url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"

    # Make HTTP request
    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=4.0)
        close_client = True

    try:
        response = await client.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()

        # Parse Open-Meteo response
        # Response structure: {daily: {time: [...], temperature_2m_max: [...], ...}}
        daily = data["daily"]
        dates = [date.fromisoformat(d) for d in daily["time"]]
        temp_max = daily["temperature_2m_max"]
        temp_min = daily["temperature_2m_min"]
        precip_prob = daily["precipitation_probability_max"]
        wind_speed = daily["wind_speed_10m_max"]

        # Build WeatherDay objects
        weather_days = []
        for i, d in enumerate(dates):
            # Open-Meteo precipitation_probability is 0-100, we want 0.0-1.0
            precip = precip_prob[i] / 100.0 if precip_prob[i] is not None else 0.0

            weather_day = WeatherDay(
                date=d,
                precip_prob=precip,
                wind_kmh=wind_speed[i] if wind_speed[i] is not None else 0.0,
                temp_c_high=temp_max[i] if temp_max[i] is not None else 20.0,
                temp_c_low=temp_min[i] if temp_min[i] is not None else 10.0,
                provenance=provenance_for_http(
                    source="weather.open_meteo",
                    url=url,
                    cache_hit=False,
                ),
            )
            weather_days.append(weather_day)

        # Wrap in ToolResult
        return ToolResult(
            value=weather_days,
            provenance=provenance_for_http(
                source="weather.open_meteo",
                url=url,
                cache_hit=False,
            ),
        )
    finally:
        if close_client:
            await client.aclose()
