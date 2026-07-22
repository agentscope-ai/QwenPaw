# -*- coding: utf-8 -*-
"""Base class and models for provider OAuth flows."""

from __future__ import annotations

import base64
import hashlib
import secrets
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field


class OAuthStartResult(BaseModel):
    """Result of starting an OAuth flow."""

    authorize_url: str = Field(
        ...,
        description="URL to open in browser popup",
    )
    state: str = Field(
        ...,
        description="State token for CSRF protection",
    )
    flow_type: str = Field(
        default="browser_redirect",
        description="OAuth flow type: browser_redirect or device_code",
    )


class OAuthTokenResult(BaseModel):
    """Result of completing an OAuth flow."""

    api_key: Optional[str] = Field(
        default=None,
        description="Permanent API key (e.g. OpenRouter)",
    )
    access_token: Optional[str] = Field(
        default=None,
        description="Short-lived access token (e.g. Qwen)",
    )
    refresh_token: Optional[str] = Field(
        default=None,
        description="Refresh token for token renewal",
    )
    expires_at: Optional[float] = Field(
        default=None,
        description="Unix timestamp when access_token expires",
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Override base URL if needed",
    )


class OAuthFlow(ABC):
    """Abstract base for provider-specific OAuth flows."""

    provider_id: str = ""

    @abstractmethod
    def start(self, callback_url: str) -> OAuthStartResult:
        """Generate the authorize URL and state token."""

    @abstractmethod
    async def exchange(
        self,
        code: str,
        state: str,
        code_verifier: str,
        callback_url: str,
    ) -> OAuthTokenResult:
        """Exchange authorization code for credentials."""

    async def refresh(
        self,
        refresh_token: str,
    ) -> OAuthTokenResult:
        """Refresh an expired token. Optional."""
        raise NotImplementedError(
            f"{self.provider_id} does not support token refresh",
        )

    def get_credential_dict(
        self,
        result: OAuthTokenResult,
    ) -> dict:
        """Convert OAuthTokenResult to provider config fields."""
        if result.api_key:
            return {"api_key": result.api_key}
        if result.access_token:
            return {"api_key": result.access_token}
        return {}


def generate_code_verifier() -> str:
    """Generate a PKCE code_verifier (RFC 7636)."""
    return (
        base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    )


def generate_code_challenge(verifier: str) -> str:
    """Derive S256 code_challenge from verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def generate_state() -> str:
    """Generate a cryptographic state token."""
    return secrets.token_urlsafe(32)
