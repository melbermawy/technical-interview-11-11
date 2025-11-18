"""Document retrieval node - fetches relevant docs for LLM context (PR-10B)."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.run_events import append_run_event
from backend.app.docs.retriever import search_docs
from backend.app.orchestration.state import GraphState


async def docs_node(state: GraphState, session: AsyncSession) -> GraphState:
    """Retrieve relevant documents and populate state.doc_matches.

    Queries the document store using the user's prompt (from intent) and
    attaches the top matching chunks to state.doc_matches for LLM context.

    Args:
        state: Current graph state (must have intent)
        session: Database session

    Returns:
        Updated state with doc_matches populated
    """
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="docs",
        phase="started",
        summary="Retrieving relevant organization documents",
    )

    # Skip if no intent (shouldn't happen in normal flow)
    if not state.intent or not state.intent.city:
        state.doc_matches = []
        await append_run_event(
            session,
            run_id=state.run_id,
            org_id=state.org_id,
            sequence=state.next_sequence(),
            node="docs",
            phase="completed",
            summary="No intent available; skipping document retrieval",
        )
        return state

    # Build query from intent (use city + themes as search terms)
    query_parts = [state.intent.city]
    if state.intent.prefs and state.intent.prefs.themes:
        query_parts.extend(state.intent.prefs.themes)

    query = " ".join(query_parts)

    # Search docs
    matches = await search_docs(
        org_id=state.org_id,
        user_id=state.user_id,
        query=query,
        limit=5,  # Top 5 chunks
        session=session,
    )

    # Extract just the chunks (drop scores for now)
    state.doc_matches = [match.chunk for match in matches]

    num_matches = len(state.doc_matches)
    await append_run_event(
        session,
        run_id=state.run_id,
        org_id=state.org_id,
        sequence=state.next_sequence(),
        node="docs",
        phase="completed",
        summary=f"Retrieved {num_matches} relevant document chunks",
    )

    return state
