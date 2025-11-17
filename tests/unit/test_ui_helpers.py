"""Unit tests for UI helper functions - PR-4B."""

from ui.helpers import build_activity_feed, build_itinerary_view, build_telemetry_view


def test_build_activity_feed_empty() -> None:
    """Test activity feed with no events."""
    result = build_activity_feed([])
    assert result == []


def test_build_activity_feed_with_events() -> None:
    """Test activity feed with sample events."""
    events = [
        {"node": "intent", "phase": "started", "summary": "Extracting intent"},
        {"node": "intent", "phase": "completed", "summary": "Intent extracted"},
        {"node": "planner", "phase": "started", "summary": "Planning trip"},
    ]

    result = build_activity_feed(events)

    assert len(result) == 3
    assert "intent" in result[0]
    assert "started" in result[0]
    assert "completed" in result[1]
    assert "planner" in result[2]


def test_build_itinerary_view_empty() -> None:
    """Test itinerary view with no events."""
    result = build_itinerary_view([])

    assert result["days"] == []
    assert result["status"] == "pending"


def test_build_itinerary_view_with_planner_complete() -> None:
    """Test itinerary view after planner completes."""
    events = [
        {"node": "intent", "phase": "completed", "summary": "Intent extracted"},
        {"node": "planner", "phase": "completed", "summary": "Plan created"},
    ]

    result = build_itinerary_view(events)

    assert result["status"] == "planned"
    assert len(result["days"]) == 2  # Stub creates 2 days
    assert result["days"][0]["day"] == 1
    assert "slots" in result["days"][0]


def test_build_itinerary_view_fully_completed() -> None:
    """Test itinerary view when responder completes."""
    events = [
        {"node": "planner", "phase": "completed", "summary": "Plan created"},
        {"node": "responder", "phase": "completed", "summary": "Response ready"},
    ]

    result = build_itinerary_view(events)

    assert result["status"] == "completed"


def test_build_telemetry_view_empty() -> None:
    """Test telemetry view with no events."""
    result = build_telemetry_view([])

    assert result["nodes_completed"] == []
    assert len(result["nodes_pending"]) == 8  # All 8 nodes pending
    assert result["violations"] == []


def test_build_telemetry_view_with_completions() -> None:
    """Test telemetry view with some completed nodes."""
    events = [
        {"node": "intent", "phase": "completed", "summary": "Done"},
        {"node": "planner", "phase": "completed", "summary": "Done"},
        {"node": "verifier", "phase": "completed", "summary": "0 violations found"},
    ]

    result = build_telemetry_view(events)

    assert "intent" in result["nodes_completed"]
    assert "planner" in result["nodes_completed"]
    assert "verifier" in result["nodes_completed"]
    assert len(result["nodes_completed"]) == 3

    assert "selector" in result["nodes_pending"]  # Not completed yet
    assert len(result["violations"]) == 1
    assert "No violations" in result["violations"][0]


def test_build_telemetry_view_progress() -> None:
    """Test telemetry view progress calculation."""
    events = [
        {"node": "intent", "phase": "completed", "summary": "Done"},
        {"node": "planner", "phase": "completed", "summary": "Done"},
    ]

    result = build_telemetry_view(events)

    assert "2/8" in result["checks"]
