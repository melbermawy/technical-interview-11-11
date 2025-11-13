"""Violation models - constraint violations found during verification."""

from typing import Any

from pydantic import BaseModel

from backend.app.models.common import ViolationKind


class Violation(BaseModel):
    """A single constraint violation."""

    kind: ViolationKind
    node_ref: str
    details: dict[str, Any]
    blocking: bool
