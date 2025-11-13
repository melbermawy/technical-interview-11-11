"""Property-based tests for non-overlapping slots."""

import random
from datetime import date, datetime, time

from backend.app.models import ChoiceFeatures, ChoiceKind, DayPlan, Provenance, Slot, TimeWindow
from backend.app.models.plan import Choice


def generate_non_overlapping_slots(n: int, seed: int = 42) -> list[Slot]:
    """Generate n non-overlapping slots with fixed seed."""
    random.seed(seed)
    stub_prov = Provenance(source="tool", fetched_at=datetime.now())

    slots = []
    current_hour = 8  # Start at 8 AM

    for _ in range(n):
        if current_hour >= 22:  # Don't go past 10 PM
            break

        start = time(current_hour, 0)
        duration = random.randint(1, 3)  # 1-3 hours
        end = time(min(current_hour + duration, 23), 0)

        stub_features = ChoiceFeatures(cost_usd_cents=random.randint(1000, 10000))
        stub_choice = Choice(
            kind=ChoiceKind.attraction,
            option_ref=f"activity_{len(slots)}",
            features=stub_features,
            provenance=stub_prov,
        )

        slots.append(Slot(window=TimeWindow(start=start, end=end), choices=[stub_choice]))

        current_hour += duration + 1  # Add gap between slots

    return slots


def test_generated_slots_are_non_overlapping() -> None:
    """Test that generated slots are non-overlapping."""
    slots = generate_non_overlapping_slots(5, seed=42)

    # Verify non-overlapping
    sorted_slots = sorted(slots, key=lambda s: s.window.start)
    for i in range(len(sorted_slots) - 1):
        current_end = sorted_slots[i].window.end
        next_start = sorted_slots[i + 1].window.start
        assert current_end <= next_start, f"Overlap detected: {current_end} > {next_start}"


def test_non_overlapping_slots_serialize_and_validate() -> None:
    """Test that non-overlapping slots serialize and re-validate correctly."""
    slots = generate_non_overlapping_slots(4, seed=123)

    # Create day plan
    day_plan = DayPlan(date=date(2025, 6, 10), slots=slots)

    # Serialize
    data = day_plan.model_dump()

    # Deserialize
    restored = DayPlan(**data)

    # Still non-overlapping
    sorted_slots = sorted(restored.slots, key=lambda s: s.window.start)
    for i in range(len(sorted_slots) - 1):
        current_end = sorted_slots[i].window.end
        next_start = sorted_slots[i + 1].window.start
        assert current_end <= next_start


def test_property_various_seeds() -> None:
    """Test non-overlapping property with various random seeds."""
    for seed in [1, 10, 100, 999, 12345]:
        slots = generate_non_overlapping_slots(6, seed=seed)

        # Serialize and deserialize
        day_plan = DayPlan(date=date(2025, 6, 10), slots=slots)
        data = day_plan.model_dump()
        restored = DayPlan(**data)

        # Verify still non-overlapping
        sorted_slots = sorted(restored.slots, key=lambda s: s.window.start)
        for i in range(len(sorted_slots) - 1):
            current_end = sorted_slots[i].window.end
            next_start = sorted_slots[i + 1].window.start
            assert current_end <= next_start, f"Seed {seed}: overlap {current_end} > {next_start}"
