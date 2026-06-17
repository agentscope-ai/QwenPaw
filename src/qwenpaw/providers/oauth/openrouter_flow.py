# -*- coding: utf-8 -*-
"""OpenRouter OAuth flow: browser redirect -> code -> permanent API Key."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from .base import (
    OAuthFlow,
    OAuthStartResult,
    OAuthTokenResult,
    generate_state,
)


class OpenRouterOAuthFlow(OAuthFlow):
    """OpenRouter: redirect to openrouter.ai/auth -> get permanent key."""

    provider_id = "openrouter"

    def start(self, callback_url: str) -> OAuthStartResult:
        """Generate OpenRouter authorize URL."""
        state = generate_state()
        authorize_url = (
            f"https://openrouter.ai/auth"
            f"?callback_url={quote(callback_url, safe='')}"
        )
        return OAuthStartResult(
            authorize_url=authorize_url,
            state=state,
            flow_type="browser_redirect",
        )

    async def exchange(
        self,
        code: str,
        state: str = "",
        code_verifier: str = "",
        callback_url: str = "",
    ) -> OAuthTokenResult:
        """Exchange code for a permanent API key."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/auth/keys",
                json={"code": code},
            )
            resp.raise_for_status()
            data = resp.json()
            return OAuthTokenResult(api_key=data["key"])
