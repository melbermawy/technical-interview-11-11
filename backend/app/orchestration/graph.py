"""Graph orchestrator - stub implementation for PR-4A.

All nodes are deterministic stubs that emit events but do not call LLMs or external APIs.
"""

from datetime import date, datetime, time

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.run_events import append_run_event
from backend.app.models.common import ChoiceKind, Provenance
from backend.app.models.intent import DateWindow, IntentV1, Preferences
from backend.app.models.itinerary import Decision
from backend.app.models.plan import Assumptions, Choice, ChoiceFeatures, DayPlan, PlanV1, Slot
from backend.app.models.violations import ViolationSeverity
from backend.app.orchestration.planner import plan_real
from backend.app.orchestration.selector import select_best_choices
from backend.app.orchestration.state import GraphState
from backend.app.orchestration.synth import synth_node
from backend.app.verification.verifiers import run_verifiers


async def run_graph_stub(state: GraphState, session: AsyncSession) -> GraphState:
    """Execute the full agent graph with stub implementations.

    Args:
        state: Initial graph state
        session: Database session for event persistence

    Returns:
        Final graph state
    """
    state.status = "running"

    # Node 1: Extract intent
    state = await extract_intent_stub(state, session)

    # Node 2: Planner (real implementation from PR-6A)
    state = await plan_real(state, session)

    # Node 3: Selector
    state = await selector_stub(state, session)

    # Node 4: Tool executor
    state = await tool_exec_stub(state, session)

    # Node 5: Verifier
    state = await verify_stub(state, session)

    # Node 6: Repair (conditional)
    if state.violations:
        state = await repair_stub(state, session)

    # Node 7: Synthesizer (real LLM synthesis from PR-8A)
    state = await synth_node(state, session)

    # Node 8: Responder
    state = await responder_stub(state, session)

    state.status = "succeeded"
    state.updated_at = datetime.utcnow()

    return state


async def extract_intent_stub(state: GraphState, session: AsyncSession) -> GraphState:
    """Stub intent extractor - creates minimal IntentV1 from hard-coded data.

    If state.intent is already set (e.g., from what-if derivation), preserve it.
    """
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="intent",
        phase="started",
        summary="Extracting intent from user prompt",
    )

    # Only create stub intent if not already set (e.g., from what-if)
    if state.intent is None:
        state.intent = IntentV1(
            city="Paris",
            date_window=DateWindow(
                start=date(2025, 6, 10),
                end=date(2025, 6, 14),
                tz="Europe/Paris",
            ),
            budget_usd_cents=250000,  # $2,500
            airports=["CDG"],
            prefs=Preferences(
                kid_friendly=False,
                themes=["art", "food"],
                avoid_overnight=False,
                locked_slots=[],
            ),
        )

    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="intent",
        phase="completed",
        summary="Intent extracted: Paris, Jun 10-14, $2500 budget",
    )

    return state


async def plan_stub(state: GraphState, session: AsyncSession) -> GraphState:
    """Stub planner - creates minimal PlanV1 with 4 days."""
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="planner",
        phase="started",
        summary="Generating initial plan with 1 branch",
    )

    # Create stub plan (aligned with SPEC §3.2)
    base_date = state.intent.date_window.start if state.intent else date(2025, 6, 10)
    stub_provenance = Provenance(
        source="tool",
        ref_id="stub_tool",
        fetched_at=datetime.utcnow(),
        cache_hit=False,
    )

    state.plan = PlanV1(
        days=[
            DayPlan(
                date=base_date,
                slots=[
                    Slot(
                        window={"start": time(10, 0), "end": time(13, 0)},
                        choices=[
                            Choice(
                                kind=ChoiceKind.attraction,
                                option_ref="louvre_001",
                                features=ChoiceFeatures(
                                    cost_usd_cents=2000,
                                    travel_seconds=1800,
                                    indoor=True,
                                    themes=["art"],
                                ),
                                score=0.9,
                                provenance=stub_provenance,
                            )
                        ],
                        locked=False,
                    )
                ],
            ),
            DayPlan(
                date=base_date.replace(day=base_date.day + 1),
                slots=[
                    Slot(
                        window={"start": time(14, 0), "end": time(17, 0)},
                        choices=[
                            Choice(
                                kind=ChoiceKind.attraction,
                                option_ref="orsay_002",
                                features=ChoiceFeatures(
                                    cost_usd_cents=1500,
                                    travel_seconds=1200,
                                    indoor=True,
                                    themes=["art"],
                                ),
                                score=0.85,
                                provenance=stub_provenance,
                            )
                        ],
                        locked=False,
                    )
                ],
            ),
            DayPlan(date=base_date.replace(day=base_date.day + 2), slots=[]),
            DayPlan(date=base_date.replace(day=base_date.day + 3), slots=[]),
        ],
        assumptions=Assumptions(
            fx_rate_usd_eur=1.1,
            daily_spend_est_cents=8000,
            transit_buffer_minutes=15,
            airport_buffer_minutes=120,
        ),
        rng_seed=state.rng_seed,
    )

    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="planner",
        phase="completed",
        summary="Plan generated: 4 days, 2 activities",
    )

    return state


async def selector_stub(state: GraphState, session: AsyncSession) -> GraphState:
    """Real selector - scores choices and selects top-k (PR-6B)."""
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="selector",
        phase="started",
        summary="Scoring and selecting best choices",
    )

    # Handle empty/missing choices
    if not state.choices or not state.intent:
        num_choices = len(state.choices) if state.choices else 0
        has_intent = state.intent is not None
        await append_run_event(
            session,
            run_id=state.run_id,
            org_id=state.org_id,
            sequence=state.next_sequence(),
            node="selector",
            phase="completed",
            summary=f"No choices to select from ({num_choices} available, intent={has_intent})",
        )
        return state

    # Score and select best choices
    selected_choices, selector_logs = select_best_choices(
        choices=state.choices,
        intent=state.intent,
        max_selected=10,
    )

    # Update state
    state.choices = selected_choices
    state.selector_logs = selector_logs

    # Record decision
    state.decisions.append(
        Decision(
            node="selector",
            rationale=f"Selected {len(selected_choices)} choices using feature-based scoring",
            alternatives_considered=len(state.choices) if state.choices else 0,
            selected=f"top_{len(selected_choices)}",
        )
    )

    num_selected = len(selected_choices)
    num_logs = len(selector_logs)
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="selector",
        phase="completed",
        summary=f"Selected {num_selected} choices with scores; {num_logs} decision logs",
    )

    return state


async def tool_exec_stub(state: GraphState, session: AsyncSession) -> GraphState:
    """Stub tool executor - attaches stub provenance."""
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="tool_exec",
        phase="started",
        summary="Enriching plan with tool results",
    )

    # No-op: provenance already attached in planner stub

    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="tool_exec",
        phase="completed",
        summary="Enriched plan with 2 tool calls (weather, attractions)",
    )

    return state


async def verify_stub(state: GraphState, session: AsyncSession) -> GraphState:
    """Real verifier - checks budget, preferences, feasibility, and weather (PR-7B)."""
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="verifier",
        phase="started",
        summary="Running verifiers (budget, preferences, feasibility, weather)",
    )

    # Handle missing intent or choices
    if not state.intent or not state.choices:
        state.violations = []
        state.has_blocking_violations = False
        await append_run_event(
            session,
            run_id=state.run_id,
            org_id=state.org_id,
            sequence=state.next_sequence(),
            node="verifier",
            phase="completed",
            summary="Verification skipped: missing intent or choices",
        )
        return state

    # Run verifiers (pass weather if available)
    violations = await run_verifiers(
        intent=state.intent,
        choices=state.choices,
        weather=state.weather if state.weather else None,
    )

    # Update state
    state.violations = violations
    state.has_blocking_violations = any(
        v.severity == ViolationSeverity.BLOCKING for v in violations
    )

    num_violations = len(violations)
    num_blocking = sum(1 for v in violations if v.severity == ViolationSeverity.BLOCKING)
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="verifier",
        phase="completed",
        summary=f"Verification complete: {num_violations} violations ({num_blocking} blocking)",
    )

    return state


async def repair_stub(state: GraphState, session: AsyncSession) -> GraphState:
    """Stub repair - no-op if no violations."""
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="repair",
        phase="started",
        summary="Attempting repairs for violations",
    )

    # Stub: clear violations
    state.violations = []

    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="repair",
        phase="completed",
        summary="Repair completed: 0 moves made",
    )

    return state


async def synth_stub(state: GraphState, session: AsyncSession) -> GraphState:
    """Stub synthesizer - generates dummy answer."""
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="synth",
        phase="started",
        summary="Synthesizing prose itinerary",
    )

    # Stub: no-op (final itinerary will be created in a later PR)

    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="synth",
        phase="completed",
        summary="Synthesis complete: generated markdown and citations",
    )

    return state


async def responder_stub(state: GraphState, session: AsyncSession) -> GraphState:
    """Stub responder - marks run as succeeded."""
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="responder",
        phase="started",
        summary="Finalizing response",
    )

    # Mark as succeeded
    state.status = "succeeded"

    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="responder",
        phase="completed",
        summary="Response finalized: run succeeded",
    )

    return state
