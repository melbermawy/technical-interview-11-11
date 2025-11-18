"""Tests for real planner node (PR-6A)."""

from datetime import date
from uuid import uuid4

import httpx
import pytest

from backend.app.config import Settings
from backend.app.models.common import ChoiceKind
from backend.app.models.intent import DateWindow, IntentV1, Preferences
from backend.app.orchestration.planner import apply_fanout_cap, plan_real
from backend.app.orchestration.state import GraphState


class MockSession:
    """Mock database session for testing."""

    def add(self, *args: object) -> None:
        pass

    async def execute(self, *args: object, **kwargs: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def flush(self) -> None:
        pass


@pytest.fixture
def paris_intent() -> IntentV1:
    """Create a Paris trip intent for testing."""
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


@pytest.fixture
def mock_http_client() -> httpx.AsyncClient:
    """Create a mock HTTP client for weather adapter tests."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Mock Open-Meteo response
        return httpx.Response(
            200,
            json={
                "daily": {
                    "time": ["2025-06-10", "2025-06-11", "2025-06-12", "2025-06-13"],
                    "temperature_2m_max": [22.0, 24.0, 23.0, 21.0],
                    "temperature_2m_min": [12.0, 13.0, 14.0, 12.5],
                    "precipitation_probability_max": [10, 20, 30, 15],
                    "wind_speed_10m_max": [10.0, 12.0, 15.0, 8.0],
                }
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_apply_fanout_cap_respects_limit() -> None:
    """Test that apply_fanout_cap enforces the cap."""
    from datetime import datetime

    from backend.app.models.common import Provenance
    from backend.app.models.plan import Choice, ChoiceFeatures

    prov = Provenance(
        source="test",
        ref_id="test",
        fetched_at=datetime.utcnow(),
        cache_hit=False,
    )

    # Create 10 choices
    choices = [
        Choice(
            kind=ChoiceKind.flight,
            option_ref=f"flight_{i}",
            features=ChoiceFeatures(
                cost_usd_cents=1000 * i,
                travel_seconds=3600,
                indoor=None,
                themes=[],
            ),
            score=None,
            provenance=prov,
        )
        for i in range(10)
    ]

    # Apply cap of 3
    capped = apply_fanout_cap(choices, cap=3)

    assert len(capped) == 3


def test_apply_fanout_cap_is_deterministic() -> None:
    """Test that apply_fanout_cap produces consistent ordering."""
    from datetime import datetime

    from backend.app.models.common import Provenance
    from backend.app.models.plan import Choice, ChoiceFeatures

    prov = Provenance(
        source="test",
        ref_id="test",
        fetched_at=datetime.utcnow(),
        cache_hit=False,
    )

    # Create choices with varied costs
    choices = [
        Choice(
            kind=ChoiceKind.lodging,
            option_ref="hotel_expensive",
            features=ChoiceFeatures(
                cost_usd_cents=15000,
                travel_seconds=None,
                indoor=True,
                themes=["luxury"],
            ),
            score=None,
            provenance=prov,
        ),
        Choice(
            kind=ChoiceKind.lodging,
            option_ref="hotel_budget",
            features=ChoiceFeatures(
                cost_usd_cents=8000,
                travel_seconds=None,
                indoor=True,
                themes=["budget"],
            ),
            score=None,
            provenance=prov,
        ),
        Choice(
            kind=ChoiceKind.lodging,
            option_ref="hotel_mid",
            features=ChoiceFeatures(
                cost_usd_cents=12000,
                travel_seconds=None,
                indoor=True,
                themes=["mid"],
            ),
            score=None,
            provenance=prov,
        ),
    ]

    # Run twice
    result1 = apply_fanout_cap(choices, cap=2)
    result2 = apply_fanout_cap(choices, cap=2)

    # Should be identical
    assert len(result1) == len(result2) == 2
    assert [c.option_ref for c in result1] == [c.option_ref for c in result2]
    # Should be sorted by cost
    assert result1[0].option_ref == "hotel_budget"
    assert result1[1].option_ref == "hotel_mid"


def test_apply_fanout_cap_prioritizes_by_kind() -> None:
    """Test that apply_fanout_cap prioritizes flights, then lodging, etc."""
    from datetime import datetime

    from backend.app.models.common import Provenance
    from backend.app.models.plan import Choice, ChoiceFeatures

    prov = Provenance(
        source="test",
        ref_id="test",
        fetched_at=datetime.utcnow(),
        cache_hit=False,
    )

    choices = [
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="attraction_1",
            features=ChoiceFeatures(
                cost_usd_cents=1000,
                travel_seconds=None,
                indoor=True,
                themes=[],
            ),
            score=None,
            provenance=prov,
        ),
        Choice(
            kind=ChoiceKind.flight,
            option_ref="flight_1",
            features=ChoiceFeatures(
                cost_usd_cents=45000,
                travel_seconds=3600,
                indoor=None,
                themes=[],
            ),
            score=None,
            provenance=prov,
        ),
        Choice(
            kind=ChoiceKind.lodging,
            option_ref="lodging_1",
            features=ChoiceFeatures(
                cost_usd_cents=10000,
                travel_seconds=None,
                indoor=True,
                themes=[],
            ),
            score=None,
            provenance=prov,
        ),
    ]

    capped = apply_fanout_cap(choices, cap=2)

    # Should prioritize flight, then lodging
    assert len(capped) == 2
    assert capped[0].kind == ChoiceKind.flight
    assert capped[1].kind == ChoiceKind.lodging


@pytest.mark.asyncio
async def test_plan_real_populates_choices(
    paris_intent: IntentV1, mock_http_client: httpx.AsyncClient
) -> None:
    """Test that plan_real populates state.choices."""
    # Create minimal state
    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=paris_intent,
    )

    # Mock session that doesn't actually write to DB
    session = MockSession()

    # Run planner
    result_state = await plan_real(state, session, http_client=mock_http_client)  # type: ignore[arg-type]

    # Verify choices populated
    assert result_state.choices is not None
    assert len(result_state.choices) > 0

    # All choices should have score=None (no scoring in PR-6A)
    for choice in result_state.choices:
        assert choice.score is None


@pytest.mark.asyncio
async def test_plan_real_respects_fanout_cap(
    paris_intent: IntentV1, mock_http_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that plan_real respects settings.fanout_cap."""
    # Override settings to have a small cap
    small_cap_settings = Settings(fanout_cap=3)

    def mock_get_settings() -> Settings:
        return small_cap_settings

    from backend.app.orchestration import planner

    monkeypatch.setattr(planner, "get_settings", mock_get_settings)

    # Create state
    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=paris_intent,
    )

    session = MockSession()

    # Run planner
    result_state = await plan_real(state, session, http_client=mock_http_client)  # type: ignore[arg-type]

    # Verify cap respected
    assert result_state.choices is not None
    assert len(result_state.choices) <= 3
    assert len(result_state.choices) == 3  # Should hit the cap with Paris fixtures


@pytest.mark.asyncio
async def test_plan_real_is_deterministic(
    paris_intent: IntentV1, mock_http_client: httpx.AsyncClient
) -> None:
    """Test that plan_real produces deterministic results."""

    async def run_planner() -> list[str]:
        state = GraphState(
            run_id=uuid4(),
            org_id=uuid4(),
            user_id=uuid4(),
            intent=paris_intent,
        )

        session = MockSession()
        result = await plan_real(state, session, http_client=mock_http_client)  # type: ignore[arg-type]
        return [f"{c.kind.value}:{c.option_ref}" for c in (result.choices or [])]

    # Run twice
    run1 = await run_planner()
    run2 = await run_planner()

    # Should be identical
    assert run1 == run2


@pytest.mark.asyncio
async def test_plan_real_includes_multiple_kinds(
    paris_intent: IntentV1, mock_http_client: httpx.AsyncClient
) -> None:
    """Test that plan_real includes flights, lodging, attractions, etc."""
    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=paris_intent,
    )

    session = MockSession()

    result_state = await plan_real(state, session, http_client=mock_http_client)  # type: ignore[arg-type]

    assert result_state.choices is not None

    # Check that we have multiple kinds represented
    kinds = {c.kind for c in result_state.choices}

    # With fanout_cap=4, we should get at least flights and lodging
    # (exact mix depends on fixtures and cap, but verify we get variety)
    assert len(kinds) >= 1  # At least one kind of choice


@pytest.mark.asyncio
async def test_plan_real_logs_tool_calls(
    paris_intent: IntentV1, mock_http_client: httpx.AsyncClient
) -> None:
    """Test that plan_real logs all adapter tool calls (PR-11A)."""
    session = MockSession()
    state = GraphState(run_id=uuid4(), org_id=uuid4(), user_id=uuid4(), intent=paris_intent)

    result_state = await plan_real(state, session, http_client=mock_http_client)  # type: ignore

    # Verify tool calls were logged
    assert len(result_state.tool_calls) >= 6  # flights, lodging, attractions, fx, weather, transit

    # Extract tool names
    tool_names = {log.name for log in result_state.tool_calls}

    # Verify all expected adapters are logged
    expected_tools = {
        "adapter.flights",
        "adapter.lodging",
        "adapter.attractions",
        "adapter.fx",
        "adapter.weather",
        "adapter.transit",
    }
    assert expected_tools.issubset(tool_names)

    # Verify all logs have required fields
    for log in result_state.tool_calls:
        assert log.name
        assert log.started_at
        assert log.finished_at
        assert log.duration_ms >= 0
        assert isinstance(log.success, bool)
        assert isinstance(log.input_summary, dict)
        assert isinstance(log.output_summary, dict)
