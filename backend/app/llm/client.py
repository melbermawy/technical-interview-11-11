"""LLM client for synthesis with OpenAI integration.

Security: Reads API key from environment only, never hardcoded.
Provides deterministic fallback when no key present for testing.
"""

import logging
from typing import Protocol

from openai import AsyncOpenAI

from backend.app.config import settings
from backend.app.models.answer import AnswerV1
from backend.app.models.docs import DocChunk
from backend.app.models.intent import IntentV1
from backend.app.models.plan import Choice
from backend.app.models.violations import Violation

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Protocol for LLM client implementations."""

    async def synthesize_answer(
        self,
        *,
        intent: IntentV1,
        choices: list[Choice],
        violations: list[Violation],
        selector_logs: list[dict[str, object]],
        doc_matches: list[DocChunk] | None = None,
    ) -> AnswerV1:
        """Generate natural language summary from graph state.

        Args:
            intent: User's travel intent
            choices: Selected options (flights, lodging, attractions, etc)
            violations: Constraint violations found during verification
            selector_logs: Decision logs from selector node
            doc_matches: Retrieved document chunks (PR-10B)

        Returns:
            AnswerV1 with markdown summary and extracted decisions
        """
        ...


class DeterministicStubClient:
    """Deterministic stub client for testing (no API key required)."""

    async def synthesize_answer(
        self,
        *,
        intent: IntentV1,
        choices: list[Choice],
        violations: list[Violation],
        selector_logs: list[dict[str, object]],
        doc_matches: list[DocChunk] | None = None,
    ) -> AnswerV1:
        """Generate deterministic stub answer."""
        city = intent.city
        num_choices = len(choices)
        num_violations = len(violations)

        # Extract decision count from selector logs
        num_decisions = len(selector_logs)

        answer_markdown = (
            f"# Travel Itinerary for {city}\n\n"
            f"This is a placeholder itinerary with {num_choices} selected options.\n\n"
            f"**Status**: {num_violations} constraint violation(s) detected.\n\n"
            f"*This is a stub response generated without LLM synthesis.*"
        )

        decisions = [f"Decision {i+1} (stub)" for i in range(min(num_decisions, 3))]

        return AnswerV1(
            answer_markdown=answer_markdown, decisions=decisions, synthesis_source="stub"
        )


class OpenAIClient:
    """OpenAI-backed LLM client for real synthesis."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        """Initialize OpenAI client.

        Args:
            api_key: OpenAI API key (read from environment)
            model: Model name to use (default: gpt-4o-mini for cost efficiency)
        """
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def synthesize_answer(
        self,
        *,
        intent: IntentV1,
        choices: list[Choice],
        violations: list[Violation],
        selector_logs: list[dict[str, object]],
        doc_matches: list[DocChunk] | None = None,
    ) -> AnswerV1:
        """Generate answer using OpenAI API."""
        # Build context for LLM
        context = self._build_context(intent, choices, violations, selector_logs, doc_matches)

        # Build system prompt
        system_prompt = self._build_system_prompt()

        try:
            # Call OpenAI API
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": context},
                ],
                temperature=0.7,
                max_tokens=2000,
            )

            # Extract answer markdown from response
            answer_markdown = response.choices[0].message.content or ""

            # Validation: Check for empty response
            if not answer_markdown.strip():
                logger.warning("OpenAI returned empty response, using deterministic stub fallback")
                stub = DeterministicStubClient()
                return await stub.synthesize_answer(
                    intent=intent,
                    choices=choices,
                    violations=violations,
                    selector_logs=selector_logs,
                    doc_matches=doc_matches,
                )

            # Validation: Check for unreasonably long response
            if len(answer_markdown) > 10000:
                logger.warning(
                    f"OpenAI response unexpectedly large ({len(answer_markdown)} chars), "
                    "truncating to 10000"
                )
                answer_markdown = answer_markdown[:10000] + "\n\n[Truncated]"

            # Extract decisions from selector logs
            decisions = self._extract_decisions(selector_logs)

            return AnswerV1(
                answer_markdown=answer_markdown,
                decisions=decisions,
                synthesis_source="openai",
            )

        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            logger.warning("Falling back to deterministic stub client for synthesis")
            # Fallback to stub on error
            stub = DeterministicStubClient()
            return await stub.synthesize_answer(
                intent=intent,
                choices=choices,
                violations=violations,
                selector_logs=selector_logs,
                doc_matches=doc_matches,
            )

    def _build_system_prompt(self) -> str:
        """Build system prompt for synthesis."""
        return """You are a travel itinerary assistant. Given structured data about a trip plan,
generate a natural language markdown summary that explains:

1. Overview of the trip (destination, dates, budget)
2. Key highlights and selected activities
3. Any constraint violations or warnings
4. Practical advice and recommendations

Format the response as markdown with clear sections. Be concise but informative.
Focus on what the traveler needs to know, not implementation details.

CRITICAL CONSTRAINTS:
- Only mention flights, lodging, attractions, and transit options that appear in the
  "Selected Options" section below.
- Do NOT invent new places, activities, flight times, hotel names, or details that are not
  present in the provided data.
- If information is missing (e.g., exact times, amenities), say "details not available"
  rather than guessing.
- Respect the stated budget and any listed constraint violations; do not casually recommend
  spending far beyond budget.
- When mentioning costs, use the exact amounts provided (e.g., "$99.50"), not rounded or
  approximate phrasing like "about $100".

ORGANIZATION DOCUMENTS:
- If an "Organization Docs" section appears below, these are official company policies or
  guidelines from the traveler's organization.
- You MUST respect and incorporate these policies into your recommendations. For example,
  if the org doc mentions "all flights must be economy class", ensure your itinerary
  complies with this requirement.
- When an org policy conflicts with the user's intent, acknowledge the conflict and explain
  how the itinerary respects the policy.
- Do NOT ignore or contradict organization policies."""

    def _build_context(
        self,
        intent: IntentV1,
        choices: list[Choice],
        violations: list[Violation],
        selector_logs: list[dict[str, object]],
        doc_matches: list[DocChunk] | None = None,
    ) -> str:
        """Build context string for LLM from graph state."""
        lines = []

        # Intent section
        lines.append("## User Intent")
        lines.append(f"- Destination: {intent.city}")
        lines.append(f"- Dates: {intent.date_window.start} to {intent.date_window.end}")
        lines.append(f"- Budget: ${intent.budget_usd_cents / 100:.2f} USD")
        if intent.prefs and intent.prefs.themes:
            lines.append(f"- Preferred themes: {', '.join(intent.prefs.themes)}")
        lines.append("")

        # Organization Docs section (PR-10B)
        if doc_matches:
            lines.append("## Organization Docs")
            lines.append("Relevant policies and guidelines from the traveler's organization:")
            lines.append("")
            for chunk in doc_matches:
                # Truncate long chunks for context efficiency
                chunk_preview = chunk.text if len(chunk.text) <= 300 else chunk.text[:297] + "..."
                lines.append(f"- {chunk_preview}")
            lines.append("")

        # Choices section
        lines.append("## Selected Options")
        if choices:
            for choice in choices[:20]:  # Limit for context size
                cost_str = (
                    f"${choice.features.cost_usd_cents / 100:.2f}"
                    if choice.features.cost_usd_cents
                    else "free"
                )
                themes_str = (
                    f" ({', '.join(choice.features.themes)})" if choice.features.themes else ""
                )
                lines.append(f"- {choice.kind.value}: {choice.option_ref} - {cost_str}{themes_str}")
        else:
            lines.append("- No choices selected")
        lines.append("")

        # Violations section
        lines.append("## Constraint Violations")
        if violations:
            for v in violations:
                lines.append(f"- [{v.severity.value}] {v.code}: {v.message}")
        else:
            lines.append("- No violations")
        lines.append("")

        # Decisions section (from selector logs)
        lines.append("## Agent Decisions")
        if selector_logs:
            for log in selector_logs[:10]:  # Limit for context size
                if "rationale" in log:
                    lines.append(f"- {log.get('rationale', 'N/A')}")
        else:
            lines.append("- No decision logs available")

        return "\n".join(lines)

    def _extract_decisions(self, selector_logs: list[dict[str, object]]) -> list[str]:
        """Extract human-readable decisions from selector logs."""
        decisions: list[str] = []
        for log in selector_logs[:10]:  # Limit to top 10
            if "rationale" in log:
                rationale = log["rationale"]
                if isinstance(rationale, str):
                    decisions.append(rationale)
            elif "node" in log and "selected" in log:
                decisions.append(f"{log['node']}: selected {log['selected']}")
        return decisions


async def get_llm_client() -> LLMClient:
    """Factory function to get appropriate LLM client based on config.

    Returns:
        OpenAIClient if API key is configured, DeterministicStubClient otherwise
    """
    api_key = settings.openai_api_key

    if api_key and api_key.get_secret_value():
        logger.info("Using OpenAI client for synthesis")
        return OpenAIClient(
            api_key=api_key.get_secret_value(),
            model=settings.openai_model,
        )
    else:
        logger.warning("No OpenAI API key configured, using deterministic stub client")
        return DeterministicStubClient()


async def synthesize_answer_with_openai(
    *,
    intent: IntentV1,
    choices: list[Choice],
    violations: list[Violation],
    selector_logs: list[dict[str, object]],
    doc_matches: list[DocChunk] | None = None,
) -> AnswerV1:
    """Main entry point for LLM synthesis.

    Args:
        intent: User's travel intent
        choices: Selected options
        violations: Constraint violations
        selector_logs: Decision logs
        doc_matches: Retrieved document chunks (PR-10B)

    Returns:
        AnswerV1 with synthesized answer
    """
    client = await get_llm_client()
    return await client.synthesize_answer(
        intent=intent,
        choices=choices,
        violations=violations,
        selector_logs=selector_logs,
        doc_matches=doc_matches,
    )
