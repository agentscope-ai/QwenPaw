# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import qwenpaw.utils.stdio as stdio_module
from qwenpaw.utils.stdio import (
    _close_fallback_streams,
    _is_stream_usable,
    ensure_standard_streams,
)


@pytest.fixture(autouse=True)
def _reset_stdio_state():
    """Reset module-level state between tests."""
    stdio_module._FALLBACK_STREAMS.clear()
    stdio_module._FALLBACK_STREAMS_BY_ENCODING.clear()
    stdio_module._FALLBACK_CLEANUP_REGISTERED = False
    yield
    stdio_module._FALLBACK_STREAMS.clear()
    stdio_module._FALLBACK_STREAMS_BY_ENCODING.clear()


# ---------------------------------------------------------------------------
# _is_stream_usable
# ---------------------------------------------------------------------------


def test_is_stream_usable_none() -> None:
    assert _is_stream_usable(None) is False


def test_is_stream_usable_valid() -> None:
    stream = MagicMock()
    stream.flush.return_value = None
    stream.write.return_value = 0
    assert _is_stream_usable(stream) is True


def test_is_stream_usable_flush_raises() -> None:
    stream = MagicMock()
    stream.flush.side_effect = OSError("broken")
    assert _is_stream_usable(stream) is False


def test_is_stream_usable_write_raises() -> None:
    stream = MagicMock()
    stream.flush.return_value = None
    stream.write.side_effect = ValueError("closed")
    assert _is_stream_usable(stream) is False


def test_is_stream_usable_no_flush_attr() -> None:
    stream = MagicMock(spec=[])
    assert _is_stream_usable(stream) is False


# ---------------------------------------------------------------------------
# ensure_standard_streams
# ---------------------------------------------------------------------------


def test_ensure_standard_streams_keeps_good_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good_stdout = MagicMock()
    good_stdout.flush.return_value = None
    good_stdout.write.return_value = 0
    good_stderr = MagicMock()
    good_stderr.flush.return_value = None
    good_stderr.write.return_value = 0

    import sys

    monkeypatch.setattr(sys, "stdout", good_stdout)
    monkeypatch.setattr(sys, "stderr", good_stderr)

    ensure_standard_streams()

    assert sys.stdout is good_stdout
    assert sys.stderr is good_stderr


def test_ensure_standard_streams_replaces_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = MagicMock()
    broken.flush.side_effect = OSError("broken pipe")
    broken.encoding = "utf-8"

    import sys

    monkeypatch.setattr(sys, "stdout", broken)
    monkeypatch.setattr(sys, "stderr", broken)

    ensure_standard_streams()

    assert sys.stdout is not broken
    assert sys.stderr is not broken
    assert hasattr(sys.stdout, "write")


def test_ensure_standard_streams_replaces_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    ensure_standard_streams()

    assert sys.stdout is not None
    assert sys.stderr is not None


# ---------------------------------------------------------------------------
# fallback caching and cleanup
# ---------------------------------------------------------------------------


def test_fallback_stream_cached_by_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken1 = MagicMock()
    broken1.flush.side_effect = OSError()
    broken1.encoding = "utf-8"

    broken2 = MagicMock()
    broken2.flush.side_effect = OSError()
    broken2.encoding = "utf-8"

    import sys

    monkeypatch.setattr(sys, "stdout", broken1)
    monkeypatch.setattr(sys, "stderr", broken2)

    ensure_standard_streams()

    assert sys.stdout is sys.stderr


def test_close_fallback_streams_cleans_up() -> None:
    mock_stream = MagicMock()
    stdio_module._FALLBACK_STREAMS.append(mock_stream)
    stdio_module._FALLBACK_STREAMS_BY_ENCODING["utf-8"] = mock_stream

    _close_fallback_streams()

    mock_stream.close.assert_called_once()
    assert len(stdio_module._FALLBACK_STREAMS) == 0
    assert len(stdio_module._FALLBACK_STREAMS_BY_ENCODING) == 0


def test_close_fallback_streams_ignores_os_error() -> None:
    mock_stream = MagicMock()
    mock_stream.close.side_effect = OSError("can't close")
    stdio_module._FALLBACK_STREAMS.append(mock_stream)

    _close_fallback_streams()
    assert len(stdio_module._FALLBACK_STREAMS) == 0
