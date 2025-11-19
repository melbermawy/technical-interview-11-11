"""Helper functions for UI - /qa/plan client."""

from typing import Any

import httpx


def get_auth_header() -> dict[str, str]:
    """Get auth header for API calls.

    For PR-12: hardcoded dev credentials.
    TODO(future): Replace with real JWT auth.
    """
    org_id = "00000000-0000-0000-0000-000000000001"
    user_id = "00000000-0000-0000-0000-000000000002"
    return {"Authorization": f"Bearer {org_id}:{user_id}"}


def call_qa_plan(
    backend_url: str,
    city: str,
    start_date: str,
    end_date: str,
    budget_usd_cents: int,
    airports: list[str],
    themes: list[str],
    timezone: str = "UTC",
) -> dict[str, Any]:
    """Call /qa/plan endpoint with user intent.

    Args:
        backend_url: Backend base URL (e.g. http://localhost:8000)
        city: Destination city
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        budget_usd_cents: Budget in cents
        airports: List of airport codes
        themes: List of preference themes
        timezone: Timezone string (default UTC)

    Returns:
        QAPlanResponse dict

    Raises:
        httpx.HTTPStatusError: If request fails
    """
    intent = {
        "city": city,
        "date_window": {"start": start_date, "end": end_date, "tz": timezone},
        "budget_usd_cents": budget_usd_cents,
        "airports": airports,
        "prefs": {"themes": themes, "kid_friendly": False, "avoid_overnight": False, "locked_slots": []},
    }

    response = httpx.post(
        f"{backend_url}/qa/plan",
        json=intent,
        headers=get_auth_header(),
        timeout=60.0,  # Allow up to 60s for planning
    )
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result
