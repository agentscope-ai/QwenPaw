# -*- coding: utf-8 -*-
"""GitHub Copilot OAuth subsystem.

Provides device-code authentication, token persistence and per-request
authorization for the GitHub Copilot built-in provider.
"""
from .copilot_auth import CopilotAuth
from .copilot_oauth_service import (
    CopilotOAuthService,
    CopilotOAuthError,
    get_oauth_service,
)
from .copilot_token_store import CopilotTokenStore
from .models import (
    CopilotApiToken,
    DeviceCodeStart,
    OAuthStatus,
)

__all__ = [
    "CopilotApiToken",
    "CopilotAuth",
    "CopilotOAuthError",
    "CopilotOAuthService",
    "CopilotTokenStore",
    "DeviceCodeStart",
    "OAuthStatus",
    "get_oauth_service",
]
