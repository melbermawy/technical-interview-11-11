"""Document domain models (PR-10A)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class UserDocument(BaseModel):
    """User document metadata."""

    doc_id: UUID
    org_id: UUID
    user_id: UUID
    title: str
    kind: Literal["policy", "notes", "itinerary", "other"] = "other"
    created_at: datetime


class DocChunk(BaseModel):
    """Document chunk with text content."""

    chunk_id: UUID
    doc_id: UUID
    order: int  # 0-based
    text: str
    section_label: str | None = None
