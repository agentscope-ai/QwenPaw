# -*- coding: utf-8 -*-
"""Unit tests for OAuth2 credential providers (issue #7053).

Covers the rotating-refresh_token fix:
- ``StandardOAuth2Exchanger.exchange`` returns the rotated refresh_token.
- ``OAuth2AuthCodeProvider.resolve`` persists the rotated refresh_token so a
  rotating provider does not permanently degrade to manual re-auth.
"""
from __future__ import annotations

import time
from typing import Any

import pytest

from qwenpaw.drivers.credentials.providers import (
    OAuth2AuthCodeProvider,
    StandardOAuth2Exchanger,
)
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.credentials.types import CredentialRecord


class _FakeExchanger:
    """TokenExchanger stub returning a rotating refresh_token."""

    def __init__(
        self,
        access_token: str = "new-access",
        expires_in: int = 3600,
        rotated_refresh_token: str | None = "rotated-refresh",
    ) -> None:
        self._access_token = access_token
        self._expires_in = expires_in
        self._rotated_refresh_token = rotated_refresh_token
        self.exchange_calls: list[dict[str, Any]] = []

    async def exchange(
        self,
        secrets: dict[str, Any],
    ) -> tuple[str, int, str | None]:
        self.exchange_calls.append(dict(secrets))
        return (
            self._access_token,
            self._expires_in,
            self._rotated_refresh_token,
        )


async def _seed_expired_record(store: AsyncCredentialStore) -> None:
    """Seed an expired auth-code credential so resolve() refreshes."""
    await store.put(
        CredentialRecord(
            ref="mcp:test",
            kind="oauth2_auth_code",
            public={
                "token_endpoint": "https://example.com/token",
                "expires_at": time.time() - 60,  # expired -> refresh
            },
            secrets={
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "client_id": "client-1",
            },
            meta={},
        ),
    )


@pytest.mark.asyncio
async def test_auth_code_provider_persists_rotated_refresh_token(tmp_path):
    """Rotated refresh_token must be written back to the store."""
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await _seed_expired_record(store)
    exchanger = _FakeExchanger()
    provider = OAuth2AuthCodeProvider(
        ref="mcp:test",
        store=store,
        exchanger=exchanger,
    )

    resolved = await provider.resolve()

    assert resolved.secrets["access_token"] == "new-access"
    # The exchanger received the existing refresh_token for the grant.
    assert exchanger.exchange_calls[0]["refresh_token"] == "old-refresh"
    # The store now holds the rotated refresh_token.
    record = await store.get("mcp:test")
    assert record.secrets["access_token"] == "new-access"
    assert record.secrets["refresh_token"] == "rotated-refresh"
    assert record.public["expires_at"] > time.time()


@pytest.mark.asyncio
async def test_auth_code_provider_keeps_refresh_token_when_not_rotated(
    tmp_path,
):
    """Non-rotating responses (None) must not clobber the stored token."""
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await _seed_expired_record(store)
    exchanger = _FakeExchanger(rotated_refresh_token=None)
    provider = OAuth2AuthCodeProvider(
        ref="mcp:test",
        store=store,
        exchanger=exchanger,
    )

    resolved = await provider.resolve()

    assert resolved.secrets["access_token"] == "new-access"
    record = await store.get("mcp:test")
    assert record.secrets["refresh_token"] == "old-refresh"


@pytest.mark.asyncio
async def test_exchanger_returns_rotated_refresh_token(monkeypatch):
    """StandardOAuth2Exchanger must surface a rotated refresh_token."""

    async def fake_post(client, token_endpoint, payload):  # noqa: ARG001
        return {
            "access_token": "tok-2",
            "expires_in": 7200,
            "refresh_token": "rot-2",
        }

    monkeypatch.setattr(
        "qwenpaw.drivers.credentials.providers._post_oauth_token_with_retry",
        fake_post,
    )
    exchanger = StandardOAuth2Exchanger()
    token, expires_in, rotated = await exchanger.exchange(
        {
            "token_endpoint": "https://example.com/token",
            "refresh_token": "old-refresh",
            "client_id": "client-1",
        },
    )

    assert token == "tok-2"
    assert expires_in == 7200
    assert rotated == "rot-2"


@pytest.mark.asyncio
async def test_exchanger_returns_none_when_no_rotation(monkeypatch):
    """Responses without refresh_token must yield None (not clobber)."""

    async def fake_post(client, token_endpoint, payload):  # noqa: ARG001
        return {"access_token": "tok-3", "expires_in": 3600}

    monkeypatch.setattr(
        "qwenpaw.drivers.credentials.providers._post_oauth_token_with_retry",
        fake_post,
    )
    exchanger = StandardOAuth2Exchanger()
    token, expires_in, rotated = await exchanger.exchange(
        {
            "token_endpoint": "https://example.com/token",
            "refresh_token": "old-refresh",
            "client_id": "client-1",
        },
    )

    assert token == "tok-3"
    assert expires_in == 3600
    assert rotated is None
