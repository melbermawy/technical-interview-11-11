"""Document endpoints - POST /docs, GET /docs, GET /docs/search (PR-10B)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.auth import get_current_context
from backend.app.db.context import RequestContext
from backend.app.db.engine import get_session
from backend.app.db.models import Doc as DocDB
from backend.app.docs.ingest import ingest_document
from backend.app.docs.retriever import search_docs
from backend.app.models.docs import DocChunk, UserDocument

router = APIRouter(prefix="/docs", tags=["docs"])


class CreateDocRequest(BaseModel):
    """Request body for POST /docs."""

    title: str = Field(..., min_length=1, max_length=200, description="Document title")
    text: str = Field(..., min_length=1, description="Raw document text")
    kind: str = Field(
        "other",
        pattern="^(policy|notes|itinerary|other)$",
        description="Document type",
    )


class CreateDocResponse(BaseModel):
    """Response for POST /docs."""

    doc_id: str
    title: str
    kind: str
    created_at: datetime


class DocListResponse(BaseModel):
    """Response for GET /docs."""

    docs: list[UserDocument]


class DocSearchMatch(BaseModel):
    """Single search result with chunk and score."""

    chunk: DocChunk
    score: float


class DocSearchResponse(BaseModel):
    """Response for GET /docs/search."""

    matches: list[DocSearchMatch]
    query: str


@router.post("", response_model=CreateDocResponse, status_code=status.HTTP_201_CREATED)
async def create_doc(
    request: CreateDocRequest,
    ctx: Annotated[RequestContext, Depends(get_current_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CreateDocResponse:
    """Create a new document with automatic chunking.

    Args:
        request: Document creation request
        ctx: Request context (org_id, user_id)
        session: Database session

    Returns:
        Created document metadata
    """
    # Ingest document (chunks + persists)
    doc = await ingest_document(
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        title=request.title,
        text=request.text,
        kind=request.kind,
        session=session,
    )

    return CreateDocResponse(
        doc_id=str(doc.doc_id),
        title=doc.title,
        kind=doc.kind,
        created_at=doc.created_at,
    )


@router.get("", response_model=DocListResponse)
async def list_docs(
    ctx: Annotated[RequestContext, Depends(get_current_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
    kind: Annotated[str | None, Query(pattern="^(policy|notes|itinerary|other)$")] = None,
) -> DocListResponse:
    """List all documents for the current org/user.

    Args:
        ctx: Request context (org_id, user_id)
        session: Database session
        kind: Optional filter by document kind

    Returns:
        List of documents (without chunks)
    """
    # Build query with tenancy
    query = select(DocDB).where(
        DocDB.org_id == ctx.org_id,
        DocDB.user_id == ctx.user_id,
    )

    # Apply kind filter if provided
    if kind:
        query = query.where(DocDB.kind == kind)

    # Sort by created_at desc (newest first)
    query = query.order_by(DocDB.created_at.desc())

    # Execute query
    result = await session.execute(query)
    docs = list(result.scalars().all())

    # Convert to domain models
    user_docs = [
        UserDocument(
            doc_id=doc.doc_id,
            org_id=doc.org_id,
            user_id=doc.user_id,
            title=doc.title,
            kind=doc.kind,
            created_at=doc.created_at,
        )
        for doc in docs
    ]

    return DocListResponse(docs=user_docs)


@router.get("/search", response_model=DocSearchResponse)
async def search_docs_endpoint(
    ctx: Annotated[RequestContext, Depends(get_current_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
    query: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> DocSearchResponse:
    """Search document chunks by query string.

    Args:
        ctx: Request context (org_id, user_id)
        session: Database session
        query: Search query string
        limit: Maximum number of results (default 5, max 20)

    Returns:
        Ranked list of matching chunks with scores
    """
    # Search using retriever
    matches = await search_docs(
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        query=query,
        limit=limit,
        session=session,
    )

    # Convert to response format
    search_matches = [
        DocSearchMatch(
            chunk=match.chunk,
            score=match.score,
        )
        for match in matches
    ]

    return DocSearchResponse(matches=search_matches, query=query)
