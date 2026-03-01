# -*- coding: utf-8 -*-
"""FastAPI routes for token management (requires owner scope)."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .models import Actor, TokenScope, scope_rank
from .store import TokenStore

router = APIRouter(prefix="/auth/tokens", tags=["auth"])


def _get_store(request: Request) -> TokenStore:
    return request.app.state.token_store


def _require_owner(request: Request) -> Actor:
    """Enforce owner scope for token management routes."""
    actor: Actor = getattr(request.state, "actor", None)
    if actor is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if scope_rank(actor.scope) < scope_rank(TokenScope.OWNER):
        raise HTTPException(status_code=403, detail="Requires owner scope")
    return actor


class CreateTokenRequest(BaseModel):
    scope: str = Field(default="viewer", description="owner, collaborator, or viewer")
    label: str = Field(default="", description="Optional label")


class TokenInfo(BaseModel):
    id: str
    scope: str
    label: str
    created_at: str


@router.post("")
async def create_token(body: CreateTokenRequest, request: Request):
    """Create a new API token. Returns the plaintext token (shown once)."""
    _require_owner(request)
    store = _get_store(request)

    try:
        token_scope = TokenScope(body.scope)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scope: {body.scope}. Use owner, collaborator, or viewer.",
        )

    plaintext = store.create(scope=token_scope, label=body.label)
    return {
        "token": plaintext,
        "scope": token_scope.value,
        "label": body.label,
        "message": "Save this token — it will not be shown again.",
    }


@router.get("")
async def list_tokens(request: Request):
    """List all tokens (without hashes)."""
    _require_owner(request)
    store = _get_store(request)
    tokens = store.list_tokens()
    return {
        "tokens": [
            TokenInfo(
                id=t.id,
                scope=t.scope.value,
                label=t.label,
                created_at=datetime.fromtimestamp(t.created_at).isoformat(),
            ).model_dump()
            for t in tokens
        ],
    }


@router.delete("/{token_id}")
async def revoke_token(token_id: str, request: Request):
    """Revoke (delete) a token by ID."""
    _require_owner(request)
    store = _get_store(request)
    ok = store.revoke(token_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"status": "revoked", "id": token_id}
