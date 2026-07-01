# -*- coding: utf-8 -*-
"""Unit tests for SyncEngine.verify_user_token delegation."""
from __future__ import annotations

from types import SimpleNamespace

from nocobase_auth.sync_engine import SyncEngine


class _FakeClient:
    def __init__(self, user):
        self._user = user
        self.called_with = None

    async def verify_user_token(self, token):
        self.called_with = token
        return self._user


async def test_verify_user_token_none_when_not_configured() -> None:
    engine = SyncEngine()
    engine.config = SimpleNamespace(
        enabled=False,
        base_url="",
        api_token="",
    )
    engine._client = None
    assert await engine.verify_user_token("t") is None


async def test_verify_user_token_delegates_to_client() -> None:
    engine = SyncEngine()
    engine.config = SimpleNamespace(
        enabled=True,
        base_url="http://nb",
        api_token="admin",
    )
    fake = _FakeClient({"email": "x@y.com"})
    engine._client = fake
    user = await engine.verify_user_token("USER-TOK")
    assert user == {"email": "x@y.com"}
    assert fake.called_with == "USER-TOK"
