"""Response models for /qa/plan endpoint (SPEC §9 Final Response Contract)."""

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from backend.app.models.itinerary import Citation

if TYPE_CHECKING:
    from backend.app.orchestration.state import GraphState


class ItineraryDayItem(BaseModel):
    """Single item in a day's itinerary."""

    start: str = Field(..., description="Start time in HH:MM format (local time)")
    end: str = Field(..., description="End time in HH:MM format (local time)")
    title: str = Field(..., description="Activity name")
    location: str | None = Field(None, description="Address or venue name")
    notes: str = Field("", description="Additional context (themes, indoor/outdoor, etc)")


class ItineraryDay(BaseModel):
    """Single day in the itinerary."""

    date: str = Field(..., description="ISO 8601 date string (YYYY-MM-DD)")
    items: list[ItineraryDayItem] = Field(default_factory=list)


class ItinerarySummary(BaseModel):
    """Simplified itinerary for /qa/plan response."""

    days: list[ItineraryDay]
    total_cost_usd: int = Field(..., description="Total cost in USD (not cents)")


class ToolUsageSummary(BaseModel):
    """Summary of tool invocations."""

    name: str = Field(..., description="Tool name")
    count: int = Field(..., description="Number of calls")
    total_ms: int = Field(..., description="Cumulative latency in milliseconds")


class QAPlanResponse(BaseModel):
    """External response contract for /qa/plan endpoint (SPEC §9).

    This is the strict, versioned API contract returned to clients.
    """

    answer_markdown: str = Field(..., description="Human-readable prose summary of the itinerary")
    itinerary: ItinerarySummary = Field(..., description="Simplified itinerary structure")
    citations: list[Citation] = Field(
        default_factory=list, description="Citations linking claims to provenance"
    )
    tools_used: list[ToolUsageSummary] = Field(
        default_factory=list, description="Summary of tool invocations"
    )
    decisions: list[str] = Field(
        default_factory=list,
        description="Human-readable rationales for key agent choices",
    )


class AnswerV1(BaseModel):
    """Internal synthesis output from LLM synth node.

    This is the internal representation that gets stored in GraphState.
    It contains the markdown answer that will be wrapped into QAPlanResponse.
    """

    answer_markdown: str = Field(..., description="LLM-generated markdown summary of the itinerary")
    decisions: list[str] = Field(
        default_factory=list,
        description="LLM-extracted decision rationales from selector logs",
    )
    synthesis_source: Literal["openai", "stub"] = Field(
        ..., description="Source of synthesis: 'openai' for real LLM, 'stub' for fallback"
    )


def build_tools_used_from_state(state: "GraphState") -> list[ToolUsageSummary]:
    """Build tools_used from GraphState.tool_calls (PR-11B).

    This is a pure aggregation function with no side effects.
    Groups tool calls by name and computes count and total_ms.

    Args:
        state: GraphState with tool_calls populated

    Returns:
        List of ToolUsageSummary, sorted by name (deterministic)
    """
    from backend.app.orchestration.state import GraphState

    if not isinstance(state, GraphState):
        raise TypeError(f"Expected GraphState, got {type(state)}")

    # Handle empty or None tool_calls
    if not state.tool_calls:
        return []

    # Group by tool name
    tool_groups: dict[str, list[int]] = {}
    for log in state.tool_calls:
        if log.name not in tool_groups:
            tool_groups[log.name] = []
        # Append duration, treating None as 0
        duration = log.duration_ms if log.duration_ms is not None else 0
        tool_groups[log.name].append(duration)

    # Build ToolUsageSummary list
    tools_used = [
        ToolUsageSummary(
            name=name,
            count=len(durations),
            total_ms=sum(durations),
        )
        for name, durations in tool_groups.items()
    ]

    # Sort by name for determinism
    tools_used.sort(key=lambda t: t.name)

    return tools_used


def build_qa_plan_response_from_state(state: "GraphState") -> QAPlanResponse:
    """Map GraphState to QAPlanResponse for /qa/plan endpoint.

    This is a pure, deterministic mapping function with no I/O.

    Args:
        state: Final graph state after orchestrator execution

    Returns:
        QAPlanResponse with all fields populated from state

    Raises:
        ValueError: If state.answer is None (graph should guarantee this)
    """
    from backend.app.orchestration.state import GraphState

    if not isinstance(state, GraphState):
        raise TypeError(f"Expected GraphState, got {type(state)}")

    if state.answer is None:
        raise ValueError("state.answer must not be None - synth node should populate it")

    # 1. answer_markdown and decisions come directly from AnswerV1
    answer_markdown = state.answer.answer_markdown
    decisions = state.answer.decisions

    # 2. citations come directly from state (already extracted from provenance)
    citations = state.citations

    # 3. Build itinerary from choices
    choices = state.choices or []

    # Calculate total cost in USD (convert from cents)
    total_cost_usd_cents = sum(choice.features.cost_usd_cents for choice in choices)
    total_cost_usd = total_cost_usd_cents // 100

    # Build days list - minimal implementation
    # For now, create a single day with all choices if we have dates
    days: list[ItineraryDay] = []
    if choices and state.intent and state.intent.date_window:
        # Use the first date as the representative day
        date_str = state.intent.date_window.start.isoformat()

        # Convert choices to itinerary items (minimal mapping)
        items: list[ItineraryDayItem] = []
        for choice in choices:
            # Use choice kind and ref as title
            title = f"{choice.kind.value}: {choice.option_ref}"

            # Minimal time allocation (stub)
            items.append(
                ItineraryDayItem(
                    start="09:00",  # Stub time
                    end="10:00",  # Stub time
                    title=title,
                    location=None,
                    notes="",
                )
            )

        if items:
            days.append(ItineraryDay(date=date_str, items=items))

    itinerary = ItinerarySummary(days=days, total_cost_usd=total_cost_usd)

    # 4. Build tools_used from GraphState.tool_calls (PR-11B)
    tools_used = build_tools_used_from_state(state)

    return QAPlanResponse(
        answer_markdown=answer_markdown,
        itinerary=itinerary,
        citations=citations,
        tools_used=tools_used,
        decisions=decisions,
    )
