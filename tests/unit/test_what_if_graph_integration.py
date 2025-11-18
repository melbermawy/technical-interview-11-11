"""Unit tests for what-if intent preservation through graph execution (PR-9A bug fix)."""

from datetime import date
from uuid import UUID

import pytest

from backend.app.models.intent import DateWindow, IntentV1, Preferences
from backend.app.orchestration.graph import extract_intent_stub
from backend.app.orchestration.state import GraphState


@pytest.mark.asyncio
async def test_extract_intent_stub_preserves_existing_intent() -> None:
    """Test that extract_intent_stub preserves intent if already set (what-if scenario)."""
    # Create a what-if derived intent (different from default stub)
    derived_intent = IntentV1(
        city="Tokyo",
        date_window=DateWindow(start=date(2025, 7, 1), end=date(2025, 7, 5), tz="Asia/Tokyo"),
        budget_usd_cents=300000,  # $3000, different from stub's $2500
        airports=["NRT"],
        prefs=Preferences(themes=["temples", "food"]),
    )

    # Create state with pre-populated intent (as what-if endpoint does)
    state = GraphState(
        run_id=UUID("00000000-0000-0000-0000-000000000999"),
        org_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        sequence_counter=1,
        intent=derived_intent,  # Pre-populated
    )

    # Mock session (not used by stub but required)
    from unittest.mock import AsyncMock

    mock_session = AsyncMock()

    # Run extract_intent_stub
    result_state = await extract_intent_stub(state, mock_session)

    # Verify intent was preserved, not overwritten
    assert result_state.intent is not None
    assert result_state.intent.city == "Tokyo"  # Not "Paris" (stub default)
    assert result_state.intent.budget_usd_cents == 300000  # Not 250000
    assert result_state.intent.airports == ["NRT"]  # Not ["CDG"]
    assert result_state.intent.prefs is not None
    assert result_state.intent.prefs.themes == ["temples", "food"]  # Not ["art", "food"]


@pytest.mark.asyncio
async def test_extract_intent_stub_creates_default_when_none() -> None:
    """Test that extract_intent_stub creates default intent when none exists."""
    # Create state with no intent (normal flow)
    state = GraphState(
        run_id=UUID("00000000-0000-0000-0000-000000000999"),
        org_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        sequence_counter=1,
        intent=None,  # No pre-populated intent
    )

    # Mock session
    from unittest.mock import AsyncMock

    mock_session = AsyncMock()

    # Run extract_intent_stub
    result_state = await extract_intent_stub(state, mock_session)

    # Verify default stub intent was created
    assert result_state.intent is not None
    assert result_state.intent.city == "Paris"
    assert result_state.intent.budget_usd_cents == 250000
    assert result_state.intent.airports == ["CDG"]
    assert result_state.intent.prefs is not None
    assert result_state.intent.prefs.themes == ["art", "food"]
