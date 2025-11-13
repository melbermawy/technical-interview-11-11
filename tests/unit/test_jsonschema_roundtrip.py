"""Test JSON schema export and roundtrip validation."""

import json
import subprocess
from datetime import date, datetime, time
from pathlib import Path

import pytest

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


@pytest.fixture(scope="module", autouse=True)
def export_schemas() -> None:
    """Export schemas before running tests."""
    result = subprocess.run(["python", "scripts/export_schemas.py"], capture_output=True, text=True)
    assert result.returncode == 0, f"Schema export failed: {result.stderr}"


def test_schemas_exist() -> None:
    """Test that schema files were created."""
    assert Path("docs/schemas/PlanV1.schema.json").exists()
    assert Path("docs/schemas/ItineraryV1.schema.json").exists()


def test_plan_schema_has_title() -> None:
    """Test that PlanV1 schema has title."""
    with open("docs/schemas/PlanV1.schema.json") as f:
        schema = json.load(f)
    assert "title" in schema
    assert schema["title"] == "PlanV1"


def test_itinerary_schema_has_title() -> None:
    """Test that ItineraryV1 schema has title."""
    with open("docs/schemas/ItineraryV1.schema.json") as f:
        schema = json.load(f)
    assert "title" in schema
    assert schema["title"] == "ItineraryV1"


def test_plan_valid_sample_passes() -> None:
    """Test that valid PlanV1 sample validates against schema."""
    stub_prov = Provenance(source="tool", fetched_at=datetime.now())
    stub_features = ChoiceFeatures(cost_usd_cents=1000)
    stub_choice = Choice(
        kind=ChoiceKind.attraction,
        option_ref="stub",
        features=stub_features,
        provenance=stub_prov,
    )
    stub_slot = Slot(window=TimeWindow(start=time(10, 0), end=time(12, 0)), choices=[stub_choice])

    days = [DayPlan(date=date(2025, 6, 10), slots=[stub_slot]) for _ in range(4)]
    assumptions = Assumptions(fx_rate_usd_eur=1.1, daily_spend_est_cents=5000)
    plan = PlanV1(days=days, assumptions=assumptions, rng_seed=42)

    # Serialize and deserialize
    json_str = plan.model_dump_json()
    restored = PlanV1.model_validate_json(json_str)
    assert restored == plan


def test_plan_invalid_type_fails() -> None:
    """Test that invalid PlanV1 sample fails validation."""
    stub_prov = Provenance(source="tool", fetched_at=datetime.now())
    stub_features = ChoiceFeatures(cost_usd_cents=1000)
    stub_choice = Choice(
        kind=ChoiceKind.attraction,
        option_ref="stub",
        features=stub_features,
        provenance=stub_prov,
    )
    stub_slot = Slot(window=TimeWindow(start=time(10, 0), end=time(12, 0)), choices=[stub_choice])

    days = [DayPlan(date=date(2025, 6, 10), slots=[stub_slot]) for _ in range(4)]
    assumptions = Assumptions(fx_rate_usd_eur=1.1, daily_spend_est_cents=5000)
    plan = PlanV1(days=days, assumptions=assumptions, rng_seed=42)

    # Mutate to invalid type
    data = plan.model_dump()
    data["rng_seed"] = "invalid_string"  # Should be int

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PlanV1(**data)


def test_itinerary_valid_sample_passes() -> None:
    """Test that valid ItineraryV1 sample validates against schema."""
    stub_activity = Activity(
        window=TimeWindow(start=time(10, 0), end=time(12, 0)),
        kind=ChoiceKind.attraction,
        name="Test Museum",
        geo=Geo(lat=48.8566, lon=2.3522),
        notes="Test notes",
        locked=False,
    )

    intent = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=300000,
        airports=["CDG"],
        prefs=Preferences(),
    )

    days = [DayItinerary(date=date(2025, 6, 10), activities=[stub_activity]) for _ in range(4)]

    cost_breakdown = CostBreakdown(
        flights_usd_cents=50000,
        lodging_usd_cents=80000,
        attractions_usd_cents=10000,
        transit_usd_cents=5000,
        daily_spend_usd_cents=20000,
        total_usd_cents=165000,
        currency_disclaimer="FX as-of 2025-06-01",
    )

    itinerary = ItineraryV1(
        itinerary_id="test_123",
        intent=intent,
        days=days,
        cost_breakdown=cost_breakdown,
        decisions=[],
        citations=[
            Citation(claim="test", provenance=Provenance(source="tool", fetched_at=datetime.now()))
        ],
        created_at=datetime.now(),
        trace_id="trace_123",
    )

    # Serialize and deserialize
    json_str = itinerary.model_dump_json()
    restored = ItineraryV1.model_validate_json(json_str)
    assert restored.itinerary_id == itinerary.itinerary_id
