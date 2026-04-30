# -*- coding: utf-8 -*-
"""DTOs for the GitHub Copilot OAuth device-code flow."""
from __future__ import annotations

import time
from typing import Optional

from pydantic import BaseModel, Field


class DeviceCodeStart(BaseModel):
    """Response for ``POST /models/{provider_id}/oauth/device-code``."""

    user_code: str = Field(..., description="Code the user types into GitHub")
    verification_uri: str = Field(
        ...,
        description="URL the user opens to enter the code",
    )
    expires_in: int = Field(
        default=900,
        description="Seconds until the device code expires",
    )
    interval: int = Field(
        default=5,
        description="Recommended polling interval in seconds",
    )


class OAuthStatus(BaseModel):
    """Response for ``GET /models/{provider_id}/oauth/status``."""

    status: str = Field(
        ...,
        description=(
            "One of: 'not_started', 'pending', 'authorized', 'error'."
        ),
    )
    message: str = Field(default="")
    is_authenticated: bool = Field(default=False)
    login: str = Field(
        default="",
        description="GitHub login of the authenticated user when known.",
    )


class CopilotApiToken(BaseModel):
    """Short-lived Copilot API token returned by ``copilot_internal/v2/token``.

    Held in memory only; never persisted to disk.
    """

    token: str
    expires_at: int = Field(
        default=0,
        description="Unix epoch seconds when the token expires.",
    )
    refresh_in: int = Field(
        default=0,
        description=(
            "Server-suggested seconds until next refresh. "
            "When non-zero this is preferred over expires_at-buffer."
        ),
    )
    api_endpoint: str = Field(
        default="https://api.githubcopilot.com",
        description=(
            "Copilot REST endpoint announced via the token response's "
            "endpoints.api field."
        ),
    )
    chat_enabled: Optional[bool] = Field(default=None)
    sku: str = Field(default="")

    def is_expired(self, buffer_seconds: int = 0) -> bool:
        """Return True when the token will expire within *buffer_seconds*."""
        if self.expires_at <= 0:
            return False
        return int(time.time()) >= (self.expires_at - max(0, buffer_seconds))
