"""Tests for synth_node integration (PR-8A)."""

from datetime import date, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from backend.app.models.answer import AnswerV1
from backend.app.models.common import ChoiceKind, Provenance
from backend.app.models.intent import DateWindow, IntentV1, Preferences
from backend.app.models.plan import Choice, ChoiceFeatures
from backend.app.orchestration.state import GraphState
from backend.app.orchestration.synth import synth_node


@pytest.fixture
def base_state() -> GraphState:
    """Create base GraphState for testing."""
    return GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10),
                end=date(2025, 6, 14),
                tz="Europe/Paris",
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(themes=["art"]),
        ),
        choices=[
            Choice(
                kind=ChoiceKind.attraction,
                option_ref="louvre_001",
                features=ChoiceFeatures(cost_usd_cents=2000, themes=["art"]),
                provenance=Provenance(
                    source="tool",
                    ref_id="louvre_001",
                    fetched_at=datetime.utcnow(),
                ),
            )
        ],
    )


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create mock database session."""
    session = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_synth_node_populates_answer_and_citations(
    base_state: GraphState,
    mock_session: AsyncMock,
) -> None:
    """Test that synth_node populates answer and citations in state."""
    # Mock LLM client to return deterministic answer
    mock_answer = AnswerV1(
        answer_markdown="# Paris Itinerary\n\nTest content",
        decisions=["Decision 1"],
        synthesis_source="openai",
    )

    with patch("backend.app.orchestration.synth.synthesize_answer_with_openai") as mock_synth:
        mock_synth.return_value = mock_answer

        result_state = await synth_node(base_state, mock_session)

        # Verify answer was set
        assert result_state.answer is not None
        assert result_state.answer.answer_markdown == "# Paris Itinerary\n\nTest content"
        assert len(result_state.answer.decisions) == 1
        assert result_state.answer.synthesis_source == "openai"

        # Verify citations were extracted
        assert len(result_state.citations) > 0


@pytest.mark.asyncio
async def test_synth_node_extracts_citations_from_choices(
    base_state: GraphState,
    mock_session: AsyncMock,
) -> None:
    """Test that synth_node correctly extracts citations from choice provenance."""
    # Add multiple choices with different provenance
    base_state.choices = [
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="louvre_001",
            features=ChoiceFeatures(cost_usd_cents=2000),
            provenance=Provenance(
                source="tool",
                ref_id="louvre_001",
                fetched_at=datetime.utcnow(),
            ),
        ),
        Choice(
            kind=ChoiceKind.lodging,
            option_ref="hotel_002",
            features=ChoiceFeatures(cost_usd_cents=15000),
            provenance=Provenance(
                source="manual",
                ref_id="hotel_002",
                fetched_at=datetime.utcnow(),
            ),
        ),
    ]

    mock_answer = AnswerV1(
        answer_markdown="Test",
        decisions=[],
        synthesis_source="stub",
    )

    with patch("backend.app.orchestration.synth.synthesize_answer_with_openai") as mock_synth:
        mock_synth.return_value = mock_answer

        result_state = await synth_node(base_state, mock_session)

        # Should have 2 citations (one per choice with unique provenance)
        assert len(result_state.citations) == 2

        # Verify citation sources
        sources = {c.provenance.source for c in result_state.citations}
        assert sources == {"tool", "manual"}


@pytest.mark.asyncio
async def test_synth_node_calls_llm_with_correct_params(
    base_state: GraphState,
    mock_session: AsyncMock,
) -> None:
    """Test that synth_node calls LLM with correct parameters."""
    base_state.violations = []
    base_state.selector_logs = [{"rationale": "Test decision"}]

    mock_answer = AnswerV1(answer_markdown="Test", decisions=[], synthesis_source="openai")

    with patch("backend.app.orchestration.synth.synthesize_answer_with_openai") as mock_synth:
        mock_synth.return_value = mock_answer

        await synth_node(base_state, mock_session)

        # Verify LLM was called with correct arguments
        mock_synth.assert_called_once_with(
            intent=base_state.intent,
            choices=base_state.choices,
            violations=base_state.violations,
            selector_logs=base_state.selector_logs,
        )


@pytest.mark.asyncio
async def test_synth_node_skips_when_no_intent(
    mock_session: AsyncMock,
) -> None:
    """Test that synth_node skips processing when intent is missing."""
    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=None,  # No intent
        choices=[
            Choice(
                kind=ChoiceKind.attraction,
                option_ref="test",
                features=ChoiceFeatures(cost_usd_cents=1000),
                provenance=Provenance(source="tool", fetched_at=datetime.utcnow()),
            )
        ],
    )

    result_state = await synth_node(state, mock_session)

    # Should not populate answer or citations
    assert result_state.answer is None
    assert result_state.citations == []


@pytest.mark.asyncio
async def test_synth_node_skips_when_no_choices(
    mock_session: AsyncMock,
) -> None:
    """Test that synth_node skips processing when choices are missing."""
    state = GraphState(
        run_id=uuid4(),
        org_id=uuid4(),
        user_id=uuid4(),
        intent=IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10),
                end=date(2025, 6, 14),
                tz="Europe/Paris",
            ),
            budget_usd_cents=100000,
            airports=["CDG"],
            prefs=Preferences(),
        ),
        choices=None,  # No choices
    )

    result_state = await synth_node(state, mock_session)

    # Should not populate answer or citations
    assert result_state.answer is None
    assert result_state.citations == []


@pytest.mark.asyncio
async def test_synth_node_emits_run_events(
    base_state: GraphState,
    mock_session: AsyncMock,
) -> None:
    """Test that synth_node emits run events."""
    mock_answer = AnswerV1(answer_markdown="Test", decisions=[], synthesis_source="openai")

    with patch("backend.app.orchestration.synth.synthesize_answer_with_openai") as mock_synth:
        with patch("backend.app.orchestration.synth.append_run_event") as mock_append_event:
            mock_synth.return_value = mock_answer

            await synth_node(base_state, mock_session)

            # Should emit at least 2 events (started + completed)
            assert mock_append_event.call_count >= 2

            # Check started event
            started_call = mock_append_event.call_args_list[0]
            assert started_call[1]["node"] == "synth"
            assert started_call[1]["phase"] == "started"

            # Check completed event
            completed_call = mock_append_event.call_args_list[-1]
            assert completed_call[1]["node"] == "synth"
            assert completed_call[1]["phase"] == "completed"


@pytest.mark.asyncio
async def test_synth_node_handles_empty_violations_and_logs(
    base_state: GraphState,
    mock_session: AsyncMock,
) -> None:
    """Test that synth_node handles empty violations and selector logs."""
    base_state.violations = []
    base_state.selector_logs = []

    mock_answer = AnswerV1(answer_markdown="Test", decisions=[], synthesis_source="stub")

    with patch("backend.app.orchestration.synth.synthesize_answer_with_openai") as mock_synth:
        mock_synth.return_value = mock_answer

        result_state = await synth_node(base_state, mock_session)

        # Should still populate answer
        assert result_state.answer is not None

        # LLM should be called with empty lists
        mock_synth.assert_called_once_with(
            intent=base_state.intent,
            choices=base_state.choices,
            violations=[],
            selector_logs=[],
        )


@pytest.mark.asyncio
async def test_synth_node_preserves_existing_state(
    base_state: GraphState,
    mock_session: AsyncMock,
) -> None:
    """Test that synth_node preserves existing state fields."""
    # Set some existing state
    base_state.rng_seed = 123
    base_state.sequence_counter = 5

    mock_answer = AnswerV1(answer_markdown="Test", decisions=[], synthesis_source="openai")

    with patch("backend.app.orchestration.synth.synthesize_answer_with_openai") as mock_synth:
        mock_synth.return_value = mock_answer

        result_state = await synth_node(base_state, mock_session)

        # Should preserve existing fields
        assert result_state.rng_seed == 123
        assert result_state.run_id == base_state.run_id
        assert result_state.org_id == base_state.org_id
        assert result_state.intent == base_state.intent


@pytest.mark.asyncio
async def test_synth_node_deduplicates_citations(
    base_state: GraphState,
    mock_session: AsyncMock,
) -> None:
    """Test that synth_node deduplicates citations from duplicate provenance."""
    # Add choices with duplicate provenance
    base_state.choices = [
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="louvre_001",
            features=ChoiceFeatures(cost_usd_cents=2000),
            provenance=Provenance(
                source="tool",
                ref_id="same_ref",
                fetched_at=datetime.utcnow(),
            ),
        ),
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="louvre_002",
            features=ChoiceFeatures(cost_usd_cents=3000),
            provenance=Provenance(
                source="tool",
                ref_id="same_ref",  # Same source + ref_id
                fetched_at=datetime.utcnow(),
            ),
        ),
    ]

    mock_answer = AnswerV1(answer_markdown="Test", decisions=[], synthesis_source="stub")

    with patch("backend.app.orchestration.synth.synthesize_answer_with_openai") as mock_synth:
        mock_synth.return_value = mock_answer

        result_state = await synth_node(base_state, mock_session)

        # Should only have 1 citation (deduplicated by source+ref_id)
        assert len(result_state.citations) == 1
