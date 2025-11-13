"""Tests for tenancy enforcement."""

import uuid
from datetime import date, datetime

from backend.app.db.context import RequestContext
from backend.app.db.inmemory import InMemoryItineraryRepository, InMemoryRunRepository
from backend.app.models.intent import DateWindow, IntentV1, Preferences
from backend.app.models.itinerary import (
    CostBreakdown,
    DayItinerary,
    ItineraryV1,
)


def test_run_repository_tenancy_isolation() -> None:
    """Test that RunRepository enforces org/user isolation."""
    repo = InMemoryRunRepository()

    # Create two orgs
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    user_a1 = uuid.uuid4()
    user_b1 = uuid.uuid4()

    ctx_a = RequestContext(org_id=org_a, user_id=user_a1)
    ctx_b = RequestContext(org_id=org_b, user_id=user_b1)

    # Create intent
    intent = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=300000,
        airports=["CDG"],
        prefs=Preferences(),
    )

    # Create runs for both orgs
    run_a = repo.create_run(intent, ctx_a)
    run_b = repo.create_run(intent, ctx_b)

    # org_a can only see its own run
    record_a = repo.get_run(run_a, ctx_a)
    assert record_a is not None
    assert record_a.org_id == org_a
    assert record_a.user_id == user_a1

    # org_a cannot see org_b's run
    record_cross = repo.get_run(run_b, ctx_a)
    assert record_cross is None

    # org_b can see its own run
    record_b = repo.get_run(run_b, ctx_b)
    assert record_b is not None
    assert record_b.org_id == org_b
    assert record_b.user_id == user_b1

    # org_b cannot see org_a's run
    record_cross_2 = repo.get_run(run_a, ctx_b)
    assert record_cross_2 is None


def test_itinerary_repository_tenancy_isolation() -> None:
    """Test that ItineraryRepository enforces org/user isolation."""
    repo = InMemoryItineraryRepository()

    # Create two orgs
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    user_a1 = uuid.uuid4()
    user_b1 = uuid.uuid4()

    ctx_a = RequestContext(org_id=org_a, user_id=user_a1)
    ctx_b = RequestContext(org_id=org_b, user_id=user_b1)

    # Create stub itinerary
    intent = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=300000,
        airports=["CDG"],
        prefs=Preferences(),
    )

    itinerary = ItineraryV1(
        itinerary_id=str(uuid.uuid4()),
        intent=intent,
        days=[
            DayItinerary(date=date(2025, 6, 10), activities=[]),
        ],
        cost_breakdown=CostBreakdown(
            flights_usd_cents=60000,
            lodging_usd_cents=80000,
            attractions_usd_cents=10000,
            transit_usd_cents=5000,
            daily_spend_usd_cents=10000,
            total_usd_cents=165000,
            currency_disclaimer="FX as-of 2025-06-01",
        ),
        decisions=[],
        citations=[],
        created_at=datetime.now(),
        trace_id="test-trace",
    )

    # Create itineraries for both orgs
    run_a = uuid.uuid4()
    run_b = uuid.uuid4()
    itin_a = repo.save_itinerary(run_a, itinerary, ctx_a)
    itin_b = repo.save_itinerary(run_b, itinerary, ctx_b)

    # org_a can only see its own itinerary
    result_a = repo.get_itinerary(itin_a, ctx_a)
    assert result_a is not None
    assert result_a.intent.city == "Paris"

    # org_a cannot see org_b's itinerary
    result_cross = repo.get_itinerary(itin_b, ctx_a)
    assert result_cross is None

    # org_b can see its own itinerary
    result_b = repo.get_itinerary(itin_b, ctx_b)
    assert result_b is not None

    # org_b cannot see org_a's itinerary
    result_cross_2 = repo.get_itinerary(itin_a, ctx_b)
    assert result_cross_2 is None


def test_list_itineraries_tenancy_isolation() -> None:
    """Test that list_recent_itineraries only returns org/user data."""
    repo = InMemoryItineraryRepository()

    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    user_a1 = uuid.uuid4()
    user_b1 = uuid.uuid4()

    ctx_a = RequestContext(org_id=org_a, user_id=user_a1)
    ctx_b = RequestContext(org_id=org_b, user_id=user_b1)

    # Create intent
    intent = IntentV1(
        city="Paris",
        date_window=DateWindow(start=date(2025, 6, 10), end=date(2025, 6, 14), tz="Europe/Paris"),
        budget_usd_cents=300000,
        airports=["CDG"],
        prefs=Preferences(),
    )

    itinerary = ItineraryV1(
        itinerary_id=str(uuid.uuid4()),
        intent=intent,
        days=[DayItinerary(date=date(2025, 6, 10), activities=[])],
        cost_breakdown=CostBreakdown(
            flights_usd_cents=60000,
            lodging_usd_cents=80000,
            attractions_usd_cents=10000,
            transit_usd_cents=5000,
            daily_spend_usd_cents=10000,
            total_usd_cents=165000,
            currency_disclaimer="FX as-of 2025-06-01",
        ),
        decisions=[],
        citations=[],
        created_at=datetime.now(),
        trace_id="test-trace",
    )

    # Create 3 itineraries for org_a, 2 for org_b
    for _ in range(3):
        repo.save_itinerary(uuid.uuid4(), itinerary, ctx_a)

    for _ in range(2):
        repo.save_itinerary(uuid.uuid4(), itinerary, ctx_b)

    # org_a sees only its 3
    list_a = repo.list_recent_itineraries(ctx_a, limit=10)
    assert len(list_a) == 3

    # org_b sees only its 2
    list_b = repo.list_recent_itineraries(ctx_b, limit=10)
    assert len(list_b) == 2
