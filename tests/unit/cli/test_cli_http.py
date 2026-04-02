# -*- coding: utf-8 -*-
"""Unit tests for CLI HTTP auth helpers."""

from __future__ import annotations

from copaw.cli.http import _build_auth_headers, client


def test_build_auth_headers_uses_explicit_token(monkeypatch) -> None:
    """Explicit CLI tokens should override host-based auto-auth."""
    monkeypatch.setenv("COPAW_API_TOKEN", "explicit-token")

    headers = _build_auth_headers("https://copaw.example.com")

    assert headers == {"Authorization": "Bearer explicit-token"}


def test_build_auth_headers_uses_local_auth_state(monkeypatch) -> None:
    """Local CLI calls should mint a bearer token from local auth state."""
    monkeypatch.delenv("COPAW_API_TOKEN", raising=False)
    monkeypatch.setattr("copaw.cli.http.is_auth_enabled", lambda: True)
    monkeypatch.setattr("copaw.cli.http.has_registered_users", lambda: True)
    monkeypatch.setattr(
        "copaw.cli.http._load_auth_data",
        lambda: {"jwt_secret": "secret", "user": {"username": "alice"}},
    )
    monkeypatch.setattr(
        "copaw.cli.http.create_token",
        lambda username: f"token-for-{username}",
    )

    headers = _build_auth_headers("http://127.0.0.1:8088")

    assert headers == {"Authorization": "Bearer token-for-alice"}


def test_build_auth_headers_skips_remote_hosts(monkeypatch) -> None:
    """Remote hosts must not trigger implicit local auth."""
    monkeypatch.delenv("COPAW_API_TOKEN", raising=False)
    monkeypatch.setattr("copaw.cli.http.is_auth_enabled", lambda: True)
    monkeypatch.setattr("copaw.cli.http.has_registered_users", lambda: True)

    headers = _build_auth_headers("https://copaw.example.com")

    assert not headers


def test_build_auth_headers_skips_unspecified_local_bind_host(
    monkeypatch,
) -> None:
    """0.0.0.0 should not be treated as a trusted local destination host."""
    monkeypatch.delenv("COPAW_API_TOKEN", raising=False)
    monkeypatch.setattr("copaw.cli.http.is_auth_enabled", lambda: True)
    monkeypatch.setattr("copaw.cli.http.has_registered_users", lambda: True)

    headers = _build_auth_headers("http://0.0.0.0:8088")

    assert not headers


def test_build_auth_headers_skips_missing_jwt_secret(monkeypatch) -> None:
    """CLI auth must not mutate local auth state without a JWT secret."""
    monkeypatch.delenv("COPAW_API_TOKEN", raising=False)
    monkeypatch.setattr("copaw.cli.http.is_auth_enabled", lambda: True)
    monkeypatch.setattr("copaw.cli.http.has_registered_users", lambda: True)
    monkeypatch.setattr(
        "copaw.cli.http._load_auth_data",
        lambda: {"user": {"username": "alice"}},
    )
    monkeypatch.setattr(
        "copaw.cli.http.create_token",
        lambda username: (_ for _ in ()).throw(
            AssertionError(
                f"create_token should not be called for {username}",
            ),
        ),
    )

    headers = _build_auth_headers("http://127.0.0.1:8088")

    assert not headers


def test_client_attaches_local_auth_header(monkeypatch) -> None:
    """The CLI client should send the generated local bearer token."""
    monkeypatch.delenv("COPAW_API_TOKEN", raising=False)
    monkeypatch.setattr("copaw.cli.http.is_auth_enabled", lambda: True)
    monkeypatch.setattr("copaw.cli.http.has_registered_users", lambda: True)
    monkeypatch.setattr(
        "copaw.cli.http._load_auth_data",
        lambda: {"jwt_secret": "secret", "user": {"username": "alice"}},
    )
    monkeypatch.setattr(
        "copaw.cli.http.create_token",
        lambda username: f"token-for-{username}",
    )

    with client("http://127.0.0.1:8088") as http_client:
        assert http_client.headers["Authorization"] == "Bearer token-for-alice"
