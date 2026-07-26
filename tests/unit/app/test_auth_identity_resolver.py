# -*- coding: utf-8 -*-
# pylint: disable=unnecessary-lambda,protected-access
"""Unit tests for the external identity resolver registry in auth.py."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request as _Req
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from qwenpaw.app import auth as auth_mod
from qwenpaw.app.auth import (
    ExternalLogin,
    ExternalLoginDenied,
    ResolvedIdentity,
    _external_identity_resolvers,
    _external_login_authenticators,
    authenticate_external_login,
    _resolve_external_identity,
    has_external_identity_resolvers,
    register_external_login_authenticator,
    register_external_identity_resolver,
    unregister_external_login_authenticator,
    unregister_external_identity_resolver,
)


@pytest.fixture(autouse=True)
def _clear_resolvers():
    _external_identity_resolvers.clear()
    _external_login_authenticators.clear()
    yield
    _external_identity_resolvers.clear()
    _external_login_authenticators.clear()


def test_register_and_has():
    assert has_external_identity_resolvers() is False

    async def r(_request):
        return None

    register_external_identity_resolver(r)
    assert has_external_identity_resolvers() is True
    unregister_external_identity_resolver(r)
    assert has_external_identity_resolvers() is False


def test_register_is_idempotent():
    async def r(_request):
        return None

    register_external_identity_resolver(r)
    register_external_identity_resolver(r)
    assert len(_external_identity_resolvers) == 1


async def test_resolve_returns_first_non_none():
    async def r_none(_request):
        return None

    async def r_alice(_request):
        return ResolvedIdentity(sender_id="alice@example.com")

    register_external_identity_resolver(r_none)
    register_external_identity_resolver(r_alice)
    result = await _resolve_external_identity(object())
    assert result.sender_id == "alice@example.com"


async def test_resolve_swallows_exceptions_and_continues():
    async def r_boom(_request):
        raise RuntimeError("boom")

    async def r_ok(_request):
        return ResolvedIdentity(sender_id="bob@example.com")

    register_external_identity_resolver(r_boom)
    register_external_identity_resolver(r_ok)
    result = await _resolve_external_identity(object())
    assert result.sender_id == "bob@example.com"


async def test_resolve_all_none():
    async def r(_request):
        return None

    register_external_identity_resolver(r)
    assert await _resolve_external_identity(object()) is None


async def test_external_login_returns_first_authenticated_identity():
    async def first(_username, _password):
        return None

    async def second(username, password):
        assert username == "admin@nocobase.com"
        assert password == "admin123"
        return "admin@nocobase.com"

    register_external_login_authenticator(first)
    register_external_login_authenticator(second)
    result = await authenticate_external_login(
        "admin@nocobase.com",
        "admin123",
    )
    assert result == ExternalLogin(identity="admin@nocobase.com")


async def test_external_login_passes_through_provider_token():
    async def nb_login(_username, _password):
        return ExternalLogin(
            identity="admin@nocobase.com",
            token="nb-jwt-token",
        )

    register_external_login_authenticator(nb_login)
    result = await authenticate_external_login(
        "admin@nocobase.com",
        "admin123",
    )
    assert result is not None
    assert result.identity == "admin@nocobase.com"
    assert result.token == "nb-jwt-token"


async def test_external_login_swallows_exceptions_and_continues():
    async def boom(_username, _password):
        raise RuntimeError("nocobase down")

    async def ok(_username, _password):
        return "admin@nocobase.com"

    register_external_login_authenticator(boom)
    register_external_login_authenticator(ok)
    result = await authenticate_external_login(
        "admin@nocobase.com",
        "admin123",
    )
    assert result == ExternalLogin(identity="admin@nocobase.com")


async def test_external_login_denied_propagates_to_caller():
    calls = {"later": 0}

    async def denies(_username, _password):
        raise ExternalLoginDenied("account not allowed")

    async def never_reached(_username, _password):
        calls["later"] += 1
        return "someone@example.com"

    register_external_login_authenticator(denies)
    register_external_login_authenticator(never_reached)
    with pytest.raises(ExternalLoginDenied) as excinfo:
        await authenticate_external_login("blocked@example.com", "pw")
    assert excinfo.value.detail == "account not allowed"
    assert calls["later"] == 0


async def test_external_login_unregisters():
    async def login(_username, _password):
        return "admin@nocobase.com"

    register_external_login_authenticator(login)
    unregister_external_login_authenticator(login)
    assert (
        await authenticate_external_login("admin@nocobase.com", "admin123")
        is None
    )


class _FakeSecurity:
    def __init__(self) -> None:
        self.allow_no_auth_hosts: list[str] = []


class _FakeConfig:
    security = _FakeSecurity()


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(auth_mod, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(
        auth_mod,
        "_get_config_cached",
        lambda: (_FakeConfig(), []),
    )

    async def whoami(request):
        return JSONResponse(
            {
                "user": getattr(request.state, "user", None),
                "roles": getattr(request.state, "user_roles", None),
            },
        )

    app = Starlette(
        routes=[Route("/api/console/chat", whoami, methods=["POST"])],
    )
    app.add_middleware(auth_mod.AuthMiddleware)
    return TestClient(app)


def test_middleware_uses_resolver_when_identity_present(monkeypatch):
    async def r(request):
        if request.headers.get("X-NocoBase-Token"):
            return ResolvedIdentity(
                sender_id="carol@example.com",
                roles=["admin"],
            )
        return None

    register_external_identity_resolver(r)
    client = _build_client(monkeypatch)
    resp = client.post(
        "/api/console/chat",
        headers={"X-NocoBase-Token": "tok"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"user": "carol@example.com", "roles": ["admin"]}


def test_middleware_401_when_resolver_returns_none(monkeypatch):
    async def r(_request):
        return None

    register_external_identity_resolver(r)
    client = _build_client(monkeypatch)
    resp = client.post("/api/console/chat")
    assert resp.status_code == 401


def test_middleware_401_when_no_resolver(monkeypatch):
    client = _build_client(monkeypatch)
    resp = client.post("/api/console/chat")
    assert resp.status_code == 401


def test_middleware_rejects_unresolvable_bearer_token(monkeypatch):
    async def r(request):
        if request.headers.get("Authorization") == "Bearer valid-nb":
            return ResolvedIdentity(sender_id="u@x.io")
        return None

    register_external_identity_resolver(r)
    client = _build_client(monkeypatch)
    resp = client.post(
        "/api/console/chat",
        headers={"Authorization": "Bearer garbage-local-token"},
    )
    assert resp.status_code == 401


def _make_request(path="/api/console/chat", method="POST") -> _Req:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "client": ("203.0.113.5", 12345),
        "query_string": b"",
    }
    return _Req(scope)


def test_skip_auth_enforced_when_resolver_present(monkeypatch):
    monkeypatch.setattr(auth_mod, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(
        auth_mod,
        "_get_config_cached",
        lambda: (_FakeConfig(), []),
    )

    async def r(_request):
        return None

    register_external_identity_resolver(r)
    assert auth_mod.AuthMiddleware._should_skip_auth(_make_request()) is False


def test_skip_auth_fails_closed_when_no_resolver(monkeypatch):
    monkeypatch.setattr(auth_mod, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(
        auth_mod,
        "_get_config_cached",
        lambda: (_FakeConfig(), []),
    )
    assert auth_mod.AuthMiddleware._should_skip_auth(_make_request()) is False


def test_skip_auth_public_path_always_skipped(monkeypatch):
    monkeypatch.setattr(auth_mod, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(
        auth_mod,
        "_get_config_cached",
        lambda: (_FakeConfig(), []),
    )

    async def r(_request):
        return None

    register_external_identity_resolver(r)
    req = _make_request(path="/api/auth/login", method="POST")
    assert auth_mod.AuthMiddleware._should_skip_auth(req) is True
