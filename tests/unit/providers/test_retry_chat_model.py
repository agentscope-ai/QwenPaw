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

    @pytest.mark.parametrize(
        "exception_factory",
        [
            lambda httpx: httpx.RemoteProtocolError(
                "peer closed connection without sending complete message body",
            ),
            lambda httpx: httpx.ReadTimeout("timed out", request=MagicMock()),
            lambda httpx: httpx.ConnectTimeout("timed out", request=MagicMock()),
            lambda httpx: httpx.ConnectError("connection refused", request=MagicMock()),
            lambda httpx: httpx.ReadError("connection reset by peer", request=MagicMock()),
        ],
        ids=[
            "RemoteProtocolError",
            "ReadTimeout",
            "ConnectTimeout",
            "ConnectError",
            "ReadError",
        ],
    )
    def test_httpx_exceptions_are_retryable(self, exception_factory):
        import httpx

        exc = exception_factory(httpx)
        assert _is_retryable(exc) is True


# ---------------------------------------------------------------------------
# Tests: Python built-in network exceptions  (new)
# ---------------------------------------------------------------------------


class TestBuiltinNetworkErrors:
    """Verify that Python built-in network exceptions are retryable."""

    @pytest.mark.parametrize(
        "exc",
        [
            ConnectionError("connection refused"),
            ConnectionResetError("reset by peer"),
            TimeoutError("timed out"),
            OSError(101, "Network unreachable"),
            BrokenPipeError("broken pipe"),
        ],
        ids=[
            "ConnectionError",
            "ConnectionResetError",
            "TimeoutError",
            "OSError_NetworkUnreachable",
            "BrokenPipeError",
        ],
    )
    def test_builtin_network_errors_are_retryable(self, exc):
        assert _is_retryable(exc) is True


# ---------------------------------------------------------------------------
# Tests: Non-retryable exceptions
# ---------------------------------------------------------------------------


class TestNonRetryable:
    """Verify that non-network exceptions are NOT marked as retryable."""

    @pytest.mark.parametrize(
        "exc",
        [
            ValueError("bad value"),
            TypeError("wrong type"),
            RuntimeError("generic runtime"),
            KeyError("missing key"),
            Exception("something went wrong"),
        ],
        ids=[
            "ValueError",
            "TypeError",
            "RuntimeError",
            "KeyError",
            "GenericException",
        ],
    )
    def test_non_retryable_exceptions(self, exc):
        assert _is_retryable(exc) is False
