# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Login route behavior when an external authenticator denies access."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app import auth as auth_mod
from qwenpaw.app.auth import (
    ExternalLogin,
    ExternalLoginDenied,
    register_external_identity_resolver,
    register_external_login_authenticator,
)
from qwenpaw.app.routers import auth as auth_router_mod


@pytest.fixture(autouse=True)
def _clear_authenticators():
    auth_mod._external_login_authenticators.clear()
    auth_mod._external_identity_resolvers.clear()
    yield
    auth_mod._external_login_authenticators.clear()
    auth_mod._external_identity_resolvers.clear()


class _FakeRateLimiter:
    def __init__(self) -> None:
        self.attempts: list[tuple[str, str, bool]] = []

    def is_user_locked(self, _username: str) -> bool:
        return False

    def is_ip_locked(self, _ip: str) -> bool:
        return False

    def is_ip_rate_limited(self, _ip: str) -> bool:
        return False

    def record_login_attempt(
        self,
        ip: str,
        username: str,
        success: bool,
    ) -> None:
        self.attempts.append((ip, username, success))


def _build_client(monkeypatch) -> tuple[TestClient, _FakeRateLimiter]:
    limiter = _FakeRateLimiter()
    monkeypatch.setattr(auth_router_mod, "rate_limiter", limiter)
    monkeypatch.setattr(auth_router_mod, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(
        auth_router_mod,
        "authenticate",
        lambda _u, _p, _e: None,
    )

    app = FastAPI()
    app.include_router(auth_router_mod.router, prefix="/api")
    return TestClient(app), limiter


@pytest.mark.p0
def test_login_returns_403_when_external_acl_denies(monkeypatch):
    async def denies(_username, _password):
        raise ExternalLoginDenied("account blocked by console ACL")

    register_external_login_authenticator(denies)
    client, limiter = _build_client(monkeypatch)

    resp = client.post(
        "/api/auth/login",
        json={"username": "blocked@example.com", "password": "correct-pw"},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "account blocked by console ACL"
    assert limiter.attempts == [
        ("testclient", "blocked@example.com", False),
    ]


@pytest.mark.p0
def test_login_returns_401_when_no_authenticator_accepts(monkeypatch):
    async def rejects(_username, _password):
        return None

    register_external_login_authenticator(rejects)
    client, _limiter = _build_client(monkeypatch)

    resp = client.post(
        "/api/auth/login",
        json={"username": "nobody@example.com", "password": "wrong"},
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


@pytest.mark.p0
def test_register_forbidden_when_external_authenticator_present(monkeypatch):
    """With an external user system (e.g. NocoBase), local self-registration
    must be closed so accounts cannot bypass the external provider."""

    async def accepts(_username, _password):
        return "user@example.com"

    register_external_login_authenticator(accepts)
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "true")
    monkeypatch.setattr(auth_router_mod, "has_registered_users", lambda: False)
    register_calls: list = []
    monkeypatch.setattr(
        auth_router_mod,
        "register_user",
        lambda *a, **k: register_calls.append((a, k)) or "token",
    )
    client, _limiter = _build_client(monkeypatch)

    resp = client.post(
        "/api/auth/register",
        json={"username": "new@example.com", "password": "pw"},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == (
        "Registration is managed by the external identity provider"
    )
    assert not register_calls


@pytest.mark.p0
def test_login_returns_provider_token_from_external_authenticator(
    monkeypatch,
):
    """When the external provider (NocoBase) returns its own token, the
    login route passes it through instead of minting a QwenPaw token."""

    async def nb_login(_username, _password):
        return ExternalLogin(
            identity="admin@nocobase.com",
            token="nb-jwt-token",
        )

    register_external_login_authenticator(nb_login)
    client, _limiter = _build_client(monkeypatch)

    resp = client.post(
        "/api/auth/login",
        json={"username": "admin@nocobase.com", "password": "pw"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "token": "nb-jwt-token",
        "username": "admin@nocobase.com",
    }


@pytest.mark.p0
def test_login_mints_local_token_when_provider_returns_none(monkeypatch):
    """Legacy authenticators (identity only) keep the old behavior."""

    async def legacy_login(_username, _password):
        return "someone@example.com"

    register_external_login_authenticator(legacy_login)
    minted: list = []
    monkeypatch.setattr(
        auth_router_mod,
        "create_token",
        lambda identity, _exp: minted.append(identity) or "local-token",
    )
    client, _limiter = _build_client(monkeypatch)

    resp = client.post(
        "/api/auth/login",
        json={"username": "someone@example.com", "password": "pw"},
    )

    assert resp.status_code == 200
    assert resp.json()["token"] == "local-token"
    assert minted == ["someone@example.com"]


@pytest.mark.p0
def test_verify_uses_external_resolver_when_provider_owns_tokens(
    monkeypatch,
):
    """`/auth/verify` must accept provider tokens (verified externally)
    and reject locally minted ones when the provider owns the token system."""

    async def login_auth(_username, _password):
        return "someone@example.com"

    async def resolver(request):
        if request.headers.get("Authorization") == "Bearer nb-token":
            return "nb-user@example.com"
        return None

    register_external_login_authenticator(login_auth)
    register_external_identity_resolver(resolver)
    client, _limiter = _build_client(monkeypatch)

    resp = client.get(
        "/api/auth/verify",
        headers={"Authorization": "Bearer nb-token"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"valid": True, "username": "nb-user@example.com"}

    resp = client.get(
        "/api/auth/verify",
        headers={"Authorization": "Bearer local-looking-token"},
    )
    assert resp.status_code == 401
