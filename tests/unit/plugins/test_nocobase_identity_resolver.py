# -*- coding: utf-8 -*-
# pylint: disable=unused-argument
"""Unit tests for the NocoBase identity resolver."""
from __future__ import annotations

from nocobase_auth.identity_cache import TokenIdentityCache
from nocobase_auth.identity_resolver import build_identity_resolver
from nocobase_auth.nocobase_client import NocoBaseRequestError


class _Cfg:
    def __init__(self, enabled=True, user_id_field="email"):
        self.enabled = enabled
        self.user_id_field = user_id_field


class _FakeEngine:
    def __init__(self, cfg, user=None, exc=None):
        self.config = cfg
        self._user = user
        self._exc = exc
        self.calls = 0

    async def verify_user_token(self, token):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._user


class _Req:
    def __init__(self, headers):
        self.headers = headers


def _cache():
    return TokenIdentityCache(ttl_seconds=60, time_fn=lambda: 0.0)


async def test_disabled_returns_none() -> None:
    eng = _FakeEngine(_Cfg(enabled=False))
    resolve = build_identity_resolver(eng, _cache())
    assert await resolve(_Req({"X-NocoBase-Token": "t"})) is None


async def test_no_header_returns_none() -> None:
    eng = _FakeEngine(_Cfg())
    resolve = build_identity_resolver(eng, _cache())
    assert await resolve(_Req({})) is None
    assert eng.calls == 0


async def test_success_extracts_email_and_caches() -> None:
    eng = _FakeEngine(_Cfg(), user={"id": 1, "email": "eve@example.com"})
    cache = _cache()
    resolve = build_identity_resolver(eng, cache)
    req = _Req({"X-NocoBase-Token": "t"})
    assert await resolve(req) == "eve@example.com"
    # second call served from cache, no extra verify
    assert await resolve(req) == "eve@example.com"
    assert eng.calls == 1


async def test_invalid_token_negative_cached() -> None:
    eng = _FakeEngine(_Cfg(), user=None)
    cache = _cache()
    resolve = build_identity_resolver(eng, cache)
    req = _Req({"X-NocoBase-Token": "bad"})
    assert await resolve(req) is None
    assert await resolve(req) is None
    assert eng.calls == 1  # negative-cached, not re-verified


async def test_network_error_not_cached() -> None:
    eng = _FakeEngine(_Cfg(), exc=NocoBaseRequestError("down"))
    cache = _cache()
    resolve = build_identity_resolver(eng, cache)
    req = _Req({"X-NocoBase-Token": "t"})
    assert await resolve(req) is None
    assert await resolve(req) is None
    assert eng.calls == 2  # retried, not cached
