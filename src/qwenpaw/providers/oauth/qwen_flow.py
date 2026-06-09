# -*- coding: utf-8 -*-
"""Qwen OAuth flow: PKCE -> access_token + refresh_token."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from .base import (
    OAuthFlow,
    OAuthStartResult,
    OAuthTokenResult,
    generate_code_challenge,
    generate_code_verifier,
    generate_state,
)


class QwenOAuthFlow(OAuthFlow):
    """Qwen: PKCE OAuth flow with refresh token support."""

    provider_id = "qwen"
    CLIENT_ID = "f0304373b74a44d2b584a3fb70ca9e56"
    TOKEN_URL = "https://chat.qwen.ai/api/v1/oauth2/token"
    AUTHORIZE_URL = "https://chat.qwen.ai/oauth/authorize"

    def start(self, callback_url: str) -> OAuthStartResult:
        """Generate Qwen authorize URL with PKCE."""
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        state = generate_state()
        params = urlencode(
            {
                "response_type": "code",
                "client_id": self.CLIENT_ID,
                "redirect_uri": callback_url,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "state": state,
            },
        )
        authorize_url = f"{self.AUTHORIZE_URL}?{params}"
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
        """Exchange authorization code for tokens."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.CLIENT_ID,
                    "code_verifier": code_verifier,
                    "redirect_uri": callback_url,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            expires_at = None
            if data.get("expiry_date"):
                expires_at = data["expiry_date"] / 1000.0
            return OAuthTokenResult(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                expires_at=expires_at,
                base_url="https://chat.qwen.ai/api/v1",
            )

    async def refresh(
        self,
        refresh_token: str,
    ) -> OAuthTokenResult:
        """Refresh an expired Qwen access token."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self.CLIENT_ID,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            expires_at = None
            if data.get("expiry_date"):
                expires_at = data["expiry_date"] / 1000.0
            return OAuthTokenResult(
                access_token=data["access_token"],
                refresh_token=data.get(
                    "refresh_token",
                    refresh_token,
                ),
                expires_at=expires_at,
            )
