# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for :mod:`qwenpaw.providers.xai_auth`.

Covers the disk-loading invariants, JWT exp decoding, mtime-tracked
hot-reload, and the refresh flow's success / re-login-required paths.
No network calls — httpx is stubbed at the module level.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from qwenpaw.providers import xai_auth as xai_auth_module
from qwenpaw.providers.xai_auth import (
    DEFAULT_XAI_BASE_URL,
    REFRESH_SAFETY_MARGIN_S,
    XAI_OAUTH_CLIENT_ID,
    XaiAuth,
    XaiAuthError,
    XaiCredential,
    _decode_jwt_claims,
    _decode_jwt_exp_ms,
    _resolve_auth_path,
)


# ---------------------------------------------------------------- #
# Helpers                                                          #
# ---------------------------------------------------------------- #


def _make_jwt(exp_seconds_from_now: int = 3600) -> str:
    """Build a syntactically-valid JWT with a given exp claim.

    The signature segment is junk — we never verify, only decode.
    """
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none"}).encode(),
    ).rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {"exp": int(time.time()) + exp_seconds_from_now},
        ).encode(),
    ).rstrip(b"=")
    sig = base64.urlsafe_b64encode(b"sig").rstrip(b"=")
    return b".".join([header, payload, sig]).decode("ascii")


def _write_auth_file(
    path: Path,
    *,
    access_token: str | None = None,
    refresh_token: str = "rt-original",
    id_token: str | None = "id-original",
    token_endpoint: str = "https://auth.x.ai/oauth2/token",
    drop_keys: tuple[str, ...] = (),
) -> Path:
    """Write a minimal valid auth.json — caller may drop keys to
    exercise validation paths.
    """
    if access_token is None:
        access_token = _make_jwt()
    raw: dict[str, Any] = {
        "auth_mode": "oauth_pkce",
        "tokens": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "id_token": id_token,
        },
        "discovery": {
            "authorization_endpoint": "https://auth.x.ai/oauth2/authorize",
            "token_endpoint": token_endpoint,
        },
        "redirect_uri": "http://127.0.0.1:56121/callback",
        "last_refresh": "2026-05-16T12:00:00Z",
    }
    for key in drop_keys:
        # Walk a dotted key like ``tokens.access_token`` and delete it.
        cur: Any = raw
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur[part]
        cur.pop(parts[-1], None)
    path.write_text(json.dumps(raw, indent=2))
    return path


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        body: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self._body = body or {}
        self.text = json.dumps(self._body)

    def json(self) -> dict[str, Any]:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request(
                    "POST",
                    "https://auth.x.ai/oauth2/token",
                ),
                response=httpx.Response(self.status_code),
            )


class _FakeAsyncClient:
    """Drop-in stand-in for ``httpx.AsyncClient`` used in _refresh()."""

    instances: list["_FakeAsyncClient"] = []

    def __init__(self, *, response: _FakeResponse, **_: Any) -> None:
        self._response = response
        self.posts: list[dict[str, Any]] = []
        _FakeAsyncClient.instances.append(self)

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.posts.append({"url": url, **kwargs})
        return self._response


def _patch_httpx_client(
    monkeypatch: pytest.MonkeyPatch,
    response: _FakeResponse,
) -> None:
    """Replace httpx.AsyncClient inside xai_auth with our fake."""
    _FakeAsyncClient.instances.clear()

    def _factory(*_args: Any, **kwargs: Any) -> _FakeAsyncClient:
        return _FakeAsyncClient(response=response, **kwargs)

    monkeypatch.setattr(xai_auth_module.httpx, "AsyncClient", _factory)


# ---------------------------------------------------------------- #
# JWT helpers                                                      #
# ---------------------------------------------------------------- #


class TestJwtDecoding:
    def test_decode_claims_valid_jwt(self) -> None:
        jwt = _make_jwt(3600)
        claims = _decode_jwt_claims(jwt)
        assert claims is not None
        assert "exp" in claims
        assert isinstance(claims["exp"], int)

    def test_decode_claims_returns_none_on_garbage(self) -> None:
        assert _decode_jwt_claims("not.a.jwt") is None
        assert _decode_jwt_claims("") is None
        assert _decode_jwt_claims("only-one-segment") is None

    def test_decode_exp_ms_returns_milliseconds(self) -> None:
        jwt = _make_jwt(3600)
        exp_ms = _decode_jwt_exp_ms(jwt)
        now_ms = int(time.time() * 1000)
        assert exp_ms is not None
        # Within a few seconds of now+3600s, in ms.
        assert abs(exp_ms - (now_ms + 3600 * 1000)) < 10_000

    def test_decode_exp_ms_handles_missing_exp(self) -> None:
        header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=")
        payload = base64.urlsafe_b64encode(b"{}").rstrip(b"=")
        sig = base64.urlsafe_b64encode(b"sig").rstrip(b"=")
        jwt = b".".join([header, payload, sig]).decode()
        assert _decode_jwt_exp_ms(jwt) is None


# ---------------------------------------------------------------- #
# Path resolution                                                  #
# ---------------------------------------------------------------- #


class TestResolveAuthPath:
    def test_default_under_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XAI_HOME", raising=False)
        monkeypatch.setenv("HOME", "/tmp/fakehome")
        path = _resolve_auth_path()
        assert path == Path("/tmp/fakehome/.xai/auth.json")

    def test_honors_xai_home_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("XAI_HOME", str(tmp_path))
        path = _resolve_auth_path()
        assert path == tmp_path / "auth.json"


# ---------------------------------------------------------------- #
# XaiCredential                                                    #
# ---------------------------------------------------------------- #


class TestXaiCredential:
    def test_seconds_until_expiry_clamps_to_zero(self) -> None:
        cred = XaiCredential(
            access_token="t",
            refresh_token="r",
            id_token=None,
            expires_at_ms=int(time.time() * 1000) - 5000,
            token_endpoint="https://auth.x.ai/oauth2/token",
            auth_path=Path("/tmp/x"),
        )
        assert cred.seconds_until_expiry == 0
        assert cred.needs_refresh is True

    def test_needs_refresh_true_within_safety_margin(self) -> None:
        cred = XaiCredential(
            access_token="t",
            refresh_token="r",
            id_token=None,
            expires_at_ms=int(time.time() * 1000)
            + (REFRESH_SAFETY_MARGIN_S - 10) * 1000,
            token_endpoint="https://auth.x.ai/oauth2/token",
            auth_path=Path("/tmp/x"),
        )
        assert cred.needs_refresh is True

    def test_needs_refresh_false_when_well_within_validity(self) -> None:
        cred = XaiCredential(
            access_token="t",
            refresh_token="r",
            id_token=None,
            expires_at_ms=int(time.time() * 1000) + 3600 * 1000,
            token_endpoint="https://auth.x.ai/oauth2/token",
            auth_path=Path("/tmp/x"),
        )
        assert cred.needs_refresh is False


# ---------------------------------------------------------------- #
# XaiAuth._load                                                    #
# ---------------------------------------------------------------- #


class TestXaiAuthLoad:
    def test_raises_file_not_found_when_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="xAI auth file not found"):
            XaiAuth(auth_path=tmp_path / "does-not-exist.json")

    def test_loads_valid_file(self, tmp_path: Path) -> None:
        path = _write_auth_file(tmp_path / "auth.json")
        auth = XaiAuth(auth_path=path)
        creds = auth._creds
        assert creds is not None
        assert creds.refresh_token == "rt-original"
        assert creds.id_token == "id-original"
        assert creds.token_endpoint == "https://auth.x.ai/oauth2/token"
        assert creds.auth_mode == "oauth_pkce"

    def test_missing_access_token_rejected(self, tmp_path: Path) -> None:
        path = _write_auth_file(
            tmp_path / "auth.json",
            drop_keys=("tokens.access_token",),
        )
        with pytest.raises(ValueError, match="missing access_token"):
            XaiAuth(auth_path=path)

    def test_missing_refresh_token_rejected(self, tmp_path: Path) -> None:
        path = _write_auth_file(
            tmp_path / "auth.json",
            drop_keys=("tokens.refresh_token",),
        )
        with pytest.raises(ValueError, match="missing access_token"):
            XaiAuth(auth_path=path)

    def test_missing_token_endpoint_rejected(self, tmp_path: Path) -> None:
        path = _write_auth_file(
            tmp_path / "auth.json",
            drop_keys=("discovery.token_endpoint",),
        )
        with pytest.raises(ValueError, match="discovery.token_endpoint"):
            XaiAuth(auth_path=path)

    def test_falls_back_to_mtime_expiry_when_not_a_jwt(
        self,
        tmp_path: Path,
    ) -> None:
        path = _write_auth_file(
            tmp_path / "auth.json",
            access_token="not-a-jwt",
        )
        auth = XaiAuth(auth_path=path)
        creds = auth._creds
        assert creds is not None
        # Fallback adds 1h to mtime, so expiry is ~1h from now.
        now_ms = int(time.time() * 1000)
        assert (
            (now_ms + 3500 * 1000)
            < creds.expires_at_ms
            < (now_ms + 3700 * 1000)
        )


# ---------------------------------------------------------------- #
# XaiAuth.ensure_fresh + hot-reload                                #
# ---------------------------------------------------------------- #


class TestEnsureFreshAndReload:
    async def test_returns_cached_when_well_within_validity(
        self,
        tmp_path: Path,
    ) -> None:
        path = _write_auth_file(tmp_path / "auth.json")
        auth = XaiAuth(auth_path=path)
        creds_a = await auth.ensure_fresh()
        creds_b = await auth.ensure_fresh()
        # Same access_token because no refresh fired.
        assert creds_a.access_token == creds_b.access_token

    async def test_reloads_when_mtime_advances(
        self,
        tmp_path: Path,
    ) -> None:
        path = _write_auth_file(tmp_path / "auth.json")
        auth = XaiAuth(auth_path=path)
        await auth.ensure_fresh()
        # Simulate a fresh `qwenpaw xai login` overwriting on disk.
        new_token = _make_jwt(7200)
        _write_auth_file(
            path,
            access_token=new_token,
            refresh_token="rt-rotated",
        )
        # Advance mtime so the hot-reload check triggers.
        new_mtime = os.stat(path).st_mtime + 5
        os.utime(path, (new_mtime, new_mtime))
        creds = await auth.ensure_fresh()
        assert creds.access_token == new_token
        assert creds.refresh_token == "rt-rotated"

    async def test_refresh_triggered_when_near_expiry(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Stale token: 60s remaining — within REFRESH_SAFETY_MARGIN_S.
        stale = _make_jwt(60)
        path = _write_auth_file(tmp_path / "auth.json", access_token=stale)
        auth = XaiAuth(auth_path=path)

        fresh = _make_jwt(3600)
        _patch_httpx_client(
            monkeypatch,
            _FakeResponse(
                200,
                {
                    "access_token": fresh,
                    "refresh_token": "rt-new",
                    "id_token": "id-new",
                },
            ),
        )

        creds = await auth.ensure_fresh()

        assert creds.access_token == fresh
        assert creds.refresh_token == "rt-new"
        assert creds.id_token == "id-new"
        # Confirm we hit the correct endpoint with the right grant.
        assert len(_FakeAsyncClient.instances) == 1
        post = _FakeAsyncClient.instances[0].posts[0]
        assert post["url"] == "https://auth.x.ai/oauth2/token"
        assert post["data"]["grant_type"] == "refresh_token"
        assert post["data"]["client_id"] == XAI_OAUTH_CLIENT_ID
        assert post["data"]["refresh_token"] == "rt-original"
        # File on disk should now have the new tokens.
        on_disk = json.loads(path.read_text())
        assert on_disk["tokens"]["access_token"] == fresh
        assert on_disk["tokens"]["refresh_token"] == "rt-new"

    async def test_refresh_preserves_old_refresh_token_when_omitted(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Some token endpoints reuse the same refresh_token across
        # refreshes — guard against accidentally clearing it.
        stale = _make_jwt(60)
        path = _write_auth_file(tmp_path / "auth.json", access_token=stale)
        auth = XaiAuth(auth_path=path)

        fresh = _make_jwt(3600)
        _patch_httpx_client(
            monkeypatch,
            _FakeResponse(200, {"access_token": fresh}),
        )

        creds = await auth.ensure_fresh()

        assert creds.refresh_token == "rt-original"
        assert creds.id_token == "id-original"

    @pytest.mark.parametrize("status", [400, 401, 403])
    async def test_refresh_4xx_raises_relogin_required(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        status: int,
    ) -> None:
        stale = _make_jwt(60)
        path = _write_auth_file(tmp_path / "auth.json", access_token=stale)
        auth = XaiAuth(auth_path=path)

        _patch_httpx_client(
            monkeypatch,
            _FakeResponse(status, {"error": "invalid_grant"}),
        )

        with pytest.raises(XaiAuthError) as exc_info:
            await auth.ensure_fresh()
        assert exc_info.value.relogin_required is True

    async def test_refresh_no_access_token_in_response_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stale = _make_jwt(60)
        path = _write_auth_file(tmp_path / "auth.json", access_token=stale)
        auth = XaiAuth(auth_path=path)

        _patch_httpx_client(monkeypatch, _FakeResponse(200, {}))

        with pytest.raises(RuntimeError, match="no access_token"):
            await auth.ensure_fresh()

    async def test_concurrent_ensure_fresh_only_refreshes_once(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Single-flight defense: two tasks that both notice the token
        # is near expiry should NOT both POST a refresh.  xAI rotates
        # refresh_token per call, so a double-refresh invalidates the
        # first response's token and leaves auth.json desynced.
        stale = _make_jwt(60)
        path = _write_auth_file(tmp_path / "auth.json", access_token=stale)
        auth = XaiAuth(auth_path=path)

        fresh = _make_jwt(3600)
        _patch_httpx_client(
            monkeypatch,
            _FakeResponse(
                200,
                {"access_token": fresh, "refresh_token": "rt-new"},
            ),
        )

        # Fire two ensure_fresh() calls simultaneously.
        results = await asyncio.gather(
            auth.ensure_fresh(),
            auth.ensure_fresh(),
        )

        # Both got the same fresh creds.
        assert results[0].access_token == fresh
        assert results[1].access_token == fresh
        # And the refresh POST fired exactly once.
        assert len(_FakeAsyncClient.instances) == 1
        assert len(_FakeAsyncClient.instances[0].posts) == 1


# ---------------------------------------------------------------- #
# Misc surface                                                     #
# ---------------------------------------------------------------- #


class TestPublicSurface:
    async def test_auth_headers_returns_bearer(self, tmp_path: Path) -> None:
        path = _write_auth_file(tmp_path / "auth.json")
        auth = XaiAuth(auth_path=path)
        headers = await auth.auth_headers()
        assert headers.keys() == {"Authorization"}
        assert headers["Authorization"].startswith("Bearer ")

    def test_base_url_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("QWENPAW_XAI_BASE_URL", raising=False)
        path = _write_auth_file(tmp_path / "auth.json")
        auth = XaiAuth(auth_path=path)
        assert auth.base_url == DEFAULT_XAI_BASE_URL

    def test_base_url_env_override(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("QWENPAW_XAI_BASE_URL", "https://mirror.example/v1")
        path = _write_auth_file(tmp_path / "auth.json")
        auth = XaiAuth(auth_path=path)
        assert auth.base_url == "https://mirror.example/v1"

    def test_reload_rereads_disk(self, tmp_path: Path) -> None:
        path = _write_auth_file(tmp_path / "auth.json")
        auth = XaiAuth(auth_path=path)
        new_token = _make_jwt(7200)
        _write_auth_file(path, access_token=new_token, refresh_token="rt-x")
        creds = auth.reload()
        assert creds.access_token == new_token
        assert creds.refresh_token == "rt-x"

    def test_save_writes_atomic_and_chmod_600(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Drive _save() indirectly via a successful refresh, then check
        # the resulting file mode.
        async def _go() -> None:
            stale = _make_jwt(60)
            path = _write_auth_file(tmp_path / "auth.json", access_token=stale)
            auth = XaiAuth(auth_path=path)
            fresh = _make_jwt(3600)
            _patch_httpx_client(
                monkeypatch,
                _FakeResponse(200, {"access_token": fresh}),
            )
            await auth.ensure_fresh()
            mode = os.stat(path).st_mode & 0o777
            assert mode == 0o600

        asyncio.run(_go())


# ---------------------------------------------------------------- #
# XaiAuthError                                                     #
# ---------------------------------------------------------------- #


class TestXaiAuthError:
    def test_default_no_relogin_required(self) -> None:
        err = XaiAuthError("bad")
        assert err.relogin_required is False
        assert str(err) == "bad"

    def test_relogin_required_flag(self) -> None:
        err = XaiAuthError("bad", relogin_required=True)
        assert err.relogin_required is True
