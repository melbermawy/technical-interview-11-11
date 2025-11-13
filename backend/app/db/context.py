"""Request context for tenancy enforcement."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class RequestContext:
    """Request context containing org and user identity.

    Used to enforce tenancy boundaries in all database operations.
    """

    org_id: UUID
    user_id: UUID
