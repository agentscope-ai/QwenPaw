# -*- coding: utf-8 -*-
"""Base types for provider auth helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Protocol

from .provider import Provider, ProviderAuth


class AuthSession(Protocol):
    """Minimal session contract exposed to the router layer."""

    provider_id: str

    def to_dict(self) -> dict[str, str]:
        """Serialize the session for API responses."""


class BaseAuthHelper(ABC):
    """Abstract interface for provider-specific browser auth helpers."""

    helper_id: str = ""

    def supports(self, provider: Provider) -> bool:
        return (
            provider.auth_helper == self.helper_id
            and "oauth_browser" in provider.auth_modes
        )

    def is_available(self) -> bool:
        """Return whether this auth flow can run in the current environment."""
        return True

    def unavailable_reason(self) -> str:
        """Return a user-facing message when the helper is unavailable."""
        return "Browser sign-in is not available for this provider."

    @abstractmethod
    async def start_browser_login(
        self,
        provider: Provider,
        auth_root: Path,
        persist: Callable[[Provider], None],
    ) -> AuthSession:
        """Start a browser login flow for the provider."""

    @abstractmethod
    async def get_session(self, session_id: str) -> AuthSession | None:
        """Load an in-memory auth session by id."""

    @abstractmethod
    async def refresh_auth(
        self,
        provider: Provider,
        persist: Callable[[Provider], None],
    ) -> ProviderAuth:
        """Refresh persisted auth credentials in-place when needed."""
