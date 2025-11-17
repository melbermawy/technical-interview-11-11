"""Tests for weather adapter."""

from datetime import date

import httpx
import pytest

from backend.app.adapters.weather import fetch_weather
from backend.app.models.common import Geo


@pytest.mark.asyncio
async def test_fetch_weather_parses_open_meteo_response() -> None:
    """Test that weather adapter parses Open-Meteo API response correctly."""
    # Mock response matching Open-Meteo structure
    mock_response = {
        "daily": {
            "time": ["2025-12-01", "2025-12-02", "2025-12-03"],
            "temperature_2m_max": [15.2, 16.8, 14.5],
            "temperature_2m_min": [8.1, 9.3, 7.8],
            "precipitation_probability_max": [20, 60, 80],
            "wind_speed_10m_max": [12.5, 18.3, 22.1],
        }
    }

    # Create mock transport
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_response)

    mock_transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=mock_transport)

    # Call adapter
    location = Geo(lat=48.8566, lon=2.3522)
    result = await fetch_weather(
        location=location,
        start_date=date(2025, 12, 1),
        end_date=date(2025, 12, 3),
        client=client,
    )

    # Verify ToolResult structure
    assert result.value is not None
    assert result.provenance is not None
    assert result.provenance.source == "tool.weather.open_meteo"
    assert result.provenance.ref_id == "weather.open_meteo"
    assert result.provenance.cache_hit is False
    assert result.provenance.source_url is not None
    assert "open-meteo.com" in result.provenance.source_url

    # Verify WeatherDay objects
    weather_days = result.value
    assert len(weather_days) == 3

    # Check first day
    day1 = weather_days[0]
    assert day1.date == date(2025, 12, 1)
    assert day1.temp_c_high == 15.2
    assert day1.temp_c_low == 8.1
    assert day1.precip_prob == 0.2  # 20% -> 0.2
    assert day1.wind_kmh == 12.5
    assert day1.provenance.source == "tool.weather.open_meteo"

    # Check second day
    day2 = weather_days[1]
    assert day2.date == date(2025, 12, 2)
    assert day2.precip_prob == 0.6  # 60% -> 0.6

    # Check third day
    day3 = weather_days[2]
    assert day3.date == date(2025, 12, 3)
    assert day3.precip_prob == 0.8  # 80% -> 0.8

    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_weather_handles_null_values() -> None:
    """Test that weather adapter handles null values in API response."""
    # Mock response with null values
    mock_response = {
        "daily": {
            "time": ["2025-12-01"],
            "temperature_2m_max": [None],
            "temperature_2m_min": [None],
            "precipitation_probability_max": [None],
            "wind_speed_10m_max": [None],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_response)

    mock_transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=mock_transport)

    location = Geo(lat=48.8566, lon=2.3522)
    result = await fetch_weather(
        location=location,
        start_date=date(2025, 12, 1),
        end_date=date(2025, 12, 1),
        client=client,
    )

    # Verify defaults are used for null values
    weather_days = result.value
    assert len(weather_days) == 1

    day = weather_days[0]
    assert day.temp_c_high == 20.0  # Default
    assert day.temp_c_low == 10.0  # Default
    assert day.precip_prob == 0.0  # Default
    assert day.wind_kmh == 0.0  # Default

    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_weather_constructs_correct_url() -> None:
    """Test that weather adapter constructs correct Open-Meteo API URL."""
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            200,
            json={
                "daily": {
                    "time": ["2025-12-01"],
                    "temperature_2m_max": [15.0],
                    "temperature_2m_min": [8.0],
                    "precipitation_probability_max": [20],
                    "wind_speed_10m_max": [12.0],
                }
            },
        )

    mock_transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=mock_transport)

    location = Geo(lat=48.8566, lon=2.3522)
    await fetch_weather(
        location=location,
        start_date=date(2025, 12, 1),
        end_date=date(2025, 12, 1),
        base_url="https://api.open-meteo.com/v1/forecast",
        client=client,
    )

    # Verify request parameters
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert str(req.url).startswith("https://api.open-meteo.com/v1/forecast")

    # Check query params
    params = dict(req.url.params)
    assert params["latitude"] == "48.8566"
    assert params["longitude"] == "2.3522"
    assert params["start_date"] == "2025-12-01"
    assert params["end_date"] == "2025-12-01"
    assert "temperature_2m_max" in params["daily"]
    assert "precipitation_probability_max" in params["daily"]
    assert params["timezone"] == "UTC"

    await client.aclose()
