# -*- coding: utf-8 -*-
"""Console event routing contracts and a Windows-only native smoke test."""

import ctypes
import os
import sys
import time
from unittest.mock import MagicMock, call

import pytest

from qwenpaw.services import terminal_windows as windows


@pytest.mark.skipif(sys.platform != "win32", reason="Real Windows console")
def test_native_ping_interrupt_and_host_cleanup(tmp_path):
    pytest.importorskip("winpty")
    adapter = windows.WindowsPty.spawn(
        ["powershell.exe", "-NoLogo", "-NoProfile"],
        str(tmp_path),
        dict(os.environ),
        (24, 80),
    )

    def until(marker):
        output = ""
        deadline = time.monotonic() + 8
        while marker not in output and time.monotonic() < deadline:
            if adapter.output.poll(0.1):
                output += adapter.read(4096)
        assert marker in output, output

    try:
        adapter.write("ping -n 30 127.0.0.1\r")
        until("TTL=")
        adapter.write("\x03")
        adapter.write("echo ('QWENPAW_' + 'INTERRUPT_OK')\r")
        until("QWENPAW_INTERRUPT_OK")
        owned = adapter.owner.children(recursive=True)
    finally:
        adapter.close()
    assert all(not process.is_running() for process in owned)


def test_control_c_uses_console_event_and_preserves_text_order(monkeypatch):
    process = MagicMock(pid=123)
    events = MagicMock()
    process.write = events.write
    monkeypatch.setattr(windows, "interrupt_console", events.interrupt)
    windows.write_input(process, "before\x03after\x03")
    assert events.mock_calls == [
        call.write("before"),
        call.interrupt(123),
        call.write("after"),
        call.interrupt(123),
    ]


def test_interrupt_attaches_only_to_owned_shell(monkeypatch):
    kernel = MagicMock()
    kernel.AttachConsole.return_value = True
    kernel.SetConsoleCtrlHandler.return_value = True
    kernel.GenerateConsoleCtrlEvent.return_value = True
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda *_a, **_kw: kernel,
        raising=False,
    )
    monkeypatch.setattr(windows.time, "sleep", lambda _: None)
    windows.interrupt_console(123)
    assert kernel.mock_calls == [
        call.FreeConsole(),
        call.AttachConsole(123),
        call.SetConsoleCtrlHandler(None, True),
        call.GenerateConsoleCtrlEvent(0, 0),
        call.FreeConsole(),
    ]


def test_failed_attach_never_signals_another_console(monkeypatch):
    kernel = MagicMock()
    kernel.AttachConsole.return_value = False
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda *_a, **_kw: kernel,
        raising=False,
    )
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 6, raising=False)
    monkeypatch.setattr(
        ctypes,
        "WinError",
        lambda _: OSError("attach failed"),
        raising=False,
    )
    with pytest.raises(OSError, match="attach failed"):
        windows.interrupt_console(123)
    kernel.GenerateConsoleCtrlEvent.assert_not_called()


def test_failed_event_detaches_console(monkeypatch):
    kernel = MagicMock()
    kernel.AttachConsole.return_value = True
    kernel.SetConsoleCtrlHandler.return_value = True
    kernel.GenerateConsoleCtrlEvent.return_value = False
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda *_a, **_kw: kernel,
        raising=False,
    )
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 6, raising=False)
    monkeypatch.setattr(
        ctypes,
        "WinError",
        lambda _: OSError("signal failed"),
        raising=False,
    )
    with pytest.raises(OSError, match="signal failed"):
        windows.interrupt_console(123)
    assert kernel.mock_calls[-1] == call.FreeConsole()
