"""Tests for real selector node (PR-6B)."""

from datetime import date, datetime
from uuid import uuid4

import pytest

from backend.app.models.common import ChoiceKind, Provenance
from backend.app.models.intent import DateWindow, IntentV1, Preferences
from backend.app.models.plan import Choice, ChoiceFeatures
from backend.app.orchestration.selector import score_choice, select_best_choices
from backend.app.orchestration.state import GraphState


def make_provenance(ref_id: str) -> Provenance:
    """Helper to create test provenance."""
    return Provenance(
        source="test",
        ref_id=ref_id,
        fetched_at=datetime.utcnow(),
        cache_hit=False,
    )


@pytest.fixture
def test_intent() -> IntentV1:
    """Create a test intent with budget and preferences."""
    return IntentV1(
        city="Paris",
        date_window=DateWindow(
            start=date(2025, 6, 10),
            end=date(2025, 6, 14),
            tz="Europe/Paris",
        ),
        budget_usd_cents=250000,  # $2,500
        airports=["JFK"],
        prefs=Preferences(
            kid_friendly=False,
            themes=["art", "food"],
            avoid_overnight=False,
            locked_slots=[],
        ),
    )


def test_score_choice_penalizes_expensive_flights(test_intent: IntentV1) -> None:
    """Test that expensive flights get lower scores."""
    cheap_flight = Choice(
        kind=ChoiceKind.flight,
        option_ref="cheap_flight",
        features=ChoiceFeatures(
            cost_usd_cents=50000,  # $500 (20% of budget)
            travel_seconds=28800,  # 8 hours
            indoor=None,
            themes=[],
        ),
        score=None,
        provenance=make_provenance("cheap"),
    )

    expensive_flight = Choice(
        kind=ChoiceKind.flight,
        option_ref="expensive_flight",
        features=ChoiceFeatures(
            cost_usd_cents=150000,  # $1,500 (60% of budget)
            travel_seconds=28800,  # 8 hours
            indoor=None,
            themes=[],
        ),
        score=None,
        provenance=make_provenance("expensive"),
    )

    cheap_score = score_choice(cheap_flight, intent=test_intent)
    expensive_score = score_choice(expensive_flight, intent=test_intent)

    assert cheap_score > expensive_score
    assert 0.0 <= cheap_score <= 1.0
    assert 0.0 <= expensive_score <= 1.0


def test_score_choice_rewards_theme_match(test_intent: IntentV1) -> None:
    """Test that choices matching user themes get higher scores."""
    # Use cost that incurs moderate penalty (30k = 12% of budget, above 10% threshold)
    no_match = Choice(
        kind=ChoiceKind.attraction,
        option_ref="no_match",
        features=ChoiceFeatures(
            cost_usd_cents=30000,  # 12% of budget - incurs penalty
            travel_seconds=None,
            indoor=True,
            themes=["shopping"],  # No match with art/food
        ),
        score=None,
        provenance=make_provenance("no_match"),
    )

    with_match = Choice(
        kind=ChoiceKind.attraction,
        option_ref="with_match",
        features=ChoiceFeatures(
            cost_usd_cents=30000,  # Same cost
            travel_seconds=None,
            indoor=True,
            themes=["art", "museum"],  # Matches "art"
        ),
        score=None,
        provenance=make_provenance("with_match"),
    )

    no_match_score = score_choice(no_match, intent=test_intent)
    with_match_score = score_choice(with_match, intent=test_intent)

    assert with_match_score > no_match_score


def test_score_choice_is_deterministic(test_intent: IntentV1) -> None:
    """Test that scoring is deterministic."""
    choice = Choice(
        kind=ChoiceKind.lodging,
        option_ref="hotel_test",
        features=ChoiceFeatures(
            cost_usd_cents=75000,  # $750 total
            travel_seconds=None,
            indoor=True,
            themes=["mid"],
        ),
        score=None,
        provenance=make_provenance("hotel"),
    )

    score1 = score_choice(choice, intent=test_intent)
    score2 = score_choice(choice, intent=test_intent)

    assert score1 == score2


def test_score_choice_penalizes_long_duration(test_intent: IntentV1) -> None:
    """Test that very long travel times are penalized."""
    short_flight = Choice(
        kind=ChoiceKind.flight,
        option_ref="short",
        features=ChoiceFeatures(
            cost_usd_cents=80000,
            travel_seconds=28800,  # 8 hours
            indoor=None,
            themes=[],
        ),
        score=None,
        provenance=make_provenance("short"),
    )

    long_flight = Choice(
        kind=ChoiceKind.flight,
        option_ref="long",
        features=ChoiceFeatures(
            cost_usd_cents=80000,  # Same cost
            travel_seconds=57600,  # 16 hours
            indoor=None,
            themes=[],
        ),
        score=None,
        provenance=make_provenance("long"),
    )

    short_score = score_choice(short_flight, intent=test_intent)
    long_score = score_choice(long_flight, intent=test_intent)

    assert short_score > long_score


def test_select_best_choices_respects_max_selected(test_intent: IntentV1) -> None:
    """Test that selection respects max_selected limit."""
    # Create 6 choices
    choices = [
        Choice(
            kind=ChoiceKind.flight,
            option_ref=f"flight_{i}",
            features=ChoiceFeatures(
                cost_usd_cents=50000 + i * 10000,
                travel_seconds=28800,
                indoor=None,
                themes=[],
            ),
            score=None,
            provenance=make_provenance(f"flight_{i}"),
        )
        for i in range(6)
    ]

    selected, logs = select_best_choices(
        choices=choices,
        intent=test_intent,
        max_selected=3,
    )

    assert len(selected) == 3


def test_select_best_choices_orders_by_score(test_intent: IntentV1) -> None:
    """Test that selected choices are ordered by score (highest first)."""
    choices = [
        Choice(
            kind=ChoiceKind.lodging,
            option_ref="expensive",
            features=ChoiceFeatures(
                cost_usd_cents=120000,  # Most expensive
                travel_seconds=None,
                indoor=True,
                themes=["luxury"],
            ),
            score=None,
            provenance=make_provenance("expensive"),
        ),
        Choice(
            kind=ChoiceKind.lodging,
            option_ref="budget",
            features=ChoiceFeatures(
                cost_usd_cents=40000,  # Cheapest
                travel_seconds=None,
                indoor=True,
                themes=["budget"],
            ),
            score=None,
            provenance=make_provenance("budget"),
        ),
        Choice(
            kind=ChoiceKind.lodging,
            option_ref="mid",
            features=ChoiceFeatures(
                cost_usd_cents=80000,  # Middle
                travel_seconds=None,
                indoor=True,
                themes=["mid"],
            ),
            score=None,
            provenance=make_provenance("mid"),
        ),
    ]

    selected, logs = select_best_choices(
        choices=choices,
        intent=test_intent,
        max_selected=3,
    )

    # Budget should be first (best score), expensive last (worst score)
    assert selected[0].option_ref == "budget"
    assert selected[-1].option_ref == "expensive"

    # Verify scores are populated and descending
    assert all(c.score is not None for c in selected)
    for i in range(len(selected) - 1):
        assert selected[i].score >= selected[i + 1].score  # type: ignore


def test_select_best_choices_populates_scores(test_intent: IntentV1) -> None:
    """Test that selected choices have scores populated."""
    choices = [
        Choice(
            kind=ChoiceKind.attraction,
            option_ref=f"attraction_{i}",
            features=ChoiceFeatures(
                cost_usd_cents=2000,
                travel_seconds=None,
                indoor=True,
                themes=["art"] if i == 0 else [],
            ),
            score=None,
            provenance=make_provenance(f"attraction_{i}"),
        )
        for i in range(3)
    ]

    selected, logs = select_best_choices(
        choices=choices,
        intent=test_intent,
        max_selected=2,
    )

    # All selected choices should have scores
    for choice in selected:
        assert choice.score is not None
        assert 0.0 <= choice.score <= 1.0


def test_select_best_choices_logs_structure(test_intent: IntentV1) -> None:
    """Test that decision logs have correct structure."""
    choices = [
        Choice(
            kind=ChoiceKind.flight,
            option_ref=f"flight_{i}",
            features=ChoiceFeatures(
                cost_usd_cents=50000 + i * 10000,
                travel_seconds=28800,
                indoor=None,
                themes=[],
            ),
            score=None,
            provenance=make_provenance(f"flight_{i}"),
        )
        for i in range(5)
    ]

    selected, logs = select_best_choices(
        choices=choices,
        intent=test_intent,
        max_selected=2,
    )

    # Should have at least one log entry
    assert len(logs) > 0

    # Check first log entry structure
    log = logs[0]
    assert "kind" in log
    assert "chosen" in log
    assert "rejected" in log

    # Check chosen structure
    chosen = log["chosen"]
    assert "option_ref" in chosen
    assert "score" in chosen
    assert "components" in chosen
    assert isinstance(chosen["score"], (int, float))
    assert isinstance(chosen["components"], dict)

    # Check rejected structure
    rejected = log["rejected"]
    assert isinstance(rejected, list)
    if len(rejected) > 0:
        assert "option_ref" in rejected[0]
        assert "score" in rejected[0]
        assert "components" in rejected[0]


def test_select_best_choices_logs_top_2_rejected(test_intent: IntentV1) -> None:
    """Test that logs include top 2 rejected choices per kind."""
    # Create 5 flights
    choices = [
        Choice(
            kind=ChoiceKind.flight,
            option_ref=f"flight_{i}",
            features=ChoiceFeatures(
                cost_usd_cents=50000 + i * 5000,
                travel_seconds=28800,
                indoor=None,
                themes=[],
            ),
            score=None,
            provenance=make_provenance(f"flight_{i}"),
        )
        for i in range(5)
    ]

    selected, logs = select_best_choices(
        choices=choices,
        intent=test_intent,
        max_selected=2,  # Select 2, reject 3
    )

    # Find flight log
    flight_log = next((log for log in logs if log["kind"] == "flight"), None)
    assert flight_log is not None

    # Should have exactly 2 rejected (top 2 of the 3 rejected)
    assert len(flight_log["rejected"]) == 2


def test_select_best_choices_handles_empty_list(test_intent: IntentV1) -> None:
    """Test that empty choice list is handled gracefully."""
    selected, logs = select_best_choices(
        choices=[],
        intent=test_intent,
        max_selected=10,
    )

    assert selected == []
    assert logs == []


def test_select_best_choices_is_deterministic(test_intent: IntentV1) -> None:
    """Test that selection is deterministic."""
    choices = [
        Choice(
            kind=ChoiceKind.attraction,
            option_ref=f"attr_{i}",
            features=ChoiceFeatures(
                cost_usd_cents=2000 + i * 500,
                travel_seconds=None,
                indoor=True,
                themes=["art"] if i % 2 == 0 else ["food"],
            ),
            score=None,
            provenance=make_provenance(f"attr_{i}"),
        )
        for i in range(10)
    ]

    selected1, logs1 = select_best_choices(
        choices=choices,
        intent=test_intent,
        max_selected=5,
    )

    selected2, logs2 = select_best_choices(
        choices=choices,
        intent=test_intent,
        max_selected=5,
    )

    # Same selection order
    assert [c.option_ref for c in selected1] == [c.option_ref for c in selected2]

    # Same scores
    assert [c.score for c in selected1] == [c.score for c in selected2]


def test_select_best_choices_preserves_provenance(test_intent: IntentV1) -> None:
    """Test that provenance is preserved in selected choices."""
    prov = make_provenance("test_provenance_123")
    choice = Choice(
        kind=ChoiceKind.flight,
        option_ref="test_flight",
        features=ChoiceFeatures(
            cost_usd_cents=60000,
            travel_seconds=28800,
            indoor=None,
            themes=[],
        ),
        score=None,
        provenance=prov,
    )

    selected, _ = select_best_choices(
        choices=[choice],
        intent=test_intent,
        max_selected=10,
    )

    assert len(selected) == 1
    assert selected[0].provenance == prov
    assert selected[0].provenance.ref_id == "test_provenance_123"


class MockSession:
    """Mock database session for integration tests."""

    def add(self, *args: object) -> None:
        pass

    async def execute(self, *args: object, **kwargs: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def flush(self) -> None:
        pass


@pytest.mark.asyncio
async def test_graph_integration_selector_scores_choices(test_intent: IntentV1) -> None:
    """Test that selector node integrates with graph and scores choices."""
    from backend.app.orchestration.graph import selector_stub

    # Create state with pre-populated choices
    choices = [
        Choice(
            kind=ChoiceKind.flight,
            option_ref=f"flight_{i}",
            features=ChoiceFeatures(
                cost_usd_cents=50000 + i * 10000,
                travel_seconds=28800,
                indoor=None,
                themes=[],
            ),
            score=None,
            provenance=make_provenance(f"flight_{i}"),
        )
        for i in range(5)
    ]

    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=test_intent,
        choices=choices,
    )

    session = MockSession()

    # Run selector
    result_state = await selector_stub(state, session)  # type: ignore[arg-type]

    # Verify choices are scored
    assert result_state.choices is not None
    assert len(result_state.choices) > 0
    assert all(c.score is not None for c in result_state.choices)

    # Verify selector logs are populated
    assert len(result_state.selector_logs) > 0


@pytest.mark.asyncio
async def test_graph_integration_selector_handles_empty_choices(
    test_intent: IntentV1,
) -> None:
    """Test that selector handles empty choices gracefully."""
    from backend.app.orchestration.graph import selector_stub

    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=test_intent,
        choices=[],
    )

    session = MockSession()

    # Should not crash
    result_state = await selector_stub(state, session)  # type: ignore[arg-type]

    assert result_state.choices == []
    assert result_state.selector_logs == []
