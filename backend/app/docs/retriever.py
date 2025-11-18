"""Document retriever - search chunks by query (PR-10A)."""

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import DocChunk as DocChunkDB
from backend.app.models.docs import DocChunk


class DocChunkMatch(BaseModel):
    """Document chunk with relevance score."""

    chunk: DocChunk
    score: float


async def search_docs(
    *,
    org_id: UUID,
    user_id: UUID,
    query: str,
    limit: int = 5,
    session: AsyncSession,
) -> list[DocChunkMatch]:
    """Search document chunks by query with simple token matching.

    Scoring strategy:
    - Tokenize query on spaces (lowercase)
    - For each chunk, count how many query tokens appear as substrings
    - Filter out chunks with score = 0
    - Sort by score descending, then by chunk order (for determinism)
    - Apply limit

    Args:
        org_id: Organization ID for tenancy filtering
        user_id: User ID for tenancy filtering
        query: Search query string
        limit: Maximum number of results to return
        session: Async database session

    Returns:
        List of DocChunkMatch sorted by relevance (descending score)
    """
    # Tokenize query
    query_lower = query.lower()
    query_tokens = [token.strip() for token in query_lower.split() if token.strip()]

    if not query_tokens:
        return []

    # Fetch all chunks for this org/user (enforce tenancy at DB level)
    stmt = (
        select(DocChunkDB)
        .join(DocChunkDB.doc)
        .where(
            DocChunkDB.doc.has(org_id=org_id),
            DocChunkDB.doc.has(user_id=user_id),
        )
    )

    result = await session.execute(stmt)
    db_chunks = list(result.scalars().all())

    # Score each chunk
    scored_chunks: list[tuple[DocChunkDB, float]] = []

    for db_chunk in db_chunks:
        chunk_text_lower = db_chunk.text.lower()

        # Count how many query tokens appear in chunk text
        match_count = sum(1 for token in query_tokens if token in chunk_text_lower)

        if match_count > 0:
            scored_chunks.append((db_chunk, float(match_count)))

    # Sort by score descending, then by order for tie-breaking (deterministic)
    scored_chunks.sort(key=lambda x: (-x[1], x[0].order))

    # Apply limit
    scored_chunks = scored_chunks[:limit]

    # Convert to domain models
    matches: list[DocChunkMatch] = []
    for db_chunk, score in scored_chunks:
        chunk = DocChunk(
            chunk_id=db_chunk.chunk_id,
            doc_id=db_chunk.doc_id,
            order=db_chunk.order,
            text=db_chunk.text,
            section_label=db_chunk.section_label,
        )
        matches.append(DocChunkMatch(chunk=chunk, score=score))

    return matches
