# -*- coding: utf-8 -*-
"""Tests for the unauthenticated public-bind safety gate in ``qwenpaw app``.

QwenPaw's HTTP gateway can invoke host-affecting tools. When
``QWENPAW_AUTH_ENABLED`` is unset, binding to a non-loopback host
exposes those tools without an authentication gate. ``app_cmd`` must
refuse this configuration unless the operator opts in.
"""
# pylint: disable=protected-access,redefined-outer-name

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from qwenpaw.cli import app_cmd as app_cmd_mod


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QWENPAW_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("QWENPAW_ALLOW_UNAUTH_PUBLIC", raising=False)


# ---------------------------------------------------------------------------
# _host_is_loopback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.5.5.5", "::1", "localhost", "LOCALHOST"],
)
def test_host_is_loopback_true(host: str) -> None:
    assert app_cmd_mod._host_is_loopback(host) is True


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "::", "1.2.3.4", "192.168.1.10", "example.com", ""],
)
def test_host_is_loopback_false(host: str) -> None:
    assert app_cmd_mod._host_is_loopback(host) is False


# ---------------------------------------------------------------------------
# _enforce_unauth_public_bind_safety
# ---------------------------------------------------------------------------


def _patch_auth(enabled: bool):
    return patch.object(
        app_cmd_mod,
        "_enforce_unauth_public_bind_safety",
        wraps=app_cmd_mod._enforce_unauth_public_bind_safety,
    ), patch("qwenpaw.app.auth.is_auth_enabled", return_value=enabled)


def test_loopback_bind_passes_without_auth() -> None:
    with patch("qwenpaw.app.auth.is_auth_enabled", return_value=False):
        # Should not raise / exit.
        app_cmd_mod._enforce_unauth_public_bind_safety("127.0.0.1", False)


def test_public_bind_with_auth_enabled_passes() -> None:
    with patch("qwenpaw.app.auth.is_auth_enabled", return_value=True):
        app_cmd_mod._enforce_unauth_public_bind_safety("0.0.0.0", False)


def test_public_bind_with_explicit_flag_passes() -> None:
    with patch("qwenpaw.app.auth.is_auth_enabled", return_value=False):
        app_cmd_mod._enforce_unauth_public_bind_safety("0.0.0.0", True)


def test_public_bind_with_env_override_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_ALLOW_UNAUTH_PUBLIC", "true")
    with patch("qwenpaw.app.auth.is_auth_enabled", return_value=False):
        app_cmd_mod._enforce_unauth_public_bind_safety("0.0.0.0", False)


def test_public_bind_without_auth_or_override_exits() -> None:
    with patch("qwenpaw.app.auth.is_auth_enabled", return_value=False):
        with pytest.raises(SystemExit) as excinfo:
            app_cmd_mod._enforce_unauth_public_bind_safety("0.0.0.0", False)
        assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_app_cmd_refuses_public_bind_without_auth(runner: CliRunner) -> None:
    with (
        patch("qwenpaw.app.auth.is_auth_enabled", return_value=False),
        patch(
            "uvicorn.run",
        ) as mock_run,
    ):
        result = runner.invoke(
            app_cmd_mod.app_cmd,
            ["--host", "0.0.0.0", "--port", "8088"],
        )
    assert result.exit_code == 2
    assert "Refusing to bind" in result.output
    assert "QWENPAW_AUTH_ENABLED" in result.output
    assert "--allow-unauth-public" in result.output
    mock_run.assert_not_called()


def test_app_cmd_loopback_default_runs(runner: CliRunner) -> None:
    with (
        patch("qwenpaw.app.auth.is_auth_enabled", return_value=False),
        patch(
            "uvicorn.run",
        ) as mock_run,
        patch("qwenpaw.cli.app_cmd.write_last_api"),
        patch(
            "qwenpaw.cli.app_cmd.setup_logger",
        ),
    ):
        result = runner.invoke(
            app_cmd_mod.app_cmd,
            ["--host", "127.0.0.1", "--port", "8088"],
        )
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()


def test_app_cmd_public_bind_with_flag_runs(runner: CliRunner) -> None:
    with (
        patch("qwenpaw.app.auth.is_auth_enabled", return_value=False),
        patch(
            "uvicorn.run",
        ) as mock_run,
        patch("qwenpaw.cli.app_cmd.write_last_api"),
        patch(
            "qwenpaw.cli.app_cmd.setup_logger",
        ),
    ):
        result = runner.invoke(
            app_cmd_mod.app_cmd,
            [
                "--host",
                "0.0.0.0",
                "--port",
                "8088",
                "--allow-unauth-public",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "WARNING" in result.output
    mock_run.assert_called_once()


def test_app_cmd_public_bind_with_auth_env_runs(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "true")
    with (
        patch("uvicorn.run") as mock_run,
        patch(
            "qwenpaw.cli.app_cmd.write_last_api",
        ),
        patch("qwenpaw.cli.app_cmd.setup_logger"),
    ):
        result = runner.invoke(
            app_cmd_mod.app_cmd,
            ["--host", "0.0.0.0", "--port", "8088"],
        )
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
