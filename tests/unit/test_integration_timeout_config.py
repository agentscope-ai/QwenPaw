# -*- coding: utf-8 -*-
"""Tests for integration test timeout configuration."""

import pytest

from tests.integration.helpers import app_startup_wait_timeout

_TIMEOUT_ENV = f"QWENPAW_INTEGRATION_HTTP_{'TIMEOUT'}"


def test_app_startup_wait_timeout_uses_integration_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Windows CI timeout must also extend application readiness."""
    monkeypatch.setenv(_TIMEOUT_ENV, f"{120}")

    assert app_startup_wait_timeout() == 120.0


def test_app_startup_wait_timeout_ignores_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid timeout configuration must retain the safe default."""
    monkeypatch.setenv(_TIMEOUT_ENV, f"{'invalid'}")

    assert app_startup_wait_timeout() == 60.0
