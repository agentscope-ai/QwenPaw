# -*- coding: utf-8 -*-
"""Registry and dispatch helpers for provider auth helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .auth_helper_base import BaseAuthHelper, AuthSession
from .provider import Provider, ProviderAuth


class AuthHelperRegistry:
    """In-memory registry of auth helpers keyed by helper id."""

    def __init__(self) -> None:
        self._helpers: dict[str, BaseAuthHelper] = {}

    def register(self, helper: BaseAuthHelper) -> BaseAuthHelper:
        self._helpers[helper.helper_id] = helper
        return helper

    def get(self, helper_id: str) -> BaseAuthHelper | None:
        return self._helpers.get(helper_id)

    def get_for_provider(self, provider: Provider) -> BaseAuthHelper | None:
        if not provider.auth_helper:
            return None
        helper = self.get(provider.auth_helper)
        if helper is None or not helper.supports(provider):
            return None
        return helper


AUTH_HELPER_REGISTRY = AuthHelperRegistry()


def get_auth_helper_for_provider(provider: Provider) -> BaseAuthHelper | None:
    """Return the auth helper configured for the provider, if any."""
    return AUTH_HELPER_REGISTRY.get_for_provider(provider)


def is_browser_auth_supported(provider: Provider) -> bool:
    """Return whether a provider has a registered browser auth helper."""
    return get_auth_helper_for_provider(provider) is not None


def browser_auth_unavailable_reason(provider: Provider) -> str:
    """Return a provider-specific browser auth availability message."""
    helper = get_auth_helper_for_provider(provider)
    if helper is None:
        return f"Provider '{provider.id}' does not support browser sign-in."
    return helper.unavailable_reason()


async def start_provider_browser_login(
    provider: Provider,
    auth_root: Path,
    persist: Callable[[Provider], None],
) -> AuthSession:
    """Start the provider's registered browser login flow."""
    helper = get_auth_helper_for_provider(provider)
    if helper is None:
        raise ValueError(
            f"Provider '{provider.id}' does not support browser sign-in.",
        )
    return await helper.start_browser_login(provider, auth_root, persist)


async def get_provider_auth_session(
    provider: Provider,
    session_id: str,
) -> AuthSession | None:
    """Look up an auth session using the provider's registered helper."""
    helper = get_auth_helper_for_provider(provider)
    if helper is None:
        return None
    return await helper.get_session(session_id)


async def refresh_provider_auth(
    provider: Provider,
    persist: Callable[[Provider], None],
) -> ProviderAuth:
    """Refresh provider auth via the registered auth helper."""
    auth = provider.auth
    if auth.mode != "oauth_browser":
        return auth

    helper = get_auth_helper_for_provider(provider)
    if helper is None:
        auth.status = "error"
        auth.error = f"No auth helper registered for provider '{provider.id}'."
        persist(provider)
        raise RuntimeError(auth.error)

    return await helper.refresh_auth(provider, persist)
