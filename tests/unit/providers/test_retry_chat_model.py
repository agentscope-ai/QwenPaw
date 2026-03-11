# -*- coding: utf-8 -*-
"""Unit tests for _is_retryable() in retry_chat_model.

Verifies that the retryable-error detection covers:
- HTTP status codes                  (existing)
- httpx transport-level exceptions   (new)
- Python built-in network exceptions (new)
- Non-retryable exceptions are rejected
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from copaw.providers.retry_chat_model import _is_retryable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _exc_with_status(code: int) -> Exception:
    """Create a generic exception with a ``status_code`` attribute."""
    exc = Exception(f"HTTP {code}")
    exc.status_code = code  # type: ignore[attr-defined]
    return exc


# ---------------------------------------------------------------------------
# Tests: HTTP status codes  (existing behaviour)
# ---------------------------------------------------------------------------


class TestHTTPStatusCodes:
    """Verify retryable HTTP status code detection."""

    @pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
    def test_retryable_status_codes(self, code: int):
        assert _is_retryable(_exc_with_status(code)) is True

    @pytest.mark.parametrize("code", [200, 400, 401, 403, 404, 422])
    def test_non_retryable_status_codes(self, code: int):
        assert _is_retryable(_exc_with_status(code)) is False


# ---------------------------------------------------------------------------
# Tests: httpx transport-level exceptions  (new)
# ---------------------------------------------------------------------------


class TestHttpxExceptions:
    """Verify that raw httpx network errors are detected as retryable."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_httpx(self):
        pytest.importorskip("httpx")

    def test_remote_protocol_error(self):
        import httpx

        exc = httpx.RemoteProtocolError(
            "peer closed connection without sending complete message body",
        )
        assert _is_retryable(exc) is True

    def test_read_timeout(self):
        import httpx

        exc = httpx.ReadTimeout(
            "timed out",
            request=MagicMock(),
        )
        assert _is_retryable(exc) is True

    def test_connect_timeout(self):
        import httpx

        exc = httpx.ConnectTimeout(
            "timed out",
            request=MagicMock(),
        )
        assert _is_retryable(exc) is True

    def test_connect_error(self):
        import httpx

        exc = httpx.ConnectError(
            "connection refused",
            request=MagicMock(),
        )
        assert _is_retryable(exc) is True

    def test_read_error(self):
        import httpx

        exc = httpx.ReadError(
            "connection reset by peer",
            request=MagicMock(),
        )
        assert _is_retryable(exc) is True


# ---------------------------------------------------------------------------
# Tests: Python built-in network exceptions  (new)
# ---------------------------------------------------------------------------


class TestBuiltinNetworkErrors:
    """Verify that Python built-in network exceptions are retryable."""

    def test_connection_error(self):
        assert _is_retryable(ConnectionError("connection refused")) is True

    def test_connection_reset_error(self):
        assert _is_retryable(ConnectionResetError("reset by peer")) is True

    def test_timeout_error(self):
        assert _is_retryable(TimeoutError("timed out")) is True

    def test_os_error_network(self):
        assert _is_retryable(OSError(101, "Network unreachable")) is True

    def test_broken_pipe(self):
        assert _is_retryable(BrokenPipeError("broken pipe")) is True


# ---------------------------------------------------------------------------
# Tests: Non-retryable exceptions
# ---------------------------------------------------------------------------


class TestNonRetryable:
    """Verify that non-network exceptions are NOT marked as retryable."""

    def test_value_error(self):
        assert _is_retryable(ValueError("bad value")) is False

    def test_type_error(self):
        assert _is_retryable(TypeError("wrong type")) is False

    def test_runtime_error(self):
        assert _is_retryable(RuntimeError("generic runtime")) is False

    def test_key_error(self):
        assert _is_retryable(KeyError("missing key")) is False

    def test_generic_exception_no_status(self):
        assert _is_retryable(Exception("something went wrong")) is False
