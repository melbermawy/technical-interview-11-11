"""Document ingestion - persist docs and chunks (PR-10A)."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Doc
from backend.app.db.models import DocChunk as DocChunkDB
from backend.app.docs.chunker import chunk_document
from backend.app.models.docs import UserDocument


async def ingest_document(
    *,
    org_id: UUID,
    user_id: UUID,
    title: str,
    text: str,
    kind: str = "other",
    session: AsyncSession,
) -> UserDocument:
    """Ingest a document: chunk it and persist to database.

    Creates a Doc row and associated DocChunk rows in a single transaction.
    Returns domain model (UserDocument), not ORM instance.

    Args:
        org_id: Organization ID for tenancy
        user_id: User ID for tenancy
        title: Document title
        text: Raw document text to chunk
        kind: Document type (policy, notes, itinerary, other)
        session: Async database session

    Returns:
        UserDocument with doc_id and metadata
    """
    # Generate doc_id
    doc_id = uuid4()
    created_at = datetime.utcnow()

    # Chunk the document
    chunks = chunk_document(text)

    # Create Doc row
    doc = Doc(
        doc_id=doc_id,
        org_id=org_id,
        user_id=user_id,
        title=title,
        kind=kind,
        created_at=created_at,
    )
    session.add(doc)

    # Create DocChunk rows
    for order, chunk_text in chunks:
        chunk = DocChunkDB(
            chunk_id=uuid4(),
            doc_id=doc_id,
            order=order,
            text=chunk_text,
            section_label=None,
        )
        session.add(chunk)

    # Commit transaction
    await session.commit()

    # Return domain model
    return UserDocument(
        doc_id=doc_id,
        org_id=org_id,
        user_id=user_id,
        title=title,
        kind=kind,
        created_at=created_at,
    )
