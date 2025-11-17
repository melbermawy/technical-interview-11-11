"""Tool result models - external data shapes."""

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel

from backend.app.models.common import Geo, Provenance, Tier, TimeWindow, TransitMode


class FlightOption(BaseModel):
    """Flight search result."""

    flight_id: str
    origin: str
    dest: str
    departure: datetime
    arrival: datetime
    duration_seconds: int
    price_usd_cents: int
    overnight: bool
    provenance: Provenance


class Lodging(BaseModel):
    """Hotel/lodging option."""

    lodging_id: str
    name: str
    geo: Geo
    checkin_window: TimeWindow
    checkout_window: TimeWindow
    price_per_night_usd_cents: int
    tier: Tier
    kid_friendly: bool
    provenance: Provenance


class Window(BaseModel):
    """Opening hours window (tz-aware)."""

    start: datetime
    end: datetime


class Attraction(BaseModel):
    """Attraction/venue with opening hours."""

    id: str
    name: str
    venue_type: Literal["museum", "park", "temple", "other"]
    indoor: bool | None
    kid_friendly: bool | None
    opening_hours: dict[Literal["0", "1", "2", "3", "4", "5", "6"], list[Window]]
    location: Geo
    est_price_usd_cents: int | None = None
    provenance: Provenance


class WeatherDay(BaseModel):
    """Daily weather forecast."""

    date: date
    precip_prob: float
    wind_kmh: float
    temp_c_high: float
    temp_c_low: float
    provenance: Provenance


class TransitLeg(BaseModel):
    """Transit route segment."""

    mode: TransitMode
    from_geo: Geo
    to_geo: Geo
    duration_seconds: int
    last_departure: time | None = None
    provenance: Provenance


class FXRate(BaseModel):
    """Foreign exchange rate."""

    rate: float
    as_of: date
    provenance: Provenance
