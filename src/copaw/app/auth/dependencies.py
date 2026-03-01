# -*- coding: utf-8 -*-
"""FastAPI dependency helpers for route-level scope enforcement.

Usage::

    from copaw.app.auth.dependencies import require_scope

    @router.post("/tokens")
    async def create_token(
        actor: Actor = Depends(require_scope(TokenScope.OWNER)),
    ):
        ...
"""

from fastapi import Depends, HTTPException, Request

from .models import Actor, TokenScope, scope_rank


def require_scope(minimum: TokenScope):
    """Return a FastAPI dependency that enforces a minimum scope level.

    Raises 403 if the actor's scope is insufficient.
    """

    def _check(request: Request) -> Actor:
        actor: Actor = getattr(request.state, "actor", None)
        if actor is None:
            raise HTTPException(status_code=401, detail="Not authenticated")

        if scope_rank(actor.scope) < scope_rank(minimum):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient scope: requires {minimum.value}",
            )
        return actor

    return Depends(_check)
