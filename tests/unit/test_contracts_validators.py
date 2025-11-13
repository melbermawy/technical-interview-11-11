"""Test contract validators and invariants."""

from datetime import date, datetime, time

import pytest
from pydantic import ValidationError

from backend.app.models import (
    Assumptions,
    ChoiceFeatures,
    ChoiceKind,
    DateWindow,
    DayPlan,
    IntentV1,
    PlanV1,
    Preferences,
    Provenance,
    Slot,
    TimeWindow,
)
from backend.app.models.plan import Choice


def test_date_window_reversed_fails() -> None:
    """Test that reversed DateWindow fails validation."""
    with pytest.raises(ValidationError, match="end must be >= start"):
        DateWindow(start=date(2025, 6, 15), end=date(2025, 6, 10), tz="Europe/Paris")


def test_date_window_same_day_passes() -> None:
    """Test that same-day DateWindow is valid."""
    dw = DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 10), tz="Europe/Paris")
    assert dw.start == dw.end


def test_intent_empty_airports_fails() -> None:
    """Test that IntentV1 with empty airports fails validation."""
    with pytest.raises(ValidationError):
        IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"
            ),
            budget_usd_cents=300000,
            airports=[],
            prefs=Preferences(),
        )


def test_intent_zero_budget_fails() -> None:
    """Test that IntentV1 with zero budget fails validation."""
    with pytest.raises(ValidationError):
        IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"
            ),
            budget_usd_cents=0,
            airports=["CDG"],
            prefs=Preferences(),
        )


def test_overlapping_slots_fails() -> None:
    """Test that overlapping slots in DayPlan fail validation."""
    stub_prov = Provenance(source="tool", fetched_at=datetime.now())
    stub_features = ChoiceFeatures(cost_usd_cents=1000)
    stub_choice = Choice(
        kind=ChoiceKind.attraction,
        option_ref="stub",
        features=stub_features,
        provenance=stub_prov,
    )

    slot1 = Slot(window=TimeWindow(start=time(10, 0), end=time(12, 0)), choices=[stub_choice])
    slot2 = Slot(window=TimeWindow(start=time(11, 0), end=time(13, 0)), choices=[stub_choice])

    with pytest.raises(ValidationError, match="Overlapping slots"):
        DayPlan(date=date(2025, 6, 10), slots=[slot1, slot2])


def test_non_overlapping_slots_passes() -> None:
    """Test that non-overlapping slots pass validation."""
    stub_prov = Provenance(source="tool", fetched_at=datetime.now())
    stub_features = ChoiceFeatures(cost_usd_cents=1000)
    stub_choice = Choice(
        kind=ChoiceKind.attraction,
        option_ref="stub",
        features=stub_features,
        provenance=stub_prov,
    )

    slot1 = Slot(window=TimeWindow(start=time(10, 0), end=time(12, 0)), choices=[stub_choice])
    slot2 = Slot(window=TimeWindow(start=time(13, 0), end=time(15, 0)), choices=[stub_choice])

    day_plan = DayPlan(date=date(2025, 6, 10), slots=[slot1, slot2])
    assert len(day_plan.slots) == 2


def test_plan_too_few_days_fails() -> None:
    """Test that PlanV1 with fewer than 4 days fails validation."""
    stub_prov = Provenance(source="tool", fetched_at=datetime.now())
    stub_features = ChoiceFeatures(cost_usd_cents=1000)
    stub_choice = Choice(
        kind=ChoiceKind.attraction,
        option_ref="stub",
        features=stub_features,
        provenance=stub_prov,
    )
    stub_slot = Slot(window=TimeWindow(start=time(10, 0), end=time(12, 0)), choices=[stub_choice])

    days = [DayPlan(date=date(2025, 6, 10), slots=[stub_slot]) for _ in range(3)]
    assumptions = Assumptions(fx_rate_usd_eur=1.1, daily_spend_est_cents=5000)

    with pytest.raises(ValidationError):
        PlanV1(days=days, assumptions=assumptions, rng_seed=42)


def test_plan_too_many_days_fails() -> None:
    """Test that PlanV1 with more than 7 days fails validation."""
    stub_prov = Provenance(source="tool", fetched_at=datetime.now())
    stub_features = ChoiceFeatures(cost_usd_cents=1000)
    stub_choice = Choice(
        kind=ChoiceKind.attraction,
        option_ref="stub",
        features=stub_features,
        provenance=stub_prov,
    )
    stub_slot = Slot(window=TimeWindow(start=time(10, 0), end=time(12, 0)), choices=[stub_choice])

    days = [DayPlan(date=date(2025, 6, 10), slots=[stub_slot]) for _ in range(8)]
    assumptions = Assumptions(fx_rate_usd_eur=1.1, daily_spend_est_cents=5000)

    with pytest.raises(ValidationError):
        PlanV1(days=days, assumptions=assumptions, rng_seed=42)


def test_plan_valid_days_passes() -> None:
    """Test that PlanV1 with 4-7 days passes validation."""
    stub_prov = Provenance(source="tool", fetched_at=datetime.now())
    stub_features = ChoiceFeatures(cost_usd_cents=1000)
    stub_choice = Choice(
        kind=ChoiceKind.attraction,
        option_ref="stub",
        features=stub_features,
        provenance=stub_prov,
    )
    stub_slot = Slot(window=TimeWindow(start=time(10, 0), end=time(12, 0)), choices=[stub_choice])

    for num_days in [4, 5, 6, 7]:
        days = [DayPlan(date=date(2025, 6, 10), slots=[stub_slot]) for _ in range(num_days)]
        assumptions = Assumptions(fx_rate_usd_eur=1.1, daily_spend_est_cents=5000)
        plan = PlanV1(days=days, assumptions=assumptions, rng_seed=42)
        assert len(plan.days) == num_days
