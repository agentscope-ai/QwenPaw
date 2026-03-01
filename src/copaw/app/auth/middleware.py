# -*- coding: utf-8 -*-
"""FastAPI middleware for Bearer token authentication.

When auth is enabled, extracts the token from the ``Authorization``
header and injects an :class:`Actor` into ``request.state.actor``.

When auth is disabled (default), all requests get an anonymous
owner-level actor.
"""

import logging
import re
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .models import Actor, TokenScope
from .store import TokenStore

logger = logging.getLogger(__name__)

_BEARER_RE = re.compile(r"^Bearer\s+(.+)$", re.IGNORECASE)

# Paths that never require authentication.
_PUBLIC_PATHS = frozenset({
    "/",
    "/api/version",
    "/logo.png",
    "/copaw-symbol.svg",
})


def _is_public(path: str) -> bool:
    """Check if a path is public (no auth required)."""
    if path in _PUBLIC_PATHS:
        return True
    # Static assets are always public.
    if path.startswith("/assets/"):
        return True
    return False


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Validates Bearer tokens and injects ``request.state.actor``.

    Args:
        app: The ASGI application.
        token_store: TokenStore instance for token verification.
        enabled: If False, all requests are treated as owner.
    """

    def __init__(self, app, token_store: TokenStore, enabled: bool = False):
        super().__init__(app)
        self._store = token_store
        self._enabled = enabled

    async def dispatch(self, request: Request, call_next) -> Response:
        # Auth disabled → anonymous owner.
        if not self._enabled:
            request.state.actor = Actor(scope=TokenScope.OWNER, is_anonymous=True)
            return await call_next(request)

        # Public paths → skip auth.
        if _is_public(request.url.path):
            request.state.actor = Actor(scope=TokenScope.OWNER, is_anonymous=True)
            return await call_next(request)

        # Extract Bearer token.
        auth_header = request.headers.get("authorization", "")
        match = _BEARER_RE.match(auth_header)
        if not match:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
            )

        token = match.group(1)
        record = self._store.get_record_by_token(token)
        if record is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid token"},
            )

        request.state.actor = Actor(
            token_id=record.id,
            scope=record.scope,
        )
        return await call_next(request)
