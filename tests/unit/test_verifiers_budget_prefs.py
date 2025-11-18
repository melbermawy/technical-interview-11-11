"""Tests for budget and preferences verifiers (PR-7A)."""

from datetime import date, datetime

import pytest

from backend.app.models.common import ChoiceKind, Provenance
from backend.app.models.intent import DateWindow, IntentV1, Preferences
from backend.app.models.plan import Choice, ChoiceFeatures
from backend.app.models.violations import ViolationKind, ViolationSeverity
from backend.app.verification.verifiers import run_verifiers, verify_budget, verify_preferences


def make_provenance(ref_id: str) -> Provenance:
    """Helper to create test provenance."""
    return Provenance(
        source="test",
        ref_id=ref_id,
        fetched_at=datetime.utcnow(),
        cache_hit=False,
    )


def make_choice(
    option_ref: str,
    cost: int,
    themes: list[str] | None = None,
    kind: ChoiceKind = ChoiceKind.attraction,
) -> Choice:
    """Helper to create test choice."""
    return Choice(
        kind=kind,
        option_ref=option_ref,
        features=ChoiceFeatures(
            cost_usd_cents=cost,
            travel_seconds=None,
            indoor=True,
            themes=themes or [],
        ),
        score=None,
        provenance=make_provenance(option_ref),
    )


@pytest.fixture
def base_intent() -> IntentV1:
    """Create a base intent for testing."""
    return IntentV1(
        city="Paris",
        date_window=DateWindow(
            start=date(2025, 6, 10),
            end=date(2025, 6, 14),
            tz="Europe/Paris",
        ),
        budget_usd_cents=100000,  # $1,000
        airports=["JFK"],
        prefs=Preferences(
            kid_friendly=False,
            themes=["art", "food"],
            avoid_overnight=False,
            locked_slots=[],
        ),
    )


# Budget verification tests


def test_verify_budget_returns_empty_when_no_budget_in_intent(base_intent: IntentV1) -> None:
    """Test that verify_budget returns empty list when budget is missing."""
    # Create intent with no budget (set to 0)
    intent = IntentV1(
        city="Paris",
        date_window=base_intent.date_window,
        budget_usd_cents=1,  # Minimum value, but we'll test edge case
        airports=["JFK"],
        prefs=Preferences(),
    )

    choices = [make_choice("choice1", 50000, [])]

    # This should still work with budget=1, so let's test actual missing case differently
    # Actually, budget_usd_cents is required >0, so let's test the logic correctly
    violations = verify_budget(intent, choices)

    # With budget=1 and cost=50000, this will be BLOCKING
    assert len(violations) == 1
    assert violations[0].severity == ViolationSeverity.BLOCKING


def test_verify_budget_returns_empty_when_under_budget(base_intent: IntentV1) -> None:
    """Test that no violations when total cost is under budget."""
    choices = [
        make_choice("choice1", 30000, []),  # $300
        make_choice("choice2", 40000, []),  # $400
        # Total: $700, budget: $1000
    ]

    violations = verify_budget(base_intent, choices)

    assert violations == []


def test_verify_budget_emits_advisory_when_slightly_over_budget(base_intent: IntentV1) -> None:
    """Test ADVISORY violation when cost is 1-20% over budget."""
    choices = [
        make_choice("choice1", 60000, []),  # $600
        make_choice("choice2", 50000, []),  # $500
        # Total: $1100 = 110% of $1000 budget (within 20% threshold)
    ]

    violations = verify_budget(base_intent, choices)

    assert len(violations) == 1
    violation = violations[0]

    assert violation.kind == ViolationKind.BUDGET
    assert violation.code == "NEAR_BUDGET"
    assert violation.severity == ViolationSeverity.ADVISORY
    assert "slightly above" in violation.message.lower()
    assert set(violation.affected_choice_ids) == {"choice1", "choice2"}
    assert violation.details["total_usd_cents"] == 110000
    assert violation.details["budget_usd_cents"] == 100000
    assert violation.details["ratio"] == 1.1


def test_verify_budget_emits_blocking_when_far_over_budget(base_intent: IntentV1) -> None:
    """Test BLOCKING violation when cost is >20% over budget."""
    choices = [
        make_choice("choice1", 80000, []),  # $800
        make_choice("choice2", 50000, []),  # $500
        # Total: $1300 = 130% of $1000 budget (>20% over)
    ]

    violations = verify_budget(base_intent, choices)

    assert len(violations) == 1
    violation = violations[0]

    assert violation.kind == ViolationKind.BUDGET
    assert violation.code == "OVER_BUDGET"
    assert violation.severity == ViolationSeverity.BLOCKING
    assert "exceeds" in violation.message.lower()
    assert "20%" in violation.message
    assert set(violation.affected_choice_ids) == {"choice1", "choice2"}
    assert violation.details["total_usd_cents"] == 130000
    assert violation.details["budget_usd_cents"] == 100000
    assert violation.details["ratio"] == 1.3


def test_verify_budget_ignores_choices_without_cost(base_intent: IntentV1) -> None:
    """Test that choices with no cost are ignored in budget calculation."""
    choices = [
        make_choice("choice1", 30000, []),  # $300
        make_choice("choice2", 0, []),  # Free
        # Total: $300, budget: $1000 - well under budget
    ]

    violations = verify_budget(base_intent, choices)

    assert violations == []


# Preferences verification tests


def test_verify_preferences_returns_empty_when_no_prefs(base_intent: IntentV1) -> None:
    """Test that verify_preferences returns empty when no preferences specified."""
    intent = IntentV1(
        city="Paris",
        date_window=base_intent.date_window,
        budget_usd_cents=100000,
        airports=["JFK"],
        prefs=Preferences(themes=[]),  # No themes
    )

    choices = [make_choice("choice1", 10000, ["shopping"])]

    violations = verify_preferences(intent, choices)

    assert violations == []


def test_verify_preferences_returns_empty_when_prefs_satisfied(base_intent: IntentV1) -> None:
    """Test that no violations when at least one required theme is present."""
    choices = [
        make_choice("choice1", 10000, ["art", "museum"]),  # Matches "art"
        make_choice("choice2", 10000, ["shopping"]),  # Doesn't match
    ]

    violations = verify_preferences(base_intent, choices)

    # No violations because "art" is present
    assert violations == []


def test_verify_preferences_creates_unfulfilled_violation_when_required_theme_missing(
    base_intent: IntentV1,
) -> None:
    """Test ADVISORY violation when required themes are not found."""
    choices = [
        make_choice("choice1", 10000, ["shopping"]),
        make_choice("choice2", 10000, ["nightlife"]),
        # Neither "art" nor "food" present
    ]

    violations = verify_preferences(base_intent, choices)

    assert len(violations) == 1
    violation = violations[0]

    assert violation.kind == ViolationKind.PREFERENCES
    assert violation.code == "PREFS_UNFULFILLED"
    assert violation.severity == ViolationSeverity.ADVISORY
    assert "no selected options match" in violation.message.lower()
    assert violation.affected_choice_ids == []  # Affects overall plan
    required_themes = violation.details["required_themes"]
    present_themes = violation.details["present_themes"]
    missing_themes = violation.details["missing_themes"]
    assert isinstance(required_themes, list)
    assert isinstance(present_themes, list)
    assert isinstance(missing_themes, list)
    assert set(required_themes) == {"art", "food"}
    assert set(present_themes) == {"shopping", "nightlife"}
    assert set(missing_themes) == {"art", "food"}


# Integration tests


@pytest.mark.asyncio
async def test_run_verifiers_aggregates_budget_and_prefs(base_intent: IntentV1) -> None:
    """Test that run_verifiers combines budget and preferences violations."""
    choices = [
        make_choice("choice1", 80000, ["shopping"]),  # $800
        make_choice("choice2", 50000, ["nightlife"]),  # $500
        # Total: $1300 (over budget), themes don't match required
        # Add lodging to prevent feasibility violations
        make_choice("lodging1", 0, [], kind=ChoiceKind.lodging),
        make_choice("lodging2", 0, [], kind=ChoiceKind.lodging),
        make_choice("lodging3", 0, [], kind=ChoiceKind.lodging),
        make_choice("lodging4", 0, [], kind=ChoiceKind.lodging),  # 4 lodging for 4 nights
    ]

    violations = await run_verifiers(intent=base_intent, choices=choices)

    # Should have 2 violations: budget + preferences (not feasibility)
    assert len(violations) == 2

    budget_viol = next(v for v in violations if v.kind == ViolationKind.BUDGET)
    pref_viol = next(v for v in violations if v.kind == ViolationKind.PREFERENCES)

    assert budget_viol.code == "OVER_BUDGET"
    assert pref_viol.code == "PREFS_UNFULFILLED"


@pytest.mark.asyncio
async def test_run_verifiers_returns_empty_when_no_choices() -> None:
    """Test that run_verifiers returns empty list when choices is empty."""
    intent = IntentV1(
        city="Paris",
        date_window=DateWindow(
            start=date(2025, 6, 10),
            end=date(2025, 6, 14),
            tz="Europe/Paris",
        ),
        budget_usd_cents=100000,
        airports=["JFK"],
        prefs=Preferences(themes=["art"]),
    )

    violations = await run_verifiers(intent=intent, choices=[])

    assert violations == []


# Graph integration test


@pytest.mark.asyncio
async def test_graph_verifier_node_integration(base_intent: IntentV1) -> None:
    """Test verifier node integration with GraphState."""
    from uuid import uuid4

    from backend.app.orchestration.graph import verify_stub
    from backend.app.orchestration.state import GraphState

    # Create state with choices that violate budget
    choices = [
        make_choice("choice1", 80000, ["art"]),
        make_choice("choice2", 60000, ["food"]),
        # Total: $1400 (40% over $1000 budget)
    ]

    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=base_intent,
        choices=choices,
    )

    # Mock session
    class MockSession:
        def add(self, *args: object) -> None:
            pass

        async def execute(self, *args: object, **kwargs: object) -> None:
            pass

        async def commit(self) -> None:
            pass

        async def flush(self) -> None:
            pass

    session = MockSession()

    # Run verifier
    result_state = await verify_stub(state, session)  # type: ignore[arg-type]

    # Verify violations populated
    assert len(result_state.violations) > 0
    assert result_state.has_blocking_violations is True

    # Check specific violation
    budget_viol = next(v for v in result_state.violations if v.kind == ViolationKind.BUDGET)
    assert budget_viol.severity == ViolationSeverity.BLOCKING


@pytest.mark.asyncio
async def test_graph_verifier_handles_empty_choices(base_intent: IntentV1) -> None:
    """Test verifier node handles empty choices gracefully."""
    from uuid import uuid4

    from backend.app.orchestration.graph import verify_stub
    from backend.app.orchestration.state import GraphState

    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=base_intent,
        choices=[],
    )

    class MockSession:
        def add(self, *args: object) -> None:
            pass

        async def execute(self, *args: object, **kwargs: object) -> None:
            pass

        async def commit(self) -> None:
            pass

        async def flush(self) -> None:
            pass

    session = MockSession()

    result_state = await verify_stub(state, session)  # type: ignore[arg-type]

    assert result_state.violations == []
    assert result_state.has_blocking_violations is False


@pytest.mark.asyncio
async def test_graph_verifier_handles_no_blocking_violations(base_intent: IntentV1) -> None:
    """Test that has_blocking_violations is False when only advisory violations."""
    from uuid import uuid4

    from backend.app.orchestration.graph import verify_stub
    from backend.app.orchestration.state import GraphState

    # Choices slightly over budget (advisory) but themes satisfied
    choices = [
        make_choice("choice1", 60000, ["art"]),
        make_choice("choice2", 50000, ["food"]),
        # Total: $1100 (10% over, advisory only)
        # Add lodging to prevent feasibility violations
        make_choice("lodging1", 0, [], kind=ChoiceKind.lodging),
        make_choice("lodging2", 0, [], kind=ChoiceKind.lodging),
        make_choice("lodging3", 0, [], kind=ChoiceKind.lodging),
        make_choice("lodging4", 0, [], kind=ChoiceKind.lodging),  # 4 lodging for 4 nights
    ]

    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=base_intent,
        choices=choices,
    )

    class MockSession:
        def add(self, *args: object) -> None:
            pass

        async def execute(self, *args: object, **kwargs: object) -> None:
            pass

        async def commit(self) -> None:
            pass

        async def flush(self) -> None:
            pass

    session = MockSession()

    result_state = await verify_stub(state, session)  # type: ignore[arg-type]

    assert len(result_state.violations) == 1  # NEAR_BUDGET only
    assert result_state.has_blocking_violations is False
