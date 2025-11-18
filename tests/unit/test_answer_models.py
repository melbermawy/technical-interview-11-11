"""Tests for AnswerV1 and QAPlanResponse models (PR-8A)."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.app.models.answer import (
    AnswerV1,
    ItineraryDay,
    ItineraryDayItem,
    ItinerarySummary,
    QAPlanResponse,
    ToolUsageSummary,
)
from backend.app.models.common import Provenance
from backend.app.models.itinerary import Citation


def test_itinerary_day_item_valid() -> None:
    """Test that valid ItineraryDayItem can be created."""
    item = ItineraryDayItem(
        start="10:00",
        end="13:00",
        title="Louvre Museum",
        location="Rue de Rivoli, Paris",
        notes="Pre-booked; indoor; art theme",
    )

    assert item.start == "10:00"
    assert item.end == "13:00"
    assert item.title == "Louvre Museum"
    assert item.location == "Rue de Rivoli, Paris"
    assert item.notes == "Pre-booked; indoor; art theme"


def test_itinerary_day_item_minimal() -> None:
    """Test that ItineraryDayItem can be created with minimal fields."""
    item = ItineraryDayItem(
        start="10:00",
        end="13:00",
        title="Louvre Museum",
    )

    assert item.start == "10:00"
    assert item.end == "13:00"
    assert item.title == "Louvre Museum"
    assert item.location is None
    assert item.notes == ""


def test_itinerary_day_valid() -> None:
    """Test that valid ItineraryDay can be created."""
    day = ItineraryDay(
        date="2025-06-10",
        items=[
            ItineraryDayItem(
                start="10:00",
                end="13:00",
                title="Louvre Museum",
            )
        ],
    )

    assert day.date == "2025-06-10"
    assert len(day.items) == 1


def test_itinerary_summary_valid() -> None:
    """Test that valid ItinerarySummary can be created."""
    summary = ItinerarySummary(
        days=[
            ItineraryDay(
                date="2025-06-10",
                items=[
                    ItineraryDayItem(
                        start="10:00",
                        end="13:00",
                        title="Louvre Museum",
                    )
                ],
            )
        ],
        total_cost_usd=1850,
    )

    assert len(summary.days) == 1
    assert summary.total_cost_usd == 1850


def test_tool_usage_summary_valid() -> None:
    """Test that valid ToolUsageSummary can be created."""
    tool = ToolUsageSummary(
        name="weather",
        count=5,
        total_ms=1230,
    )

    assert tool.name == "weather"
    assert tool.count == 5
    assert tool.total_ms == 1230


def test_qa_plan_response_valid() -> None:
    """Test that valid QAPlanResponse can be created."""
    response = QAPlanResponse(
        answer_markdown="Your 5-day Paris itinerary includes...",
        itinerary=ItinerarySummary(
            days=[
                ItineraryDay(
                    date="2025-06-10",
                    items=[
                        ItineraryDayItem(
                            start="10:00",
                            end="13:00",
                            title="Louvre Museum",
                        )
                    ],
                )
            ],
            total_cost_usd=1850,
        ),
        citations=[
            Citation(
                claim="test",
                provenance=Provenance(source="tool", fetched_at=datetime.utcnow()),
            )
        ],
        tools_used=[
            ToolUsageSummary(name="weather", count=5, total_ms=1230),
        ],
        decisions=["Chose ITM over KIX due to shorter transfer time"],
    )

    assert "Paris itinerary" in response.answer_markdown
    assert len(response.itinerary.days) == 1
    assert len(response.citations) == 1
    assert len(response.tools_used) == 1
    assert len(response.decisions) == 1


def test_qa_plan_response_minimal() -> None:
    """Test that QAPlanResponse can be created with minimal fields."""
    response = QAPlanResponse(
        answer_markdown="Minimal answer",
        itinerary=ItinerarySummary(days=[], total_cost_usd=0),
    )

    assert response.answer_markdown == "Minimal answer"
    assert len(response.itinerary.days) == 0
    assert response.citations == []
    assert response.tools_used == []
    assert response.decisions == []


def test_qa_plan_response_missing_required_fields() -> None:
    """Test that QAPlanResponse fails validation when missing required fields."""
    with pytest.raises(ValidationError):
        QAPlanResponse()  # type: ignore[call-arg]


def test_answer_v1_valid() -> None:
    """Test that valid AnswerV1 can be created."""
    answer = AnswerV1(
        answer_markdown="# Paris Itinerary\n\nYour trip includes...",
        decisions=["Decision 1", "Decision 2"],
        synthesis_source="openai",
    )

    assert "Paris Itinerary" in answer.answer_markdown
    assert len(answer.decisions) == 2
    assert answer.synthesis_source == "openai"


def test_answer_v1_minimal() -> None:
    """Test that AnswerV1 can be created with minimal fields."""
    answer = AnswerV1(answer_markdown="Minimal markdown", synthesis_source="stub")

    assert answer.answer_markdown == "Minimal markdown"
    assert answer.decisions == []
    assert answer.synthesis_source == "stub"


def test_answer_v1_missing_required_field() -> None:
    """Test that AnswerV1 fails validation when missing required field."""
    with pytest.raises(ValidationError):
        AnswerV1()  # type: ignore[call-arg]


def test_answer_v1_roundtrip_json() -> None:
    """Test that AnswerV1 can be serialized and deserialized."""
    original = AnswerV1(
        answer_markdown="# Test\n\nContent here",
        decisions=["Decision 1"],
        synthesis_source="openai",
    )

    json_str = original.model_dump_json()
    restored = AnswerV1.model_validate_json(json_str)

    assert restored == original
    assert restored.answer_markdown == original.answer_markdown
    assert restored.decisions == original.decisions
    assert restored.synthesis_source == original.synthesis_source


def test_qa_plan_response_roundtrip_json() -> None:
    """Test that QAPlanResponse can be serialized and deserialized."""
    original = QAPlanResponse(
        answer_markdown="Test answer",
        itinerary=ItinerarySummary(
            days=[
                ItineraryDay(
                    date="2025-06-10",
                    items=[
                        ItineraryDayItem(
                            start="10:00",
                            end="13:00",
                            title="Test Activity",
                        )
                    ],
                )
            ],
            total_cost_usd=100,
        ),
        citations=[],
        tools_used=[],
        decisions=["Test decision"],
    )

    json_str = original.model_dump_json()
    restored = QAPlanResponse.model_validate_json(json_str)

    assert restored.answer_markdown == original.answer_markdown
    assert restored.itinerary.total_cost_usd == original.itinerary.total_cost_usd
    assert len(restored.decisions) == 1
