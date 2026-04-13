# -*- coding: utf-8 -*-
"""Unit tests for CLI HTTP auth helpers."""

from __future__ import annotations

from qwenpaw.app.auth import LOCAL_CLI_TOKEN_HEADER
from qwenpaw.cli.http import _build_auth_headers, client


def test_build_auth_headers_uses_explicit_token(monkeypatch) -> None:
    """Explicit CLI tokens should override host-based auto-auth."""
    monkeypatch.setenv("QWENPAW_API_TOKEN", "explicit-token")

    headers = _build_auth_headers("https://qwenpaw.example.com")

    assert headers == {"Authorization": "Bearer explicit-token"}


def test_build_auth_headers_uses_local_cli_token(monkeypatch) -> None:
    """Local CLI calls should prefer the dedicated local CLI token."""
    monkeypatch.delenv("QWENPAW_API_TOKEN", raising=False)
    monkeypatch.delenv("COPAW_API_TOKEN", raising=False)
    monkeypatch.setattr("qwenpaw.cli.http.has_registered_users", lambda: True)
    monkeypatch.setattr(
        "qwenpaw.cli.http._load_auth_data",
        lambda: {"local_cli_token": "cli-token"},
    )
    monkeypatch.setattr(
        "qwenpaw.cli.http.create_token",
        lambda username: (_ for _ in ()).throw(
            AssertionError(
                f"create_token should not be called for {username}",
            ),
        ),
    )

    headers = _build_auth_headers("http://127.0.0.1:8088")

    assert headers == {LOCAL_CLI_TOKEN_HEADER: "cli-token"}


def test_build_auth_headers_skips_remote_hosts(monkeypatch) -> None:
    """Remote hosts must not trigger implicit local auth."""
    monkeypatch.delenv("QWENPAW_API_TOKEN", raising=False)
    monkeypatch.delenv("COPAW_API_TOKEN", raising=False)
    monkeypatch.setattr("qwenpaw.cli.http.has_registered_users", lambda: True)

    headers = _build_auth_headers("https://qwenpaw.example.com")

    assert not headers


def test_build_auth_headers_skips_unspecified_local_bind_host(
    monkeypatch,
) -> None:
    """0.0.0.0 should not be treated as a trusted local destination host."""
    monkeypatch.delenv("QWENPAW_API_TOKEN", raising=False)
    monkeypatch.delenv("COPAW_API_TOKEN", raising=False)
    monkeypatch.setattr("qwenpaw.cli.http.has_registered_users", lambda: True)

    headers = _build_auth_headers("http://0.0.0.0:8088")

    assert not headers


def test_build_auth_headers_falls_back_to_jwt_for_legacy_auth_data(
    monkeypatch,
) -> None:
    """Older auth files should still support local CLI calls after upgrade."""
    monkeypatch.delenv("QWENPAW_API_TOKEN", raising=False)
    monkeypatch.delenv("COPAW_API_TOKEN", raising=False)
    monkeypatch.setattr("qwenpaw.cli.http.has_registered_users", lambda: True)
    monkeypatch.setattr(
        "qwenpaw.cli.http._load_auth_data",
        lambda: {"jwt_secret": "secret", "user": {"username": "alice"}},
    )
    monkeypatch.setattr(
        "qwenpaw.cli.http.create_token",
        lambda username: f"token-for-{username}",
    )

    headers = _build_auth_headers("http://127.0.0.1:8088")

    assert headers == {"Authorization": "Bearer token-for-alice"}


def test_build_auth_headers_skips_missing_local_cli_credentials(
    monkeypatch,
) -> None:
    """CLI auth must fail closed when no local credential is available."""
    monkeypatch.delenv("QWENPAW_API_TOKEN", raising=False)
    monkeypatch.delenv("COPAW_API_TOKEN", raising=False)
    monkeypatch.setattr("qwenpaw.cli.http.has_registered_users", lambda: True)
    monkeypatch.setattr(
        "qwenpaw.cli.http._load_auth_data",
        lambda: {"user": {"username": "alice"}},
    )
    monkeypatch.setattr(
        "qwenpaw.cli.http.create_token",
        lambda username: (_ for _ in ()).throw(
            AssertionError(
                f"create_token should not be called for {username}",
            ),
        ),
    )

    headers = _build_auth_headers("http://127.0.0.1:8088")

    assert not headers


def test_client_attaches_local_cli_header(monkeypatch) -> None:
    """The CLI client should send the local CLI token for loopback hosts."""
    monkeypatch.delenv("QWENPAW_API_TOKEN", raising=False)
    monkeypatch.delenv("COPAW_API_TOKEN", raising=False)
    monkeypatch.setattr("qwenpaw.cli.http.has_registered_users", lambda: True)
    monkeypatch.setattr(
        "qwenpaw.cli.http._load_auth_data",
        lambda: {"local_cli_token": "cli-token"},
    )

    with client("http://127.0.0.1:8088") as http_client:
        assert http_client.headers[LOCAL_CLI_TOKEN_HEADER] == "cli-token"
