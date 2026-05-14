# -*- coding: utf-8 -*-
"""Provider authentication infrastructure."""

from .adapter import ProviderAuthAdapter
from .credential_store import OAuthCredentialStore
from .manager import ProviderAuthError, ProviderAuthManager
from .models import (
    AuthStartRequest,
    AuthStartResult,
    AuthStatusResult,
    OAuthCredential,
    ProviderAuthFlowType,
    ProviderAuthInfo,
    ProviderAuthStatus,
    ProviderAuthType,
)
from .registry import ProviderAuthRegistry, auth_registry

__all__ = [
    "AuthStartRequest",
    "AuthStartResult",
    "AuthStatusResult",
    "OAuthCredential",
    "OAuthCredentialStore",
    "ProviderAuthAdapter",
    "ProviderAuthError",
    "ProviderAuthFlowType",
    "ProviderAuthInfo",
    "ProviderAuthManager",
    "ProviderAuthRegistry",
    "ProviderAuthStatus",
    "ProviderAuthType",
    "auth_registry",
]
