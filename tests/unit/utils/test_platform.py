# -*- coding: utf-8 -*-
"""Tests for qwenpaw.utils.platform helpers."""
from __future__ import annotations

import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.utils.platform import (
    auto_disable_sandbox_on_windows,
    is_windows_admin,
)


@pytest.fixture()
def _platform_caplog(caplog: pytest.LogCaptureFixture):
    """Capture logs from qwenpaw.utils.platform.

    The project logger sets propagate=False on the qwenpaw namespace,
    so caplog (which hooks the root logger) won't see records unless we
    temporarily re-enable propagation.
    """
    target = logging.getLogger("qwenpaw")
    old_propagate = target.propagate
    target.propagate = True
    with caplog.at_level("WARNING", logger="qwenpaw.utils.platform"):
        yield
    target.propagate = old_propagate


# ---------------------------------------------------------------------------
# is_windows_admin
# ---------------------------------------------------------------------------


class TestIsWindowsAdmin:
    """Tests for is_windows_admin()."""

    def test_non_windows_returns_true(self) -> None:
        """Non-Windows platforms return True (no-op)."""
        with patch.object(sys, "platform", "linux"):
            assert is_windows_admin() is True

    def test_non_windows_macos_returns_true(self) -> None:
        """On macOS, is_windows_admin() returns True (no-op)."""
        with patch.object(sys, "platform", "darwin"):
            assert is_windows_admin() is True

    def test_windows_admin_returns_true(self) -> None:
        """When Windows IsUserAnAdmin() returns 1 (admin), returns True."""
        mock_ctypes = MagicMock()
        mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = 1
        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(sys.modules, {"ctypes": mock_ctypes}),
        ):
            assert is_windows_admin() is True

    def test_windows_non_admin_returns_false(self) -> None:
        """IsUserAnAdmin() returns 0 (non-admin) -> False."""
        mock_ctypes = MagicMock()
        mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = 0
        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(sys.modules, {"ctypes": mock_ctypes}),
        ):
            assert is_windows_admin() is False

    def test_windows_ctypes_exception_returns_false(self) -> None:
        """When ctypes raises an exception, returns False (conservative)."""
        mock_ctypes = MagicMock()
        mock_ctypes.windll.shell32.IsUserAnAdmin.side_effect = OSError(
            "ctypes failed",
        )
        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(sys.modules, {"ctypes": mock_ctypes}),
        ):
            assert is_windows_admin() is False


# ---------------------------------------------------------------------------
# auto_disable_sandbox_on_windows
# ---------------------------------------------------------------------------


class TestAutoDisableSandboxOnWindows:
    """Tests for auto_disable_sandbox_on_windows()."""

    def test_non_windows_is_noop(self) -> None:
        """On non-Windows platforms, function returns immediately."""
        with patch.object(sys, "platform", "linux"):
            # Should not raise or call load_config
            auto_disable_sandbox_on_windows()

    def test_windows_admin_is_noop(self) -> None:
        """Admin on Windows: no warning logged."""
        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "qwenpaw.utils.platform.is_windows_admin",
                return_value=True,
            ),
        ):
            auto_disable_sandbox_on_windows()

    def test_windows_non_admin_sandbox_disabled_logs_warning(
        self,
        _platform_caplog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When non-admin and sandbox_enabled=True, logs a warning."""
        mock_config = MagicMock()
        mock_config.security.sandbox_enabled = True

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "qwenpaw.utils.platform.is_windows_admin",
                return_value=False,
            ),
            patch(
                "qwenpaw.config.load_config",
                return_value=mock_config,
            ),
        ):
            auto_disable_sandbox_on_windows()

        assert any(
            "sandbox downgraded" in record.message for record in caplog.records
        )

    def test_windows_non_admin_sandbox_already_off_no_warning(
        self,
        _platform_caplog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When non-admin and sandbox_enabled=False, no warning is logged."""
        mock_config = MagicMock()
        mock_config.security.sandbox_enabled = False

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "qwenpaw.utils.platform.is_windows_admin",
                return_value=False,
            ),
            patch(
                "qwenpaw.config.load_config",
                return_value=mock_config,
            ),
        ):
            auto_disable_sandbox_on_windows()

        assert not any(
            "sandbox downgraded" in record.message for record in caplog.records
        )

    def test_windows_non_admin_config_load_failure_logs_warning(
        self,
        _platform_caplog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When load_config raises, logs a warning but does not crash."""
        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "qwenpaw.utils.platform.is_windows_admin",
                return_value=False,
            ),
            patch(
                "qwenpaw.config.load_config",
                side_effect=RuntimeError("config broken"),
            ),
        ):
            auto_disable_sandbox_on_windows()

        assert any(
            "auto-disable check failed" in record.message
            for record in caplog.records
        )
