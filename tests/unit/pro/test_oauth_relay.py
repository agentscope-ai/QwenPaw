# -*- coding: utf-8 -*-
"""Tests for short-lived Pro OAuth callback relay capabilities."""

import pytest

from qwenpaw.pro.oauth_relay import OAuthRelayStore


def test_relay_tokens_are_runtime_scoped_and_one_time() -> None:
    store = OAuthRelayStore()
    first_token = store.create("runtime-one", "/api/mcp/oauth/callback")
    second_token = store.create(
        "runtime-two",
        "/api/providers/openrouter/oauth/callback",
    )

    first = store.take(first_token)
    second = store.take(second_token)

    assert first is not None
    assert first.runtime_id == "runtime-one"
    assert first.callback_path == "/api/mcp/oauth/callback"
    assert second is not None
    assert second.runtime_id == "runtime-two"
    assert store.take(first_token) is None


def test_expired_relay_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time = 100.0
    monkeypatch.setattr(
        "qwenpaw.pro.oauth_relay.time.monotonic",
        lambda: current_time,
    )
    store = OAuthRelayStore()
    token = store.create("runtime-one", "/api/mcp/oauth/callback")

    current_time = 701.0

    assert store.take(token) is None
