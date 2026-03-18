# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from copaw.providers.auth_helper_registry import (
    get_auth_helper_for_provider,
    refresh_provider_auth,
)
from copaw.providers.openai_auth import OPENAI_AUTH_HELPER
from copaw.providers.openai_provider import OpenAIProvider
from copaw.providers.provider import ProviderAuth

pytestmark = pytest.mark.anyio


def _make_provider() -> OpenAIProvider:
    return OpenAIProvider(
        id="openai",
        name="OpenAI",
        auth_helper="openai",
        auth_modes=["api_key", "oauth_browser"],
        auth=ProviderAuth(
            mode="oauth_browser",
            status="authorized",
            refresh_token="refresh-1",
        ),
    )


def test_get_auth_helper_for_provider_returns_registered_helper() -> None:
    provider = _make_provider()

    helper = get_auth_helper_for_provider(provider)

    assert helper is OPENAI_AUTH_HELPER


async def test_refresh_provider_auth_dispatches_to_registered_helper(
    monkeypatch,
) -> None:
    provider = _make_provider()
    persisted: list[str] = []

    async def fake_refresh(current, persist):
        current.auth.access_token = "access-2"
        persist(current)
        return current.auth

    monkeypatch.setattr(OPENAI_AUTH_HELPER, "refresh_auth", fake_refresh)

    auth = await refresh_provider_auth(
        provider,
        lambda current: persisted.append(current.auth.access_token),
    )

    assert auth.access_token == "access-2"
    assert persisted == ["access-2"]


async def test_refresh_provider_auth_fails_without_registered_helper() -> None:
    provider = OpenAIProvider(
        id="custom-openai",
        name="Custom OpenAI",
        auth_modes=["api_key", "oauth_browser"],
        auth=ProviderAuth(
            mode="oauth_browser",
            status="authorized",
            refresh_token="refresh-1",
        ),
    )
    persisted: list[tuple[str, str]] = []

    with pytest.raises(RuntimeError, match="No auth helper registered"):
        await refresh_provider_auth(
            provider,
            lambda current: persisted.append(
                (current.auth.status, current.auth.error),
            ),
        )

    assert persisted
    assert persisted[-1][0] == "error"
