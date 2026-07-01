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
    """Return an async resolver reading ``X-NocoBase-Token`` from a request.

    Contract: returns the user's ``sender_id`` (per ``user_id_field``) or
    ``None`` (no opinion / invalid). Never raises. Positive and definitively
    invalid results are cached; "could not verify" (network error) is not.
    """

    async def resolve(request: Any) -> Optional[str]:
        # pylint: disable=too-many-return-statements
        config = getattr(engine, "config", None)
        if not (config and getattr(config, "enabled", False)):
            return None
        token = request.headers.get(NOCOBASE_TOKEN_HEADER)
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
