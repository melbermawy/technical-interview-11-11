"""Provenance helpers for tool adapters."""

from datetime import UTC, datetime

from backend.app.models.common import Provenance


def provenance_for_fixture(source: str, ref_id: str | None = None) -> Provenance:
    """Create provenance for fixture-based tool results.

    Args:
        source: Source identifier (e.g., "fixtures.flights")
        ref_id: Optional reference ID (e.g., "nyc_paris.json")

    Returns:
        Provenance with source=tool-specific string, fetched_at=now(UTC), cache_hit=False
    """
    return Provenance(
        source=f"tool.{source}",
        ref_id=f"{source}/{ref_id}" if ref_id else source,
        source_url=f"fixtures://{source}/{ref_id}" if ref_id else f"fixtures://{source}",
        fetched_at=datetime.now(UTC),
        cache_hit=False,
    )


def provenance_for_http(source: str, url: str, cache_hit: bool = False) -> Provenance:
    """Create provenance for HTTP-based tool results.

    Args:
        source: Source identifier (e.g., "weather.open_meteo")
        url: Full URL of the HTTP request
        cache_hit: Whether result came from cache

    Returns:
        Provenance with source=tool-specific string, fetched_at=now(UTC)
    """
    return Provenance(
        source=f"tool.{source}",
        ref_id=source,
        source_url=url,
        fetched_at=datetime.now(UTC),
        cache_hit=cache_hit,
    )
