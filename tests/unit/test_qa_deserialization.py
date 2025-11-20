"""Unit tests for GraphState deserialization helper (PR-13A)."""

import uuid

import pytest

from backend.app.api.routes.qa import deserialize_graph_state


def test_deserialize_graph_state_with_minimal_state() -> None:
    """Test deserializing GraphState with only required fields."""
    state_json = {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "org_id": "00000000-0000-0000-0000-000000000002",
        "user_id": "00000000-0000-0000-0000-000000000003",
    }

    state = deserialize_graph_state(state_json)

    # Verify UUIDs are parsed correctly
    assert state.run_id == uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert state.org_id == uuid.UUID("00000000-0000-0000-0000-000000000002")
    assert state.user_id == uuid.UUID("00000000-0000-0000-0000-000000000003")

    # Verify optional fields have defaults
    assert state.intent is None
    assert state.answer is None
    assert state.plan is None
    assert state.choices == []
    assert state.weather == []
    assert state.violations == []
    assert state.decisions == []
    assert state.citations == []
    assert state.doc_matches == []
    assert state.tool_calls == []
    assert state.has_blocking_violations is False
    assert state.rng_seed == 42
    assert state.sequence_counter == 0
    assert state.status == "succeeded"


def test_deserialize_graph_state_with_complete_state() -> None:
    """Test deserializing GraphState with all fields populated."""
    state_json = {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "org_id": "00000000-0000-0000-0000-000000000002",
        "user_id": "00000000-0000-0000-0000-000000000003",
        "intent": {
            "city": "Paris",
            "date_window": {
                "start": "2025-06-10",
                "end": "2025-06-14",
                "tz": "Europe/Paris",
            },
            "budget_usd_cents": 100000,
            "airports": ["CDG"],
            "prefs": {"themes": ["art"]},
        },
        "answer": {
            "answer_markdown": "Test answer",
            "decisions": ["Decision 1"],
            "synthesis_source": "stub",
        },
        "plan": {
            "days": [
                {"date": "2025-06-10", "slots": []},
                {"date": "2025-06-11", "slots": []},
                {"date": "2025-06-12", "slots": []},
                {"date": "2025-06-13", "slots": []},
            ],
            "assumptions": {
                "fx_rate_usd_eur": 1.1,
                "daily_spend_est_cents": 10000,
            },
            "rng_seed": 42,
        },
        "choices": [
            {
                "kind": "flight",
                "option_ref": "flight_1",
                "features": {
                    "cost_usd_cents": 50000,
                    "travel_seconds": 3600,
                },
                "score": 0.9,
                "provenance": {
                    "source": "adapter.flights",
                    "fetched_at": "2025-01-01T00:00:00Z",
                },
            }
        ],
        "weather": [
            {
                "date": "2025-06-10",
                "temp_c_high": 24.0,
                "temp_c_low": 15.0,
                "precip_prob": 0.1,
                "wind_kmh": 10.0,
                "provenance": {
                    "source": "weather.api",
                    "fetched_at": "2025-01-01T00:00:00Z",
                },
            }
        ],
        "violations": [
            {
                "kind": "budget",
                "code": "OVER_BUDGET",
                "message": "Budget exceeded",
                "severity": "blocking",
                "affected_choice_ids": ["flight_1"],
                "details": {},
            }
        ],
        "has_blocking_violations": True,
        "decisions": [
            {
                "node": "selector",
                "rationale": "Best price",
                "alternatives_considered": 3,
                "selected": "flight_1",
            }
        ],
        "selector_logs": [{"step": "log1"}, {"step": "log2"}],
        "citations": [
            {
                "claim": "Flight to Paris",
                "provenance": {
                    "source": "adapter.flights",
                    "fetched_at": "2025-01-01T00:00:00Z",
                },
            }
        ],
        "doc_matches": [
            {
                "chunk_id": "00000000-0000-0000-0000-000000000004",
                "doc_id": "00000000-0000-0000-0000-000000000005",
                "text": "Paris is beautiful",
                "order": 0,
                "section_label": "Intro",
            }
        ],
        "tool_calls": [
            {
                "name": "adapter.flights",
                "started_at": "2025-01-01T00:00:00Z",
                "finished_at": "2025-01-01T00:00:01Z",
                "duration_ms": 100,
                "success": True,
            }
        ],
        "rng_seed": 999,
        "sequence_counter": 10,
        "status": "succeeded",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:01:00Z",
    }

    state = deserialize_graph_state(state_json)

    # Verify core fields
    assert state.run_id == uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert state.org_id == uuid.UUID("00000000-0000-0000-0000-000000000002")
    assert state.user_id == uuid.UUID("00000000-0000-0000-0000-000000000003")

    # Verify Pydantic models are reconstructed
    assert state.intent is not None
    assert state.intent.city == "Paris"
    assert state.intent.budget_usd_cents == 100000

    assert state.answer is not None
    assert state.answer.answer_markdown == "Test answer"
    assert state.answer.decisions == ["Decision 1"]

    assert state.plan is not None
    assert len(state.plan.days) == 4
    assert state.plan.assumptions.daily_spend_est_cents == 10000

    # Verify lists are reconstructed
    assert state.choices is not None
    assert len(state.choices) == 1
    assert state.choices[0].option_ref == "flight_1"

    assert len(state.weather) == 1
    assert state.weather[0].temp_c_high == 24.0

    assert len(state.violations) == 1
    assert state.violations[0].code == "OVER_BUDGET"
    assert state.has_blocking_violations is True

    assert len(state.decisions) == 1
    assert state.decisions[0].selected == "flight_1"

    assert len(state.selector_logs) == 2

    assert len(state.citations) == 1
    assert state.citations[0].claim == "Flight to Paris"

    assert len(state.doc_matches) == 1
    assert state.doc_matches[0].text == "Paris is beautiful"

    assert len(state.tool_calls) == 1
    assert state.tool_calls[0].name == "adapter.flights"

    # Verify other fields
    assert state.rng_seed == 999
    assert state.sequence_counter == 10
    assert state.status == "succeeded"
    # Verify datetime fields are parsed correctly
    from datetime import datetime, timezone

    assert isinstance(state.created_at, datetime)
    assert isinstance(state.updated_at, datetime)


def test_deserialize_graph_state_raises_on_missing_required_field() -> None:
    """Test that deserialization raises ValueError when required fields are missing."""
    # Missing org_id
    state_json = {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "user_id": "00000000-0000-0000-0000-000000000003",
    }

    with pytest.raises(ValueError, match="Failed to deserialize GraphState"):
        deserialize_graph_state(state_json)


def test_deserialize_graph_state_raises_on_invalid_uuid() -> None:
    """Test that deserialization raises ValueError for invalid UUID format."""
    state_json = {
        "run_id": "not-a-valid-uuid",
        "org_id": "00000000-0000-0000-0000-000000000002",
        "user_id": "00000000-0000-0000-0000-000000000003",
    }

    with pytest.raises(ValueError, match="Failed to deserialize GraphState"):
        deserialize_graph_state(state_json)


def test_deserialize_graph_state_raises_on_invalid_pydantic_model() -> None:
    """Test that deserialization raises ValueError for invalid Pydantic model data."""
    state_json = {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "org_id": "00000000-0000-0000-0000-000000000002",
        "user_id": "00000000-0000-0000-0000-000000000003",
        "intent": {
            "city": "Paris",
            # Missing required fields: date_window, budget_usd_cents, airports
        },
    }

    with pytest.raises(ValueError, match="Failed to deserialize GraphState"):
        deserialize_graph_state(state_json)


def test_deserialize_graph_state_raises_on_invalid_list_item() -> None:
    """Test that deserialization raises ValueError for invalid list item."""
    state_json = {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "org_id": "00000000-0000-0000-0000-000000000002",
        "user_id": "00000000-0000-0000-0000-000000000003",
        "choices": [
            {
                "kind": "flight",
                # Missing required fields: option_ref, features, provenance
            }
        ],
    }

    with pytest.raises(ValueError, match="Failed to deserialize GraphState"):
        deserialize_graph_state(state_json)


def test_deserialize_graph_state_handles_none_values() -> None:
    """Test that deserialization handles explicit None values correctly."""
    state_json = {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "org_id": "00000000-0000-0000-0000-000000000002",
        "user_id": "00000000-0000-0000-0000-000000000003",
        "intent": None,
        "answer": None,
        "plan": None,
    }

    state = deserialize_graph_state(state_json)

    assert state.intent is None
    assert state.answer is None
    assert state.plan is None
