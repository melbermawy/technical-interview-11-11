"""Unit tests for tools_used mapping (PR-11B)."""

import uuid
from datetime import UTC, date, datetime

from backend.app.models.answer import (
    AnswerV1,
    build_qa_plan_response_from_state,
    build_tools_used_from_state,
)
from backend.app.models.tools import ToolCallLog
from backend.app.orchestration.state import GraphState


def test_build_tools_used_empty_calls() -> None:
    """Test that empty tool_calls returns empty list."""
    state = GraphState(
        run_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        tool_calls=[],
    )

    tools_used = build_tools_used_from_state(state)

    assert tools_used == []


def test_build_tools_used_single_tool_single_call() -> None:
    """Test single tool with single call."""
    state = GraphState(
        run_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        tool_calls=[
            ToolCallLog(
                name="adapter.flights",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                duration_ms=150,
                success=True,
            )
        ],
    )

    tools_used = build_tools_used_from_state(state)

    assert len(tools_used) == 1
    assert tools_used[0].name == "adapter.flights"
    assert tools_used[0].count == 1
    assert tools_used[0].total_ms == 150


def test_build_tools_used_single_tool_multiple_calls() -> None:
    """Test single tool with multiple calls aggregates correctly."""
    now = datetime.now(UTC)
    state = GraphState(
        run_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        tool_calls=[
            ToolCallLog(
                name="adapter.flights",
                started_at=now,
                finished_at=now,
                duration_ms=100,
                success=True,
            ),
            ToolCallLog(
                name="adapter.flights",
                started_at=now,
                finished_at=now,
                duration_ms=200,
                success=True,
            ),
            ToolCallLog(
                name="adapter.flights",
                started_at=now,
                finished_at=now,
                duration_ms=0,
                success=True,
            ),
        ],
    )

    tools_used = build_tools_used_from_state(state)

    assert len(tools_used) == 1
    assert tools_used[0].name == "adapter.flights"
    assert tools_used[0].count == 3
    assert tools_used[0].total_ms == 300


def test_build_tools_used_multiple_tools() -> None:
    """Test multiple tools with correct grouping and sorting."""
    now = datetime.now(UTC)
    state = GraphState(
        run_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        tool_calls=[
            ToolCallLog(
                name="docs.search",
                started_at=now,
                finished_at=now,
                duration_ms=50,
                success=True,
            ),
            ToolCallLog(
                name="adapter.flights",
                started_at=now,
                finished_at=now,
                duration_ms=100,
                success=True,
            ),
            ToolCallLog(
                name="adapter.flights",
                started_at=now,
                finished_at=now,
                duration_ms=200,
                success=True,
            ),
            ToolCallLog(
                name="docs.search",
                started_at=now,
                finished_at=now,
                duration_ms=30,
                success=True,
            ),
        ],
    )

    tools_used = build_tools_used_from_state(state)

    # Should be sorted alphabetically by name
    assert len(tools_used) == 2
    assert tools_used[0].name == "adapter.flights"
    assert tools_used[0].count == 2
    assert tools_used[0].total_ms == 300

    assert tools_used[1].name == "docs.search"
    assert tools_used[1].count == 2
    assert tools_used[1].total_ms == 80


def test_build_tools_used_deterministic_ordering() -> None:
    """Test that output is deterministic regardless of input order."""
    now = datetime.now(UTC)

    # Create same logs in different orders
    logs_order1 = [
        ToolCallLog(name="z.tool", started_at=now, finished_at=now, duration_ms=10, success=True),
        ToolCallLog(name="a.tool", started_at=now, finished_at=now, duration_ms=20, success=True),
        ToolCallLog(name="m.tool", started_at=now, finished_at=now, duration_ms=30, success=True),
    ]

    logs_order2 = [
        ToolCallLog(name="a.tool", started_at=now, finished_at=now, duration_ms=20, success=True),
        ToolCallLog(name="m.tool", started_at=now, finished_at=now, duration_ms=30, success=True),
        ToolCallLog(name="z.tool", started_at=now, finished_at=now, duration_ms=10, success=True),
    ]

    state1 = GraphState(
        run_id=uuid.uuid4(), org_id=uuid.uuid4(), user_id=uuid.uuid4(), tool_calls=logs_order1
    )

    state2 = GraphState(
        run_id=uuid.uuid4(), org_id=uuid.uuid4(), user_id=uuid.uuid4(), tool_calls=logs_order2
    )

    result1 = build_tools_used_from_state(state1)
    result2 = build_tools_used_from_state(state2)

    # Results should be identical (sorted by name)
    assert len(result1) == len(result2) == 3
    assert [t.name for t in result1] == [t.name for t in result2] == ["a.tool", "m.tool", "z.tool"]
    assert [t.count for t in result1] == [t.count for t in result2] == [1, 1, 1]
    assert [t.total_ms for t in result1] == [t.total_ms for t in result2] == [20, 30, 10]


def test_build_qa_plan_response_includes_tools_used() -> None:
    """Test that build_qa_plan_response_from_state correctly wires tools_used."""

    from backend.app.models.intent import DateWindow, IntentV1, Preferences

    now = datetime.now(UTC)
    run_id = uuid.uuid4()
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # Create state with minimal data + tool_calls
    state = GraphState(
        run_id=run_id,
        org_id=org_id,
        user_id=user_id,
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"
            ),
            budget_usd_cents=200000,
            airports=["JFK"],
            prefs=Preferences(themes=["art"]),
        ),
        answer=AnswerV1(
            answer_markdown="Test itinerary for Paris",
            decisions=["Selected flights based on cost"],
            synthesis_source="stub",
        ),
        tool_calls=[
            ToolCallLog(
                name="adapter.flights",
                started_at=now,
                finished_at=now,
                duration_ms=100,
                success=True,
            ),
            ToolCallLog(
                name="adapter.flights",
                started_at=now,
                finished_at=now,
                duration_ms=200,
                success=True,
            ),
            ToolCallLog(
                name="docs.search",
                started_at=now,
                finished_at=now,
                duration_ms=50,
                success=True,
            ),
        ],
        choices=[],
        citations=[],
    )

    response = build_qa_plan_response_from_state(state)

    # Verify tools_used is populated correctly
    assert len(response.tools_used) == 2

    # Should be sorted alphabetically
    assert response.tools_used[0].name == "adapter.flights"
    assert response.tools_used[0].count == 2
    assert response.tools_used[0].total_ms == 300

    assert response.tools_used[1].name == "docs.search"
    assert response.tools_used[1].count == 1
    assert response.tools_used[1].total_ms == 50

    # Verify other fields still work
    assert response.answer_markdown == "Test itinerary for Paris"
    assert response.decisions == ["Selected flights based on cost"]


def test_build_tools_used_with_failed_calls() -> None:
    """Test that failed tool calls are still counted."""
    now = datetime.now(UTC)
    state = GraphState(
        run_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        tool_calls=[
            ToolCallLog(
                name="adapter.flights",
                started_at=now,
                finished_at=now,
                duration_ms=100,
                success=True,
            ),
            ToolCallLog(
                name="adapter.flights",
                started_at=now,
                finished_at=now,
                duration_ms=50,
                success=False,
                error="Network timeout",
            ),
        ],
    )

    tools_used = build_tools_used_from_state(state)

    # Both successful and failed calls should be counted
    assert len(tools_used) == 1
    assert tools_used[0].name == "adapter.flights"
    assert tools_used[0].count == 2
    assert tools_used[0].total_ms == 150


def test_build_qa_plan_response_with_violations() -> None:
    """Test that QAPlanResponse includes violations from GraphState (PR-12)."""
    from backend.app.models.intent import DateWindow, IntentV1, Preferences
    from backend.app.models.violations import Violation, ViolationKind, ViolationSeverity

    # Create violations
    violation1 = Violation(
        kind=ViolationKind.BUDGET,
        code="OVER_BUDGET",
        message="Total cost exceeds budget by 45%",
        severity=ViolationSeverity.BLOCKING,
        affected_choice_ids=["flight_1", "hotel_2"],
        details={"budget_usd_cents": 100000, "total_usd_cents": 145000, "ratio": 1.45},
    )

    violation2 = Violation(
        kind=ViolationKind.WEATHER,
        code="RAIN_WARNING",
        message="High chance of rain on day 2",
        severity=ViolationSeverity.ADVISORY,
        affected_choice_ids=["day_2"],
        details={"precip_prob": 0.85},
    )

    state = GraphState(
        run_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"
            ),
            budget_usd_cents=100000,
            airports=["JFK"],
            prefs=Preferences(themes=["art"]),
        ),
        answer=AnswerV1(
            answer_markdown="Test itinerary",
            decisions=["Selected budget flights"],
            synthesis_source="stub",
        ),
        violations=[violation1, violation2],
        has_blocking_violations=True,
        choices=[],
        citations=[],
        tool_calls=[],
    )

    response = build_qa_plan_response_from_state(state)

    # Verify violations are populated
    assert len(response.violations) == 2
    assert response.has_blocking_violations is True

    # Check first violation
    assert response.violations[0].kind == ViolationKind.BUDGET
    assert response.violations[0].code == "OVER_BUDGET"
    assert response.violations[0].severity == ViolationSeverity.BLOCKING
    assert response.violations[0].details["ratio"] == 1.45

    # Check second violation
    assert response.violations[1].kind == ViolationKind.WEATHER
    assert response.violations[1].severity == ViolationSeverity.ADVISORY


def test_build_qa_plan_response_empty_violations() -> None:
    """Test that QAPlanResponse handles empty violations correctly (PR-12)."""
    from backend.app.models.intent import DateWindow, IntentV1, Preferences

    state = GraphState(
        run_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        intent=IntentV1(
            city="Tokyo",
            date_window=DateWindow(start=date(2025, 7, 1), end=date(2025, 7, 5), tz="Asia/Tokyo"),
            budget_usd_cents=300000,
            airports=["NRT"],
            prefs=Preferences(themes=["culture"]),
        ),
        answer=AnswerV1(
            answer_markdown="Perfect Tokyo itinerary",
            decisions=["Selected highly-rated attractions"],
            synthesis_source="stub",
        ),
        violations=[],  # No violations
        has_blocking_violations=False,
        choices=[],
        citations=[],
        tool_calls=[],
    )

    response = build_qa_plan_response_from_state(state)

    # Verify empty violations
    assert response.violations == []
    assert response.has_blocking_violations is False
