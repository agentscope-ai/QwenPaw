# -*- coding: utf-8 -*-
"""Data models for the token authentication system."""

import enum
import time
import uuid
from typing import Optional

from pydantic import BaseModel, Field


class TokenScope(str, enum.Enum):
    """Permission levels (ordered: owner > collaborator > viewer)."""

    OWNER = "owner"
    COLLABORATOR = "collaborator"
    VIEWER = "viewer"


# Numeric ranking for scope comparison.
_SCOPE_RANK = {
    TokenScope.VIEWER: 1,
    TokenScope.COLLABORATOR: 2,
    TokenScope.OWNER: 3,
}


def scope_rank(scope: TokenScope) -> int:
    """Return numeric rank for a scope (higher = more permissions)."""
    return _SCOPE_RANK.get(scope, 0)


class TokenRecord(BaseModel):
    """A single token record stored in tokens.json.

    The ``hash`` field stores the SHA-256 digest of the token value;
    the plaintext token is never persisted.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    hash: str = Field(..., description="SHA-256 hex digest of the token")
    scope: TokenScope = TokenScope.VIEWER
    label: str = Field(default="", description="Optional human-readable label")
    created_at: float = Field(default_factory=time.time)


class Actor(BaseModel):
    """Represents the authenticated caller injected into request.state."""

    token_id: Optional[str] = None
    scope: TokenScope = TokenScope.OWNER
    is_anonymous: bool = False
