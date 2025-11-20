"""Helper functions for UI - /qa/plan client + legacy event-based views."""

from typing import Any

import httpx

# All expected graph nodes in order
ALL_NODES = [
    "intent",
    "planner",
    "selector",
    "verifier",
    "retriever",
    "synth",
    "responder",
    "executor",
]


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
        "prefs": {
            "themes": themes,
            "kid_friendly": False,
            "avoid_overnight": False,
            "locked_slots": [],
        },
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


# --- Legacy event-based UI helpers (for backwards compat with tests) ---


def build_activity_feed(events: list[dict[str, Any]]) -> list[str]:
    """Build activity feed from run events.

    Args:
        events: List of event dicts with node, phase, summary

    Returns:
        List of formatted activity strings
    """
    activity = []
    for event in events:
        node = event.get("node", "unknown")
        phase = event.get("phase", "unknown")
        summary = event.get("summary", "")
        # Simple format: include node, phase, and summary in output
        activity.append(f"{node} {phase}: {summary}")
    return activity


def build_itinerary_view(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build itinerary view from run events.

    Args:
        events: List of event dicts with node, phase, summary

    Returns:
        Dict with status and days list
    """
    # Determine status based on completed events
    completed_nodes = {e["node"] for e in events if e.get("phase") == "completed"}

    if "responder" in completed_nodes:
        status = "completed"
    elif "planner" in completed_nodes:
        status = "planned"
    else:
        status = "pending"

    # If planner completed, create stub days
    days = []
    if "planner" in completed_nodes:
        # Stub creates 2 days with basic structure
        days = [
            {"day": 1, "slots": []},
            {"day": 2, "slots": []},
        ]

    return {"status": status, "days": days}


def build_telemetry_view(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build telemetry view from run events.

    Args:
        events: List of event dicts with node, phase, summary

    Returns:
        Dict with nodes_completed, nodes_pending, violations, and checks
    """
    # Find completed nodes
    completed_nodes = [e["node"] for e in events if e.get("phase") == "completed"]

    # Find pending nodes (all nodes not yet completed)
    nodes_pending = [node for node in ALL_NODES if node not in completed_nodes]

    # Extract violations from verifier events
    violations = []
    for event in events:
        if event.get("node") == "verifier" and event.get("phase") == "completed":
            summary = event.get("summary", "")
            if "0 violations" in summary.lower():
                violations.append("No violations found")
            else:
                violations.append(summary)

    # Build progress string
    checks = f"{len(completed_nodes)}/{len(ALL_NODES)} nodes completed"

    return {
        "nodes_completed": completed_nodes,
        "nodes_pending": nodes_pending,
        "violations": violations,
        "checks": checks,
    }
