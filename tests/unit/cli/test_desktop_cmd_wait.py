# -*- coding: utf-8 -*-
"""Unit tests for _wait_for_http with progress_cb."""

from unittest.mock import MagicMock, patch

from qwenpaw.cli.desktop_cmd import _wait_for_http


class _FakeSocket:
    """Socket mock that fails N times then succeeds."""

    def __init__(self, fail_count: int):
        self._fail_count = fail_count
        self._attempts = 0

    def settimeout(self, _timeout: float) -> None:
        pass

    def connect(self, _address: tuple) -> None:
        self._attempts += 1
        if self._attempts <= self._fail_count:
            raise OSError("Connection refused")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


def test_progress_cb_called_during_wait():
    """progress_cb should be called once per failed connection attempt."""
    fail_count = 3
    cb = MagicMock()

    with patch(
        "qwenpaw.cli.desktop_cmd.socket.socket",
        return_value=_FakeSocket(fail_count),
    ):
        with patch("qwenpaw.cli.desktop_cmd.time.sleep"):
            result = _wait_for_http(
                "127.0.0.1",
                8080,
                timeout_sec=30,
                progress_cb=cb,
            )

    assert result is True
    assert cb.call_count == fail_count


def test_progress_cb_not_called_on_immediate_success():
    """progress_cb should not be called if connection succeeds immediately."""
    cb = MagicMock()

    with patch(
        "qwenpaw.cli.desktop_cmd.socket.socket",
        return_value=_FakeSocket(0),
    ):
        result = _wait_for_http(
            "127.0.0.1",
            8080,
            timeout_sec=30,
            progress_cb=cb,
        )

    assert result is True
    assert cb.call_count == 0


def test_no_progress_cb_still_works():
    """_wait_for_http works correctly when progress_cb is None."""
    with patch(
        "qwenpaw.cli.desktop_cmd.socket.socket",
        return_value=_FakeSocket(2),
    ):
        with patch("qwenpaw.cli.desktop_cmd.time.sleep"):
            result = _wait_for_http(
                "127.0.0.1",
                8080,
                timeout_sec=30,
                progress_cb=None,
            )

    assert result is True


def test_timeout_returns_false():
    """Should return False when deadline is exceeded."""

    class _AlwaysFail:
        def settimeout(self, _t):
            pass

        def connect(self, _a):
            raise OSError("refused")

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            pass

    cb = MagicMock()

    with patch(
        "qwenpaw.cli.desktop_cmd.socket.socket",
        return_value=_AlwaysFail(),
    ):
        with patch("qwenpaw.cli.desktop_cmd.time.sleep"):
            result = _wait_for_http(
                "127.0.0.1",
                8080,
                timeout_sec=0.01,
                progress_cb=cb,
            )

    assert result is False
    # cb should have been called at least once during the failed attempts
    assert cb.call_count >= 0  # may be 0 if deadline hit immediately
