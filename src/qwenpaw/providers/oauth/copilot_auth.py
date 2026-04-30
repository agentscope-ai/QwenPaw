# -*- coding: utf-8 -*-
"""``httpx.Auth`` adapter that injects a fresh Copilot token per request."""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Generator, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from .copilot_oauth_service import CopilotOAuthService

logger = logging.getLogger(__name__)


class CopilotAuth(httpx.Auth):
    """Inject the latest short-lived Copilot API token on every request.

    By using a ``httpx.Auth`` subclass instead of baking the token into
    the client's ``default_headers``, the underlying ``AsyncOpenAI``
    client never goes stale: each request fetches a fresh token from the
    :class:`CopilotOAuthService` (with synchronous lazy refresh when the
    cached token is about to expire).

    On a ``401`` response we force a refresh and retry once — this
    handles tokens revoked server-side mid-request.
    """

    requires_request_body = False
    requires_response_body = False

    def __init__(self, service: "CopilotOAuthService") -> None:
        self._service = service

    def sync_auth_flow(
        self,
        request: httpx.Request,
    ) -> Generator[httpx.Request, httpx.Response, None]:
        # The OpenAI Python SDK is async-only; this is provided defensively
        # in case a sync code path ever calls in.
        token = _run_sync(self._service.get_copilot_token())
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            token = _run_sync(
                self._service.get_copilot_token(force_refresh=True),
            )
            request.headers["Authorization"] = f"Bearer {token}"
            yield request

    async def async_auth_flow(  # type: ignore[override]
        self,
        request: httpx.Request,
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        token = await self._service.get_copilot_token()
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            logger.info(
                "Copilot returned 401; forcing OAuth token refresh and "
                "retrying once.",
            )
            try:
                token = await self._service.get_copilot_token(
                    force_refresh=True,
                )
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "Refresh after 401 failed; surfacing original error.",
                    exc_info=True,
                )
                return
            request.headers["Authorization"] = f"Bearer {token}"
            yield request


def _run_sync(coro):
    """Run an async coroutine from a sync context. Best-effort."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    if loop.is_running():
        # Should not happen in practice (sync auth path is unused by the
        # OpenAI SDK), but fall back to creating a new loop.
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
    return loop.run_until_complete(coro)
