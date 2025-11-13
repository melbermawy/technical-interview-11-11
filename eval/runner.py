"""Eval runner - loads scenarios and evaluates against stubs."""

import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import yaml

from backend.app.models import (
    Activity,
    Assumptions,
    ChoiceFeatures,
    ChoiceKind,
    Citation,
    CostBreakdown,
    DateWindow,
    DayItinerary,
    DayPlan,
    Decision,
    Geo,
    IntentV1,
    ItineraryV1,
    PlanV1,
    Preferences,
    Provenance,
    Slot,
    TimeWindow,
)
from backend.app.models.plan import Choice


def load_scenarios(path: Path = Path("eval/scenarios.yaml")) -> dict[str, Any]:
    """Load scenarios from YAML."""
    with open(path) as f:
        result: dict[str, Any] = yaml.safe_load(f)
        return result


def build_intent_from_yaml(intent_data: dict[str, Any]) -> IntentV1:
    """Build IntentV1 from YAML data."""
    date_window = DateWindow(
        start=date.fromisoformat(intent_data["date_window"]["start"]),
        end=date.fromisoformat(intent_data["date_window"]["end"]),
        tz=intent_data["date_window"]["tz"],
    )
    prefs = Preferences(**intent_data["prefs"])
    return IntentV1(
        city=intent_data["city"],
        date_window=date_window,
        budget_usd_cents=intent_data["budget_usd_cents"],
        airports=intent_data["airports"],
        prefs=prefs,
    )


def build_stub_plan(intent: IntentV1) -> PlanV1:
    """Build minimal stub plan."""
    stub_provenance = Provenance(source="tool", fetched_at=datetime.now())
    stub_features = ChoiceFeatures(cost_usd_cents=10000, indoor=True)
    stub_choice = Choice(
        kind=ChoiceKind.attraction,
        option_ref="stub_attraction",
        features=stub_features,
        provenance=stub_provenance,
    )
    stub_slot = Slot(window=TimeWindow(start=time(10, 0), end=time(12, 0)), choices=[stub_choice])

    days: list[DayPlan] = []
    current_date = intent.date_window.start
    while current_date <= intent.date_window.end and len(days) < 7:
        days.append(DayPlan(date=current_date, slots=[stub_slot]))
        current_date = date.fromordinal(current_date.toordinal() + 1)

    if len(days) < 4:
        days = days[:4]

    assumptions = Assumptions(fx_rate_usd_eur=1.1, daily_spend_est_cents=5000)
    return PlanV1(days=days, assumptions=assumptions, rng_seed=42)


def build_stub_itinerary(intent: IntentV1, plan: PlanV1) -> ItineraryV1:
    """Build minimal stub itinerary."""
    stub_activity = Activity(
        window=TimeWindow(start=time(10, 0), end=time(12, 0)),
        kind=ChoiceKind.attraction,
        name="Stub Attraction",
        geo=Geo(lat=48.8566, lon=2.3522),
        notes="Stub activity",
        locked=False,
    )

    days = [DayItinerary(date=day.date, activities=[stub_activity]) for day in plan.days]

    cost_breakdown = CostBreakdown(
        flights_usd_cents=50000,
        lodging_usd_cents=80000,
        attractions_usd_cents=10000,
        transit_usd_cents=5000,
        daily_spend_usd_cents=len(days) * plan.assumptions.daily_spend_est_cents,
        total_usd_cents=50000 + 80000 + 10000 + 5000 + len(days) * 5000,
        currency_disclaimer="FX as-of 2025-06-01",
    )

    return ItineraryV1(
        itinerary_id="stub_itinerary_123",
        intent=intent,
        days=days,
        cost_breakdown=cost_breakdown,
        decisions=[
            Decision(node="planner", rationale="stub", alternatives_considered=1, selected="stub")
        ],
        citations=[
            Citation(claim="stub", provenance=Provenance(source="tool", fetched_at=datetime.now()))
        ],
        created_at=datetime.now(),
        trace_id="stub_trace_123",
    )


def evaluate_predicates(
    intent: IntentV1, plan: PlanV1, itinerary: ItineraryV1, predicates: list[dict[str, str]]
) -> tuple[int, int]:
    """Evaluate predicates; return (passed, total)."""
    passed = 0
    total = len(predicates)
    env = {"intent": intent, "plan": plan, "itinerary": itinerary, "len": len}

    for pred_data in predicates:
        predicate = pred_data["predicate"]
        description = pred_data.get("description", predicate)
        try:
            result = eval(predicate, {"__builtins__": {}}, env)
            if result:
                passed += 1
                print(f"  ✓ PASS: {description}")
            else:
                print(f"  ✗ FAIL: {description}")
        except Exception as e:
            print(f"  ✗ ERROR: {description} - {e}")

    return passed, total


def main() -> int:
    """Run eval scenarios."""
    scenarios_data = load_scenarios()
    scenarios = scenarios_data["scenarios"]

    total_passed = 0
    total_predicates = 0

    for scenario in scenarios:
        scenario_id = scenario["scenario_id"]
        description = scenario["description"]
        print(f"\n=== Scenario: {scenario_id} ===")
        print(f"Description: {description}")

        intent = build_intent_from_yaml(scenario["intent"])
        plan = build_stub_plan(intent)
        itinerary = build_stub_itinerary(intent, plan)

        predicates = scenario["must_satisfy"]
        passed, total = evaluate_predicates(intent, plan, itinerary, predicates)
        total_passed += passed
        total_predicates += total

        print(f"Result: {passed}/{total} predicates passed")

    print("\n=== Summary ===")
    print(f"Total: {total_passed}/{total_predicates} predicates passed")

    if total_passed < total_predicates:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
