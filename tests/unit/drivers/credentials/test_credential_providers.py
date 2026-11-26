# -*- coding: utf-8 -*-
"""Tests for credential provider registry and simple providers.

Covers register/unregister/build_provider (kind dispatch, duplicate
guard, empty kind, unknown kind), NoneProvider, DirectProvider
(resolve copies record fields), _is_transient_oauth_status, and
_post_oauth_token_with_retry retry semantics, which were previously
uncovered.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from qwenpaw.drivers.contracts import CredentialRef
from qwenpaw.drivers.credentials import providers as pv
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.credentials.types import (
    CredentialRecord,
    ResolvedCredential,
)
from qwenpaw.drivers.errors import (
    DriverCredentialProviderError,
    UnsupportedCredentialKindError,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    pv.unregister_provider("_test_kind")
    pv.unregister_provider("_test_dup")


def _store_with(record):
    store = SimpleNamespace()
    store.get = AsyncMock(return_value=record)
    return store


def _record(kind="static", public=None, secrets=None, meta=None):
    return SimpleNamespace(
        kind=kind,
        public=public or {},
        secrets=secrets or {},
        meta=meta or {},
    )


# ---------------------------------------------------------------------------
# register/unregister/build_provider
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_register_and_build(self):
        factory = MagicMock()
        pv.register_provider("_test_kind", factory)
        ref = CredentialRef(kind="_test_kind", ref="r1")
        store = _store_with(_record())
        pv.build_provider(ref, store)
        factory.assert_called_once_with(ref, store)

    def test_empty_kind_rejected(self):
        with pytest.raises(UnsupportedCredentialKindError):
            pv.register_provider("", lambda ref, store: None)

    def test_duplicate_register_rejected(self):
        pv.register_provider("_test_dup", lambda ref, store: None)
        with pytest.raises(DriverCredentialProviderError):
            pv.register_provider("_test_dup", lambda ref, store: None)

    def test_duplicate_with_replace_allowed(self):
        pv.register_provider("_test_dup", lambda ref, store: None)
        pv.register_provider(
            "_test_dup",
            lambda ref, store: None,
            replace=True,
        )

    def test_unknown_kind_raises(self):
        with pytest.raises(UnsupportedCredentialKindError):
            pv.build_provider(
                CredentialRef(kind="_not_registered_xyz", ref=""),
                _store_with(_record()),
            )

    def test_unregister_missing_is_safe(self):
        pv.unregister_provider("_never_existed")  # must not raise


class TestBuiltinProviders:
    def test_none_provider_registered(self):
        ref = CredentialRef(kind="none", ref="")
        provider = pv.build_provider(ref, _store_with(_record()))
        assert isinstance(provider, pv.NoneProvider)

    def test_static_provider_registered(self):
        ref = CredentialRef(kind="static", ref="tool/x")
        provider = pv.build_provider(ref, _store_with(_record()))
        assert isinstance(provider, pv.DirectProvider)

    def test_oauth2_cc_provider_registered(self):
        ref = CredentialRef(kind="oauth2_cc", ref="r")
        provider = pv.build_provider(ref, _store_with(_record()))
        assert isinstance(provider, pv.OAuth2CCProvider)

    def test_oauth2_auth_code_provider_registered(self):
        ref = CredentialRef(kind="oauth2_auth_code", ref="r")
        provider = pv.build_provider(ref, _store_with(_record()))
        assert isinstance(provider, pv.OAuth2AuthCodeProvider)


# ---------------------------------------------------------------------------
# NoneProvider
# ---------------------------------------------------------------------------


class TestNoneProvider:
    async def test_resolves_empty(self):
        result = await pv.NoneProvider().resolve()
        assert result is ResolvedCredential.EMPTY
        assert result.kind == "none"

    async def test_close_is_noop(self):
        await pv.NoneProvider().close()  # must not raise


# ---------------------------------------------------------------------------
# DirectProvider
# ---------------------------------------------------------------------------


class TestDirectProvider:
    async def test_resolve_copies_record(self):
        record = _record(
            kind="static",
            public={"user": "u"},
            secrets={"api_key": "sk"},
            meta={"origin": "test"},
        )
        store = _store_with(record)
        provider = pv.DirectProvider("tool/x", store)
        resolved = await provider.resolve()
        assert resolved.kind == "static"
        assert resolved.public == {"user": "u"}
        assert resolved.secrets == {"api_key": "sk"}
        assert resolved.meta == {"origin": "test"}
        store.get.assert_awaited_once_with("tool/x")

    async def test_resolve_returns_copies_not_references(self):
        record = _record(kind="static", public={"k": "v"})
        provider = pv.DirectProvider("ref", _store_with(record))
        resolved = await provider.resolve()
        resolved.public["k"] = "mutated"
        # original record untouched
        assert record.public == {"k": "v"}


@pytest.mark.parametrize("rotate_refresh_token", [True, False])
async def test_oauth2_auth_code_reuses_latest_refresh_token(
    tmp_path,
    monkeypatch,
    rotate_refresh_token,
):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(pv, "time", SimpleNamespace(time=lambda: clock.now))
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    token_endpoint = "https://example.com/token"
    ref = CredentialRef(kind="oauth2_auth_code", ref="mcp/example/oauth")
    await store.put(
        CredentialRecord(
            ref=ref.ref,
            kind=ref.kind,
            public={"token_endpoint": token_endpoint},
            secrets={"refresh_token": "initial-token"},
        ),
    )

    provider = pv.build_provider(ref, store)
    expected_token = "initial-token"
    with respx.mock as router:
        route = router.post(token_endpoint)
        for generation in (1, 2):
            access_token = f"access-{generation}"
            response = {"access_token": access_token, "expires_in": 3600}
            if rotate_refresh_token:
                response["refresh_token"] = f"refresh-{generation}"
            route.respond(200, json=response)

            resolved = await provider.resolve()

            payload = parse_qs(route.calls.last.request.content.decode())
            assert payload["refresh_token"] == [expected_token]
            expected_token = response.get("refresh_token", expected_token)
            assert resolved.secrets == {"access_token": access_token}
            assert (await store.get(ref.ref)).secrets == {
                "access_token": access_token,
                "refresh_token": expected_token,
            }
            clock.now += 3600
        assert route.call_count == 2


# ---------------------------------------------------------------------------
# _is_transient_oauth_status
# ---------------------------------------------------------------------------


def _status_error(status_code: int) -> httpx.HTTPStatusError:
    response = httpx.Response(status_code)
    return httpx.HTTPStatusError(
        "err",
        request=httpx.Request("POST", "https://x/token"),
        response=response,
    )


class TestIsTransientOauthStatus:
    @pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503])
    def test_transient(self, status):
        assert pv._is_transient_oauth_status(_status_error(status)) is True

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    def test_not_transient(self, status):
        assert pv._is_transient_oauth_status(_status_error(status)) is False


# ---------------------------------------------------------------------------
# _post_oauth_token_with_retry
# ---------------------------------------------------------------------------


class TestPostOauthTokenWithRetry:
    async def test_success_first_attempt(self, monkeypatch):
        client = SimpleNamespace(
            post=AsyncMock(
                return_value=MagicMock(
                    raise_for_status=MagicMock(),
                    json=lambda: {"access_token": "tok"},
                ),
            ),
        )
        result = await pv._post_oauth_token_with_retry(
            client,
            "https://x/token",
            {},
        )
        assert result == {"access_token": "tok"}
        client.post.assert_awaited_once()

    async def test_retries_transient_then_succeeds(self, monkeypatch):
        monkeypatch.setattr(pv, "_OAUTH_RETRY_BASE_DELAY_SECONDS", 0)
        calls = {"n": 0}
        flaky = _status_error(429)

        async def post(url, data):
            calls["n"] += 1
            resp = MagicMock()
            if calls["n"] < 2:
                resp.raise_for_status.side_effect = flaky
            else:
                resp.raise_for_status.side_effect = None
            resp.json.return_value = {"access_token": "tok"}
            return resp

        client = SimpleNamespace(post=post)
        result = await pv._post_oauth_token_with_retry(client, "https://x", {})
        assert result == {"access_token": "tok"}
        assert calls["n"] == 2

    async def test_non_transient_raises_immediately(self, monkeypatch):
        monkeypatch.setattr(pv, "_OAUTH_RETRY_BASE_DELAY_SECONDS", 0)
        calls = {"n": 0}

        async def post(url, data):
            calls["n"] += 1
            resp = MagicMock()
            resp.raise_for_status.side_effect = _status_error(401)
            return resp

        client = SimpleNamespace(post=post)
        with pytest.raises(httpx.HTTPStatusError):
            await pv._post_oauth_token_with_retry(client, "https://x", {})
        assert calls["n"] == 1  # no retry for 401

    async def test_timeout_raises_after_max_attempts(self, monkeypatch):
        monkeypatch.setattr(pv, "_OAUTH_RETRY_BASE_DELAY_SECONDS", 0)
        monkeypatch.setattr(pv, "_OAUTH_TOKEN_MAX_ATTEMPTS", 2)
        calls = {"n": 0}

        async def post(url, data):
            calls["n"] += 1
            raise httpx.ConnectTimeout("slow")

        client = SimpleNamespace(post=post)
        with pytest.raises(httpx.ConnectTimeout):
            await pv._post_oauth_token_with_retry(client, "https://x", {})
        assert calls["n"] == 2
