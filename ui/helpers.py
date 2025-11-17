"""Helper functions for UI - SSE client and view transformations."""

import json
from collections.abc import Iterator
from typing import Any

import httpx


def get_auth_header() -> dict[str, str]:
    """Get auth header for API calls.

    For PR-4B: hardcoded dev credentials.
    TODO(PR-10): Replace with real JWT auth.
    """
    org_id = "00000000-0000-0000-0000-000000000001"
    user_id = "00000000-0000-0000-0000-000000000002"
    return {"Authorization": f"Bearer {org_id}:{user_id}"}


def create_run(
    backend_url: str, prompt: str, max_days: int = 5, budget_usd_cents: int = 250000
) -> dict[str, Any]:
    """Create a new agent run.

    Args:
        backend_url: Backend base URL (e.g. http://localhost:8000)
        prompt: Trip brief
        max_days: Maximum days (default 5)
        budget_usd_cents: Budget in cents (default $2500)

    Returns:
        Response dict with run_id and status

    Raises:
        httpx.HTTPStatusError: If request fails
    """
    response = httpx.post(
        f"{backend_url}/runs",
        json={"prompt": prompt, "max_days": max_days, "budget_usd_cents": budget_usd_cents},
        headers=get_auth_header(),
        timeout=10.0,
    )
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def stream_run_events(backend_url: str, run_id: str) -> Iterator[dict[str, Any]]:
    """Stream run events from SSE endpoint.

    Args:
        backend_url: Backend base URL
        run_id: Run ID to stream

    Yields:
        Event dicts with keys: type, data

    Example events:
        {"type": "run_event", "data": {...SSERunEvent...}}
        {"type": "heartbeat", "data": {"ts": "2025-11-17T..."}}
        {"type": "done", "data": {"status": "succeeded"}}
    """
    with httpx.stream(
        "GET",
        f"{backend_url}/runs/{run_id}/events/stream",
        headers=get_auth_header(),
        timeout=300.0,  # 5 min timeout for long runs
    ) as response:
        response.raise_for_status()

        # Parse SSE format
        event_type = "message"  # default
        for line in response.iter_lines():
            line = line.strip()

            if not line:
                # Empty line signals end of event
                continue

            if line.startswith("event:"):
                # Extract event type
                event_type = line[6:].strip()

            elif line.startswith("data:"):
                # Extract data
                data_str = line[5:].strip()
                try:
                    data = json.loads(data_str)
                    yield {"type": event_type, "data": data}
                except json.JSONDecodeError:
                    # Malformed JSON, skip
                    continue

                # Reset event type
                event_type = "message"


# View transformation functions


def build_activity_feed(events: list[dict[str, Any]]) -> list[str]:
    """Build activity feed strings from run events.

    Args:
        events: List of SSERunEvent dicts

    Returns:
        List of formatted activity strings
    """
    feed = []
    for event in events:
        node = event.get("node", "unknown")
        phase = event.get("phase", "unknown")
        summary = event.get("summary", "")

        # Format: "✓ planner: completed" or "⋯ intent: started"
        icon = "✓" if phase == "completed" else "⋯"
        feed.append(f"{icon} **{node}**: {phase} - {summary}")

    return feed


def build_itinerary_view(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build itinerary view from run events.

    Args:
        events: List of SSERunEvent dicts

    Returns:
        Dict with keys: days (list of day objects), status (str)
    """
    # For PR-4B: extract stub itinerary from planner event
    # In real implementation, this would parse plan_snapshot from backend

    itinerary: dict[str, Any] = {"days": [], "status": "pending"}

    for event in events:
        node = event.get("node")
        phase = event.get("phase")

        if node == "planner" and phase == "completed":
            # Stub: create placeholder days
            # TODO: Parse real itinerary from event payload in future PRs
            itinerary["days"] = [
                {"day": 1, "slots": [{"time": "10:00", "activity": "Stub activity 1"}]},
                {"day": 2, "slots": [{"time": "14:00", "activity": "Stub activity 2"}]},
            ]
            itinerary["status"] = "planned"

        if node == "responder" and phase == "completed":
            itinerary["status"] = "completed"

    return itinerary


def build_telemetry_view(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build telemetry/checks view from run events.

    Args:
        events: List of SSERunEvent dicts

    Returns:
        Dict with keys: nodes_completed, nodes_pending, violations, checks
    """
    all_nodes = [
        "intent",
        "planner",
        "selector",
        "tool_exec",
        "verifier",
        "repair",
        "synth",
        "responder",
    ]

    completed_nodes = []
    violations = []

    for event in events:
        node = event.get("node")
        phase = event.get("phase")

        if phase == "completed" and node not in completed_nodes:
            completed_nodes.append(node)

        if node == "verifier" and phase == "completed":
            # Extract violations from summary
            summary = event.get("summary", "")
            if "0 violations" in summary.lower():
                violations.append("✓ No violations found")
            else:
                violations.append("⚠ Violations detected")

    pending_nodes = [n for n in all_nodes if n not in completed_nodes]

    return {
        "nodes_completed": completed_nodes,
        "nodes_pending": pending_nodes,
        "violations": violations,
        "checks": f"{len(completed_nodes)}/{len(all_nodes)} nodes completed",
    }
