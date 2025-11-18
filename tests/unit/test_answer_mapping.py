"""Tests for GraphState → QAPlanResponse mapping (PR-8B)."""

from datetime import date, datetime
from uuid import uuid4

import pytest

from backend.app.models.answer import (
    AnswerV1,
    build_qa_plan_response_from_state,
)
from backend.app.models.common import ChoiceKind, Provenance
from backend.app.models.intent import DateWindow, IntentV1, Preferences
from backend.app.models.itinerary import Citation
from backend.app.models.plan import Choice, ChoiceFeatures
from backend.app.orchestration.state import GraphState


def test_build_qa_plan_response_maps_answer_and_decisions() -> None:
    """Test that answer_markdown and decisions are mapped from state.answer."""
    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(themes=["art"]),
        ),
        answer=AnswerV1(
            answer_markdown="# Test Answer\n\nContent here",
            decisions=["Decision 1", "Decision 2"],
            synthesis_source="stub",
        ),
        choices=[],
        citations=[],
    )

    response = build_qa_plan_response_from_state(state)

    assert response.answer_markdown == "# Test Answer\n\nContent here"
    assert response.decisions == ["Decision 1", "Decision 2"]


def test_build_qa_plan_response_maps_citations() -> None:
    """Test that citations are mapped from state.citations."""
    prov = Provenance(source="tool", ref_id="ref1", fetched_at=datetime.utcnow())
    citation = Citation(claim="test claim", provenance=prov)

    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(),
        ),
        answer=AnswerV1(
            answer_markdown="Test",
            decisions=[],
            synthesis_source="stub",
        ),
        choices=[],
        citations=[citation],
    )

    response = build_qa_plan_response_from_state(state)

    assert len(response.citations) == 1
    assert response.citations[0].claim == "test claim"
    assert response.citations[0].provenance.source == "tool"


def test_build_qa_plan_response_calculates_total_cost() -> None:
    """Test that total_cost_usd is correctly calculated from choices."""
    choices = [
        Choice(
            kind=ChoiceKind.flight,
            option_ref="AF123",
            features=ChoiceFeatures(cost_usd_cents=50000, themes=[]),
            provenance=Provenance(source="tool.flights", fetched_at=datetime.utcnow()),
        ),
        Choice(
            kind=ChoiceKind.lodging,
            option_ref="Hotel Paris",
            features=ChoiceFeatures(cost_usd_cents=15000, themes=[]),
            provenance=Provenance(source="tool.lodging", fetched_at=datetime.utcnow()),
        ),
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="Louvre",
            features=ChoiceFeatures(cost_usd_cents=2000, themes=["art"]),
            provenance=Provenance(source="tool.attractions", fetched_at=datetime.utcnow()),
        ),
    ]

    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(),
        ),
        answer=AnswerV1(
            answer_markdown="Test",
            decisions=[],
            synthesis_source="stub",
        ),
        choices=choices,
        citations=[],
    )

    response = build_qa_plan_response_from_state(state)

    # 50000 + 15000 + 2000 = 67000 cents = 670 USD
    assert response.itinerary.total_cost_usd == 670


def test_build_qa_plan_response_handles_zero_costs() -> None:
    """Test that zero costs are handled gracefully."""
    choices = [
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="Free Museum",
            features=ChoiceFeatures(cost_usd_cents=0, themes=[]),
            provenance=Provenance(source="tool", fetched_at=datetime.utcnow()),
        ),
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="Paid Museum",
            features=ChoiceFeatures(cost_usd_cents=1500, themes=[]),
            provenance=Provenance(source="tool", fetched_at=datetime.utcnow()),
        ),
    ]

    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(),
        ),
        answer=AnswerV1(
            answer_markdown="Test",
            decisions=[],
            synthesis_source="stub",
        ),
        choices=choices,
        citations=[],
    )

    response = build_qa_plan_response_from_state(state)

    # Free museum (0) + paid museum (1500 cents) = 1500 cents = 15 USD
    assert response.itinerary.total_cost_usd == 15


def test_build_qa_plan_response_populates_tools_used() -> None:
    """Test that tools_used is populated from provenance."""
    choices = [
        Choice(
            kind=ChoiceKind.flight,
            option_ref="AF123",
            features=ChoiceFeatures(cost_usd_cents=50000, themes=[]),
            provenance=Provenance(source="tool.flights", fetched_at=datetime.utcnow()),
        ),
        Choice(
            kind=ChoiceKind.flight,
            option_ref="AF456",
            features=ChoiceFeatures(cost_usd_cents=55000, themes=[]),
            provenance=Provenance(source="tool.flights", fetched_at=datetime.utcnow()),
        ),
        Choice(
            kind=ChoiceKind.lodging,
            option_ref="Hotel",
            features=ChoiceFeatures(cost_usd_cents=15000, themes=[]),
            provenance=Provenance(source="tool.lodging", fetched_at=datetime.utcnow()),
        ),
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="Louvre",
            features=ChoiceFeatures(cost_usd_cents=2000, themes=[]),
            provenance=Provenance(source="manual", fetched_at=datetime.utcnow()),
        ),
    ]

    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(),
        ),
        answer=AnswerV1(
            answer_markdown="Test",
            decisions=[],
            synthesis_source="stub",
        ),
        choices=choices,
        citations=[],
    )

    response = build_qa_plan_response_from_state(state)

    # Should have 3 distinct tools
    assert len(response.tools_used) == 3

    # Check they're sorted alphabetically
    tool_names = [t.name for t in response.tools_used]
    assert tool_names == sorted(tool_names)

    # Check counts
    tools_by_name = {t.name: t.count for t in response.tools_used}
    assert tools_by_name["tool.flights"] == 2
    assert tools_by_name["tool.lodging"] == 1
    assert tools_by_name["manual"] == 1


def test_build_qa_plan_response_handles_empty_choices() -> None:
    """Test that empty choices list is handled gracefully."""
    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(),
        ),
        answer=AnswerV1(
            answer_markdown="No options found",
            decisions=[],
            synthesis_source="stub",
        ),
        choices=[],
        citations=[],
    )

    response = build_qa_plan_response_from_state(state)

    assert response.itinerary.total_cost_usd == 0
    assert response.itinerary.days == []
    assert response.tools_used == []


def test_build_qa_plan_response_raises_on_missing_answer() -> None:
    """Test that ValueError is raised if state.answer is None."""
    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(),
        ),
        answer=None,  # Missing answer
        choices=[],
        citations=[],
    )

    with pytest.raises(ValueError, match="state.answer must not be None"):
        build_qa_plan_response_from_state(state)


def test_build_qa_plan_response_creates_itinerary_days() -> None:
    """Test that itinerary days are created from choices."""
    choices = [
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="Louvre",
            features=ChoiceFeatures(cost_usd_cents=2000, themes=["art"]),
            provenance=Provenance(source="tool", fetched_at=datetime.utcnow()),
        ),
        Choice(
            kind=ChoiceKind.lodging,
            option_ref="Hotel Paris",
            features=ChoiceFeatures(cost_usd_cents=15000, themes=[]),
            provenance=Provenance(source="tool", fetched_at=datetime.utcnow()),
        ),
    ]

    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(),
        ),
        answer=AnswerV1(
            answer_markdown="Test",
            decisions=[],
            synthesis_source="stub",
        ),
        choices=choices,
        citations=[],
    )

    response = build_qa_plan_response_from_state(state)

    # Should have 1 day with all choices
    assert len(response.itinerary.days) == 1
    day = response.itinerary.days[0]
    assert day.date == "2025-06-10"
    assert len(day.items) == 2

    # Check item titles contain choice info
    titles = [item.title for item in day.items]
    assert any("attraction" in t.lower() and "louvre" in t.lower() for t in titles)
    assert any("lodging" in t.lower() and "hotel" in t.lower() for t in titles)


def test_build_qa_plan_response_is_deterministic() -> None:
    """Test that mapper produces consistent output for same input."""
    choices = [
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="A",
            features=ChoiceFeatures(cost_usd_cents=1000, themes=[]),
            provenance=Provenance(source="tool.b", fetched_at=datetime.utcnow()),
        ),
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="B",
            features=ChoiceFeatures(cost_usd_cents=2000, themes=[]),
            provenance=Provenance(source="tool.a", fetched_at=datetime.utcnow()),
        ),
    ]

    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(),
        ),
        answer=AnswerV1(
            answer_markdown="Test",
            decisions=[],
            synthesis_source="stub",
        ),
        choices=choices,
        citations=[],
    )

    response1 = build_qa_plan_response_from_state(state)
    response2 = build_qa_plan_response_from_state(state)

    assert response1.answer_markdown == response2.answer_markdown
    assert response1.itinerary.total_cost_usd == response2.itinerary.total_cost_usd
    assert [t.name for t in response1.tools_used] == [t.name for t in response2.tools_used]
