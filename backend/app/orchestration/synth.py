"""Synthesis node - generates natural language summary using LLM."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.citations.extract import extract_citations_from_choices
from backend.app.db.run_events import append_run_event
from backend.app.llm.client import synthesize_answer_with_openai
from backend.app.orchestration.state import GraphState

logger = logging.getLogger(__name__)


async def synth_node(state: GraphState, session: AsyncSession) -> GraphState:
    """Synthesis node: Generate natural language summary from graph state.

    Takes:
    - intent: User's travel requirements
    - choices: Selected options from selector + tool_exec
    - violations: Constraint violations from verifier
    - selector_logs: Decision logs from selector

    Produces:
    - answer: AnswerV1 with markdown summary and decisions
    - citations: List of citations extracted from provenance

    Args:
        state: Current graph state
        session: Database session for event persistence

    Returns:
        Updated graph state with answer and citations populated
    """
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="synth",
        phase="started",
        summary="Synthesizing prose itinerary with LLM",
    )

    logger.info(f"[synth_node] run_id={state.run_id}")

    # Validate required state
    if not state.intent:
        logger.warning("[synth_node] No intent in state, skipping synthesis")
        await append_run_event(
            session,
            run_id=state.run_id,
            org_id=state.org_id,
            sequence=state.next_sequence(),
            node="synth",
            phase="completed",
            summary="Synthesis skipped: no intent",
        )
        return state

    if not state.choices:
        logger.warning("[synth_node] No choices in state, skipping synthesis")
        await append_run_event(
            session,
            run_id=state.run_id,
            org_id=state.org_id,
            sequence=state.next_sequence(),
            node="synth",
            phase="completed",
            summary="Synthesis skipped: no choices",
        )
        return state

    # Call LLM client to generate answer (with doc_matches from PR-10B)
    answer = await synthesize_answer_with_openai(
        intent=state.intent,
        choices=state.choices,
        violations=state.violations,
        selector_logs=state.selector_logs,
        doc_matches=state.doc_matches if state.doc_matches else None,
    )

    # Extract citations from choice provenance
    citations = extract_citations_from_choices(state.choices)

    # Update state
    state.answer = answer
    state.citations = citations

    logger.info(
        f"[synth_node] Generated answer ({len(answer.answer_markdown)} chars, "
        f"{len(citations)} citations, {len(answer.decisions)} decisions)"
    )

    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="synth",
        phase="completed",
        summary=(
            f"Synthesis complete: {len(citations)} citations, " f"{len(answer.decisions)} decisions"
        ),
    )

    return state
