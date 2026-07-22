# -*- coding: utf-8 -*-
"""Resolve a NocoBase user token into an ACL sender_id."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from .identity_cache import TokenIdentityCache
from .nocobase_client import NocoBaseClient

logger = logging.getLogger(__name__)

NOCOBASE_TOKEN_HEADER = "X-NocoBase-Token"

IdentityResolver = Callable[[Any], Awaitable[Optional[str]]]


def build_identity_resolver(
    engine: Any,
    cache: TokenIdentityCache,
) -> IdentityResolver:
    """Return an async resolver extracting a NocoBase token from a request.

    Token sources, in priority order: the ``X-NocoBase-Token`` header, the
    ``Authorization: Bearer`` header, then the ``?token=`` query parameter
    (used by WebSocket and file-preview URLs).  Since the login route hands
    the NocoBase token itself to clients, the Bearer header *is* a NocoBase
    token in this deployment.

    Contract: returns the user's ``sender_id`` (per ``user_id_field``) or
    ``None`` (no opinion / invalid). Never raises. Positive and definitively
    invalid results are cached; "could not verify" (network error) is not.
    """

    def _extract_token(request: Any) -> Optional[str]:
        token = request.headers.get(NOCOBASE_TOKEN_HEADER)
        if token:
            return token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        query_params = getattr(request, "query_params", None)
        if query_params is None:
            return None
        return query_params.get("token")

    async def resolve(request: Any) -> Optional[str]:
        # pylint: disable=too-many-return-statements
        config = getattr(engine, "config", None)
        if not (config and getattr(config, "enabled", False)):
            return None
        token = _extract_token(request)
        if not token:
            return None

        hit, value = cache.get(token)
        if hit:
            return value

        try:
            user = await engine.verify_user_token(token)
        except Exception:
            logger.warning(
                "NocoBase auth: token check errored; not caching this token",
            )
            return None

        if user is None:
            cache.put(token, None)  # definitively invalid -> negative cache
            return None

        sender_id = NocoBaseClient.extract_sender_id(
            user,
            config.user_id_field,
        )
        if not sender_id:
            cache.put(token, None)
            return None
        cache.put(token, sender_id)
        return sender_id

    return resolve
