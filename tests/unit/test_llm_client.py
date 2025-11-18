"""Tests for LLM client (PR-8A).

All tests are deterministic and do not make real network calls.
"""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.llm.client import (
    DeterministicStubClient,
    OpenAIClient,
    get_llm_client,
    synthesize_answer_with_openai,
)
from backend.app.models.common import ChoiceKind, Provenance
from backend.app.models.intent import DateWindow, IntentV1, Preferences
from backend.app.models.plan import Choice, ChoiceFeatures
from backend.app.models.violations import Violation, ViolationKind, ViolationSeverity


@pytest.fixture
def sample_intent() -> IntentV1:
    """Create sample intent for testing."""
    return IntentV1(
        city="Paris",
        date_window=DateWindow(
            start=date(2025, 6, 10),
            end=date(2025, 6, 14),
            tz="Europe/Paris",
        ),
        budget_usd_cents=100000,
        airports=["CDG"],
        prefs=Preferences(themes=["art", "food"]),
    )


@pytest.fixture
def sample_choices() -> list[Choice]:
    """Create sample choices for testing."""
    prov = Provenance(source="tool", ref_id="test_ref", fetched_at=datetime.utcnow())
    return [
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="louvre_001",
            features=ChoiceFeatures(
                cost_usd_cents=2000,
                themes=["art"],
            ),
            provenance=prov,
        ),
        Choice(
            kind=ChoiceKind.attraction,
            option_ref="restaurant_002",
            features=ChoiceFeatures(
                cost_usd_cents=5000,
                themes=["food"],
            ),
            provenance=prov,
        ),
    ]


@pytest.fixture
def sample_violations() -> list[Violation]:
    """Create sample violations for testing."""
    return [
        Violation(
            kind=ViolationKind.BUDGET,
            code="NEAR_BUDGET",
            message="Slightly over budget",
            severity=ViolationSeverity.ADVISORY,
            affected_choice_ids=["choice1"],
            details={"ratio": 1.1},
        )
    ]


@pytest.fixture
def sample_selector_logs() -> list[dict]:
    """Create sample selector logs for testing."""
    return [
        {"rationale": "Selected louvre due to high art score", "score": 0.9},
        {"rationale": "Selected restaurant for food theme", "score": 0.85},
    ]


@pytest.mark.asyncio
async def test_deterministic_stub_client_generates_answer(
    sample_intent: IntentV1,
    sample_choices: list[Choice],
    sample_violations: list[Violation],
    sample_selector_logs: list[dict],
) -> None:
    """Test that DeterministicStubClient generates deterministic answer."""
    client = DeterministicStubClient()

    answer = await client.synthesize_answer(
        intent=sample_intent,
        choices=sample_choices,
        violations=sample_violations,
        selector_logs=sample_selector_logs,
    )

    assert "Paris" in answer.answer_markdown
    assert "2 selected options" in answer.answer_markdown
    assert "1 constraint violation(s)" in answer.answer_markdown
    assert len(answer.decisions) == 2  # min(2 selector logs, 3)
    assert answer.synthesis_source == "stub"


@pytest.mark.asyncio
async def test_deterministic_stub_client_is_deterministic(
    sample_intent: IntentV1,
    sample_choices: list[Choice],
    sample_violations: list[Violation],
    sample_selector_logs: list[dict],
) -> None:
    """Test that DeterministicStubClient produces same output every time."""
    client = DeterministicStubClient()

    answer1 = await client.synthesize_answer(
        intent=sample_intent,
        choices=sample_choices,
        violations=sample_violations,
        selector_logs=sample_selector_logs,
    )

    answer2 = await client.synthesize_answer(
        intent=sample_intent,
        choices=sample_choices,
        violations=sample_violations,
        selector_logs=sample_selector_logs,
    )

    assert answer1.answer_markdown == answer2.answer_markdown
    assert answer1.decisions == answer2.decisions
    assert answer1.synthesis_source == "stub"
    assert answer2.synthesis_source == "stub"


@pytest.mark.asyncio
async def test_deterministic_stub_handles_empty_inputs() -> None:
    """Test that DeterministicStubClient handles empty inputs gracefully."""
    client = DeterministicStubClient()
    intent = IntentV1(
        city="TestCity",
        date_window=DateWindow(
            start=date(2025, 1, 1),
            end=date(2025, 1, 5),
            tz="UTC",
        ),
        budget_usd_cents=10000,
        airports=["XXX"],
        prefs=Preferences(),
    )

    answer = await client.synthesize_answer(
        intent=intent,
        choices=[],
        violations=[],
        selector_logs=[],
    )

    assert "TestCity" in answer.answer_markdown
    assert "0 selected options" in answer.answer_markdown
    assert "0 constraint violation(s)" in answer.answer_markdown
    assert len(answer.decisions) == 0
    assert answer.synthesis_source == "stub"


@pytest.mark.asyncio
async def test_openai_client_builds_context_correctly(
    sample_intent: IntentV1,
    sample_choices: list[Choice],
    sample_violations: list[Violation],
    sample_selector_logs: list[dict],
) -> None:
    """Test that OpenAIClient builds correct context string."""
    client = OpenAIClient(api_key="test_key")

    context = client._build_context(
        sample_intent,
        sample_choices,
        sample_violations,
        sample_selector_logs,
    )

    # Check intent section
    assert "## User Intent" in context
    assert "Paris" in context
    assert "2025-06-10" in context
    assert "$1000.00" in context
    assert "art, food" in context

    # Check choices section
    assert "## Selected Options" in context
    assert "attraction: louvre_001" in context
    assert "$20.00" in context  # 2000 cents
    assert "attraction: restaurant_002" in context
    assert "$50.00" in context  # 5000 cents

    # Check violations section
    assert "## Constraint Violations" in context
    assert "NEAR_BUDGET" in context
    assert "Slightly over budget" in context

    # Check decisions section
    assert "## Agent Decisions" in context
    assert "Selected louvre due to high art score" in context


@pytest.mark.asyncio
async def test_openai_client_extract_decisions(
    sample_selector_logs: list[dict],
) -> None:
    """Test that OpenAIClient extracts decisions from selector logs."""
    client = OpenAIClient(api_key="test_key")

    decisions = client._extract_decisions(sample_selector_logs)

    assert len(decisions) == 2
    assert "Selected louvre due to high art score" in decisions
    assert "Selected restaurant for food theme" in decisions


@pytest.mark.asyncio
async def test_openai_client_extract_decisions_handles_missing_rationale() -> None:
    """Test that _extract_decisions handles logs without rationale."""
    client = OpenAIClient(api_key="test_key")
    logs = [
        {"node": "selector", "selected": "option1"},
        {"rationale": "Good choice"},
    ]

    decisions = client._extract_decisions(logs)

    assert len(decisions) == 2
    assert "selector: selected option1" in decisions
    assert "Good choice" in decisions


@pytest.mark.asyncio
async def test_openai_client_calls_api_and_returns_answer(
    sample_intent: IntentV1,
    sample_choices: list[Choice],
    sample_violations: list[Violation],
    sample_selector_logs: list[dict],
) -> None:
    """Test that OpenAIClient calls API and returns answer (mocked)."""
    # Mock OpenAI client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "# Mocked LLM Response\n\nThis is a test."

    mock_openai_client = AsyncMock()
    mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

    client = OpenAIClient(api_key="test_key")
    client.client = mock_openai_client

    answer = await client.synthesize_answer(
        intent=sample_intent,
        choices=sample_choices,
        violations=sample_violations,
        selector_logs=sample_selector_logs,
    )

    # Verify API was called
    mock_openai_client.chat.completions.create.assert_called_once()

    # Verify response
    assert "Mocked LLM Response" in answer.answer_markdown
    assert len(answer.decisions) == 2
    assert answer.synthesis_source == "openai"


@pytest.mark.asyncio
async def test_openai_client_falls_back_to_stub_on_error(
    sample_intent: IntentV1,
    sample_choices: list[Choice],
    sample_violations: list[Violation],
    sample_selector_logs: list[dict],
) -> None:
    """Test that OpenAIClient falls back to stub when API call fails."""
    # Mock OpenAI client to raise exception
    mock_openai_client = AsyncMock()
    mock_openai_client.chat.completions.create = AsyncMock(side_effect=Exception("API error"))

    client = OpenAIClient(api_key="test_key")
    client.client = mock_openai_client

    answer = await client.synthesize_answer(
        intent=sample_intent,
        choices=sample_choices,
        violations=sample_violations,
        selector_logs=sample_selector_logs,
    )

    # Should get stub response
    assert "Paris" in answer.answer_markdown
    assert "placeholder itinerary" in answer.answer_markdown
    assert "stub response" in answer.answer_markdown
    assert answer.synthesis_source == "stub"


@pytest.mark.asyncio
async def test_get_llm_client_returns_stub_when_no_api_key() -> None:
    """Test that get_llm_client returns stub when no API key configured."""
    with patch("backend.app.llm.client.settings") as mock_settings:
        mock_settings.openai_api_key = None

        client = await get_llm_client()

        assert isinstance(client, DeterministicStubClient)


@pytest.mark.asyncio
async def test_get_llm_client_returns_openai_when_api_key_present() -> None:
    """Test that get_llm_client returns OpenAI client when key present."""
    from pydantic import SecretStr

    with patch("backend.app.llm.client.settings") as mock_settings:
        mock_settings.openai_api_key = SecretStr("test_key")
        mock_settings.openai_model = "gpt-4o-mini"

        client = await get_llm_client()

        assert isinstance(client, OpenAIClient)


@pytest.mark.asyncio
async def test_synthesize_answer_with_openai_entry_point(
    sample_intent: IntentV1,
    sample_choices: list[Choice],
    sample_violations: list[Violation],
    sample_selector_logs: list[dict],
) -> None:
    """Test synthesize_answer_with_openai entry point."""
    with patch("backend.app.llm.client.settings") as mock_settings:
        mock_settings.openai_api_key = None

        answer = await synthesize_answer_with_openai(
            intent=sample_intent,
            choices=sample_choices,
            violations=sample_violations,
            selector_logs=sample_selector_logs,
        )

        # Should get stub response (no API key)
        assert "Paris" in answer.answer_markdown
        assert isinstance(answer.answer_markdown, str)
        assert isinstance(answer.decisions, list)
        assert answer.synthesis_source == "stub"


@pytest.mark.asyncio
async def test_openai_client_handles_empty_response(
    sample_intent: IntentV1,
    sample_choices: list[Choice],
    sample_violations: list[Violation],
    sample_selector_logs: list[dict],
) -> None:
    """Test that OpenAIClient falls back to stub when API returns empty content."""
    # Mock OpenAI client to return empty response
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = ""

    mock_openai_client = AsyncMock()
    mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

    client = OpenAIClient(api_key="test_key")
    client.client = mock_openai_client

    # Capture log output
    with patch("backend.app.llm.client.logger") as mock_logger:
        answer = await client.synthesize_answer(
            intent=sample_intent,
            choices=sample_choices,
            violations=sample_violations,
            selector_logs=sample_selector_logs,
        )

        # Verify warning was logged
        mock_logger.warning.assert_called_with(
            "OpenAI returned empty response, using deterministic stub fallback"
        )

    # Should get stub response with stub marker
    assert "Paris" in answer.answer_markdown
    assert "placeholder itinerary" in answer.answer_markdown
    assert "stub response" in answer.answer_markdown
    assert answer.synthesis_source == "stub"


@pytest.mark.asyncio
async def test_openai_client_handles_none_response(
    sample_intent: IntentV1,
    sample_choices: list[Choice],
    sample_violations: list[Violation],
    sample_selector_logs: list[dict],
) -> None:
    """Test that OpenAIClient falls back to stub when API returns None content."""
    # Mock OpenAI client to return None response
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = None

    mock_openai_client = AsyncMock()
    mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

    client = OpenAIClient(api_key="test_key")
    client.client = mock_openai_client

    # Capture log output
    with patch("backend.app.llm.client.logger") as mock_logger:
        answer = await client.synthesize_answer(
            intent=sample_intent,
            choices=sample_choices,
            violations=sample_violations,
            selector_logs=sample_selector_logs,
        )

        # Verify warning was logged
        mock_logger.warning.assert_called_with(
            "OpenAI returned empty response, using deterministic stub fallback"
        )

    # Should get stub response with stub marker
    assert "Paris" in answer.answer_markdown
    assert "placeholder itinerary" in answer.answer_markdown
    assert answer.synthesis_source == "stub"


@pytest.mark.asyncio
async def test_openai_client_truncates_overlong_response(
    sample_intent: IntentV1,
    sample_choices: list[Choice],
    sample_violations: list[Violation],
    sample_selector_logs: list[dict],
) -> None:
    """Test that OpenAIClient truncates overlong responses and logs warning."""
    # Create response just over the 10000 char threshold
    overlong_content = "x" * 10001

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = overlong_content

    mock_openai_client = AsyncMock()
    mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

    client = OpenAIClient(api_key="test_key")
    client.client = mock_openai_client

    # Capture log output
    with patch("backend.app.llm.client.logger") as mock_logger:
        answer = await client.synthesize_answer(
            intent=sample_intent,
            choices=sample_choices,
            violations=sample_violations,
            selector_logs=sample_selector_logs,
        )

        # Verify warning was logged
        mock_logger.warning.assert_called_with(
            "OpenAI response unexpectedly large (10001 chars), truncating to 10000"
        )

    # Should be truncated to 10000 chars + truncation notice
    assert len(answer.answer_markdown) == 10000 + len("\n\n[Truncated]")
    assert answer.answer_markdown.endswith("[Truncated]")
    assert answer.synthesis_source == "openai"


@pytest.mark.asyncio
async def test_openai_client_logs_warning_on_error_fallback(
    sample_intent: IntentV1,
    sample_choices: list[Choice],
    sample_violations: list[Violation],
    sample_selector_logs: list[dict],
) -> None:
    """Test that OpenAIClient logs explicit warning when falling back to stub on error."""
    # Mock OpenAI client to raise exception
    mock_openai_client = AsyncMock()
    mock_openai_client.chat.completions.create = AsyncMock(
        side_effect=Exception("API connection failed")
    )

    client = OpenAIClient(api_key="test_key")
    client.client = mock_openai_client

    # Capture log output
    with patch("backend.app.llm.client.logger") as mock_logger:
        answer = await client.synthesize_answer(
            intent=sample_intent,
            choices=sample_choices,
            violations=sample_violations,
            selector_logs=sample_selector_logs,
        )

        # Verify both error and warning were logged
        mock_logger.error.assert_called_once()
        assert "API connection failed" in str(mock_logger.error.call_args)

        mock_logger.warning.assert_called_with(
            "Falling back to deterministic stub client for synthesis"
        )

    # Should get stub response
    assert answer.synthesis_source == "stub"
    assert "stub response" in answer.answer_markdown


@pytest.mark.asyncio
async def test_openai_client_system_prompt_includes_critical_constraints() -> None:
    """Test that system prompt includes CRITICAL CONSTRAINTS section."""
    client = OpenAIClient(api_key="test_key")

    system_prompt = client._build_system_prompt()

    # Verify CRITICAL CONSTRAINTS section exists
    assert "CRITICAL CONSTRAINTS:" in system_prompt
    assert "flights, lodging, attractions, and transit options" in system_prompt
    assert "Do NOT invent new places" in system_prompt
    assert "details not available" in system_prompt
    assert "Respect the stated budget" in system_prompt
    assert "use the exact amounts provided" in system_prompt
