# -*- coding: utf-8 -*-
"""Unit tests for :mod:`qwenpaw.providers.xai_login`.

The PKCE loopback flow is mostly orchestration; the parts that warrant
unit tests are the pure helpers (PKCE generation, discovery validation,
token exchange, atomic save) and the callback handler's state-mismatch
defense.  The HTTP server + serve_forever loop is integration-tested
via the live ``qwenpaw xai login`` smoke path — not duplicated here.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from qwenpaw.providers import xai_login as xai_login_module
from qwenpaw.providers.xai_login import (
    LOOPBACK_REDIRECT_URI,
    XAI_OAUTH_SCOPE,
    _CallbackHandler,
    _discover,
    _exchange_code,
    _pkce_challenge,
    _pkce_verifier,
    _save_auth,
    is_port_free,
)
from qwenpaw.providers.xai_auth import (
    DEFAULT_XAI_BASE_URL,
    XAI_OAUTH_CLIENT_ID,
    XAI_OAUTH_ISSUER,
)

# URL fixtures used across discovery tests — extracted so per-test
# dicts fit inside the project's 79-char line cap without escaping.
_AUTH_URL = "https://auth.x.ai/oauth2/authorize"
_TOKEN_URL = "https://auth.x.ai/oauth2/token"
_AUTH_URL_HTTP = "http://auth.x.ai/oauth2/authorize"
_TOKEN_URL_EVIL = "https://evil.example.com/oauth2/token"


# ---------------------------------------------------------------- #
# Fakes                                                            #
# ---------------------------------------------------------------- #


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        body: dict[str, Any] | None = None,
        text: str | None = None,
    ) -> None:
        self.status_code = status_code
        self._body = body or {}
        self.text = text if text is not None else json.dumps(self._body)

    def json(self) -> dict[str, Any]:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "https://example/x"),
                response=httpx.Response(self.status_code),
            )


class _FakeAsyncClient:
    instances: list["_FakeAsyncClient"] = []

    def __init__(
        self,
        *,
        response: _FakeResponse | dict[str, _FakeResponse],
        **_: Any,
    ) -> None:
        # Allow either a single response or a per-URL map (for the
        # mixed discovery + token endpoints case).
        self._response = response
        self.gets: list[str] = []
        self.posts: list[dict[str, Any]] = []
        _FakeAsyncClient.instances.append(self)

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    def _pick(self, url: str) -> _FakeResponse:
        if isinstance(self._response, dict):
            return self._response[url]
        return self._response

    async def get(self, url: str, **_kwargs: Any) -> _FakeResponse:
        self.gets.append(url)
        return self._pick(url)

    async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.posts.append({"url": url, **kwargs})
        return self._pick(url)


def _patch_httpx_client(
    monkeypatch: pytest.MonkeyPatch,
    response: _FakeResponse | dict[str, _FakeResponse],
) -> None:
    _FakeAsyncClient.instances.clear()

    def _factory(**kwargs: Any) -> _FakeAsyncClient:
        return _FakeAsyncClient(response=response, **kwargs)

    monkeypatch.setattr(xai_login_module.httpx, "AsyncClient", _factory)


# ---------------------------------------------------------------- #
# PKCE                                                             #
# ---------------------------------------------------------------- #


class TestPkce:
    def test_verifier_is_url_safe_and_long_enough(self) -> None:
        # RFC 7636 requires 43–128 url-safe characters.
        for _ in range(20):
            v = _pkce_verifier()
            assert 43 <= len(v) <= 128
            assert all(
                c.isalnum() or c in "-_" for c in v
            ), f"non-url-safe char in {v!r}"

    def test_verifier_is_unique_per_call(self) -> None:
        # Two consecutive calls must never collide — collision would
        # mean the per-flow secret is predictable.
        verifiers = {_pkce_verifier() for _ in range(50)}
        assert len(verifiers) == 50

    def test_challenge_matches_s256_of_verifier(self) -> None:
        v = _pkce_verifier()
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        assert _pkce_challenge(v) == expected


# ---------------------------------------------------------------- #
# Discovery                                                        #
# ---------------------------------------------------------------- #


class TestDiscover:
    async def test_returns_endpoints_when_valid(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_httpx_client(
            monkeypatch,
            _FakeResponse(
                200,
                {
                    "authorization_endpoint": _AUTH_URL,
                    "token_endpoint": _TOKEN_URL,
                },
            ),
        )

        endpoints = await _discover()

        assert endpoints == {
            "authorization_endpoint": _AUTH_URL,
            "token_endpoint": _TOKEN_URL,
        }
        # Asked the well-known URL on the issuer.
        get_url = _FakeAsyncClient.instances[0].gets[0]
        assert (
            get_url == f"{XAI_OAUTH_ISSUER}/.well-known/openid-configuration"
        )

    async def test_rejects_missing_endpoint(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_httpx_client(
            monkeypatch,
            _FakeResponse(
                200,
                {"authorization_endpoint": _AUTH_URL},
            ),
        )

        with pytest.raises(RuntimeError, match="returned no endpoints"):
            await _discover()

    async def test_rejects_non_https_endpoint(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Defense-in-depth — discovery must refuse http:// or wrong-host
        # endpoints so a compromised DNS can't steer the browser to a
        # phishing host.
        _patch_httpx_client(
            monkeypatch,
            _FakeResponse(
                200,
                {
                    "authorization_endpoint": _AUTH_URL_HTTP,
                    "token_endpoint": _TOKEN_URL,
                },
            ),
        )

        with pytest.raises(RuntimeError, match="not https on .x.ai"):
            await _discover()

    async def test_rejects_off_domain_endpoint(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_httpx_client(
            monkeypatch,
            _FakeResponse(
                200,
                {
                    "authorization_endpoint": _AUTH_URL,
                    "token_endpoint": _TOKEN_URL_EVIL,
                },
            ),
        )

        with pytest.raises(RuntimeError, match="not https on .x.ai"):
            await _discover()


# ---------------------------------------------------------------- #
# Callback handler                                                 #
# ---------------------------------------------------------------- #


class _StubRequest:
    """Minimal stand-in for ``BaseHTTPRequestHandler``'s request object —
    avoids spinning a real socket while still letting us drive ``do_GET``."""

    def makefile(self, *_args: Any, **_kwargs: Any) -> Any:
        import io

        return io.BytesIO()


def _make_handler(
    path: str,
    *,
    expected_state: str,
) -> tuple[_CallbackHandler, dict[str, Any]]:
    """Construct a handler without actually serving — drive ``do_GET``
    against a captured ``path`` and inspect ``result_holder`` afterwards."""
    result_holder: dict[str, Any] = {}

    handler = _CallbackHandler.__new__(_CallbackHandler)
    handler.result_holder = result_holder
    handler.expected_state = expected_state
    handler.path = path
    handler.wfile = MagicMock()
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    return handler, result_holder


class TestCallbackHandler:
    def test_404_on_non_callback_path(self) -> None:
        handler, holder = _make_handler("/random", expected_state="abc")
        handler.do_GET()
        handler.send_response.assert_called_with(404)
        assert not holder

    def test_error_param_captured(self) -> None:
        handler, holder = _make_handler(
            "/callback?error=access_denied",
            expected_state="abc",
        )
        handler.do_GET()
        assert "error" in holder
        assert "access_denied" in holder["error"]

    def test_missing_code_param_captured(self) -> None:
        handler, holder = _make_handler(
            "/callback?state=abc",
            expected_state="abc",
        )
        handler.do_GET()
        assert holder.get("error") == "Callback missing ?code= param"

    def test_state_mismatch_rejected(self) -> None:
        # CSRF defense — a /callback with the wrong state must never
        # surface its code, even on a loopback-only listener.
        handler, holder = _make_handler(
            "/callback?code=AUTH123&state=wrong",
            expected_state="right",
        )
        handler.do_GET()
        assert "error" in holder
        assert "State mismatch" in holder["error"]
        assert "code" not in holder

    def test_success_records_code(self) -> None:
        handler, holder = _make_handler(
            "/callback?code=AUTH123&state=abc",
            expected_state="abc",
        )
        handler.do_GET()
        assert holder.get("code") == "AUTH123"
        assert "error" not in holder


# ---------------------------------------------------------------- #
# Token exchange                                                   #
# ---------------------------------------------------------------- #


class TestExchangeCode:
    async def test_success_returns_body(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_httpx_client(
            monkeypatch,
            _FakeResponse(
                200,
                {
                    "access_token": "at",
                    "refresh_token": "rt",
                    "id_token": "it",
                },
            ),
        )

        body = await _exchange_code(
            token_endpoint="https://auth.x.ai/oauth2/token",
            code="AUTH123",
            code_verifier="V" * 64,
        )

        assert body == {
            "access_token": "at",
            "refresh_token": "rt",
            "id_token": "it",
        }
        post = _FakeAsyncClient.instances[0].posts[0]
        assert post["url"] == "https://auth.x.ai/oauth2/token"
        assert post["data"]["grant_type"] == "authorization_code"
        assert post["data"]["client_id"] == XAI_OAUTH_CLIENT_ID
        assert post["data"]["code"] == "AUTH123"
        assert post["data"]["redirect_uri"] == LOOPBACK_REDIRECT_URI
        assert post["data"]["code_verifier"] == "V" * 64

    async def test_http_4xx_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_httpx_client(
            monkeypatch,
            _FakeResponse(400, text="bad client"),
        )

        with pytest.raises(RuntimeError, match="HTTP 400"):
            await _exchange_code(
                token_endpoint="https://auth.x.ai/oauth2/token",
                code="bad",
                code_verifier="V" * 64,
            )

    async def test_missing_refresh_token_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # No refresh_token means the OAuth scope was wrong (missing
        # offline_access) — better to surface that immediately than
        # write a half-broken auth.json.
        _patch_httpx_client(
            monkeypatch,
            _FakeResponse(200, {"access_token": "at"}),
        )

        with pytest.raises(
            RuntimeError,
            match="no access_token / refresh_token",
        ):
            await _exchange_code(
                token_endpoint="https://auth.x.ai/oauth2/token",
                code="AUTH",
                code_verifier="V" * 64,
            )


# ---------------------------------------------------------------- #
# _save_auth                                                       #
# ---------------------------------------------------------------- #


class TestSaveAuth:
    def test_writes_expected_payload_and_perms(self, tmp_path: Path) -> None:
        auth_path = tmp_path / "subdir" / "auth.json"
        _save_auth(
            auth_path=auth_path,
            tokens={
                "access_token": "at",
                "refresh_token": "rt",
                "id_token": "it",
            },
            discovery={
                "authorization_endpoint": "https://auth.x.ai/oauth2/authorize",
                "token_endpoint": "https://auth.x.ai/oauth2/token",
            },
        )

        assert auth_path.exists()
        # Parent dir should be 0o700 (created mid-call).
        assert oct(os.stat(auth_path.parent).st_mode & 0o777) == "0o700"
        # File itself should be 0o600 — auth.json carries refresh tokens.
        assert oct(os.stat(auth_path).st_mode & 0o777) == "0o600"

        payload = json.loads(auth_path.read_text())
        assert payload["auth_mode"] == "oauth_pkce"
        assert payload["tokens"]["access_token"] == "at"
        assert payload["tokens"]["refresh_token"] == "rt"
        assert payload["tokens"]["id_token"] == "it"
        assert payload["redirect_uri"] == LOOPBACK_REDIRECT_URI
        assert payload["issuer"] == XAI_OAUTH_ISSUER
        assert payload["base_url"] == DEFAULT_XAI_BASE_URL
        assert "last_refresh" in payload

    def test_optional_id_token(self, tmp_path: Path) -> None:
        auth_path = tmp_path / "auth.json"
        _save_auth(
            auth_path=auth_path,
            tokens={"access_token": "at", "refresh_token": "rt"},
            discovery={
                "authorization_endpoint": "https://auth.x.ai/oauth2/authorize",
                "token_endpoint": "https://auth.x.ai/oauth2/token",
            },
        )
        payload = json.loads(auth_path.read_text())
        assert payload["tokens"]["id_token"] is None

    def test_overwrites_existing_atomically(self, tmp_path: Path) -> None:
        auth_path = tmp_path / "auth.json"
        auth_path.write_text('{"old":"contents"}')

        _save_auth(
            auth_path=auth_path,
            tokens={"access_token": "new-at", "refresh_token": "new-rt"},
            discovery={
                "authorization_endpoint": "https://auth.x.ai/oauth2/authorize",
                "token_endpoint": "https://auth.x.ai/oauth2/token",
            },
        )

        payload = json.loads(auth_path.read_text())
        assert payload["tokens"]["access_token"] == "new-at"
        # No leftover .tmp file.
        assert not (auth_path.with_suffix(auth_path.suffix + ".tmp")).exists()


# ---------------------------------------------------------------- #
# Loopback helpers                                                 #
# ---------------------------------------------------------------- #


class TestLoopback:
    def test_is_port_free_on_unused_port(self) -> None:
        # Pick a wildly-unlikely-to-be-in-use port to avoid flakiness.
        assert is_port_free(port=39999) is True

    def test_is_port_free_returns_false_when_bound(self) -> None:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.listen(1)
        try:
            assert is_port_free(port=port) is False
        finally:
            s.close()

    def test_scope_includes_offline_access(self) -> None:
        # offline_access is the scope that gets us a refresh_token —
        # without it, the credential file would expire after ~1h and
        # the user would have to re-login each session.
        assert "offline_access" in XAI_OAUTH_SCOPE.split()
