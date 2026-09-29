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
    kernel.CreateFileW.return_value = 123
    kernel.MapVirtualKeyW.return_value = 46
    kernel.WriteConsoleInputW.return_value = True

    def record_count(_handle, _records, count, written):
        pointer = ctypes.cast(written, ctypes.POINTER(ctypes.c_ulong))
        pointer.contents.value = count
        return True

    kernel.WriteConsoleInputW.side_effect = record_count
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda *_a, **_kw: kernel,
        raising=False,
    )
    windows.interrupt_console(123)
    kernel.FreeConsole.assert_has_calls([call(), call()])
    kernel.AttachConsole.assert_called_once_with(123)
    kernel.CreateFileW.assert_called_once()
    kernel.MapVirtualKeyW.assert_called_once_with(windows.VK_C, 0)
    kernel.WriteConsoleInputW.assert_called_once()
    records = kernel.WriteConsoleInputW.call_args.args[1]
    assert [record.event.key.key_down for record in records] == [True, False]
    assert all(
        record.event.key.control_key_state == windows.LEFT_CTRL_PRESSED
        for record in records
    )
    kernel.CloseHandle.assert_called_once_with(123)


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
    kernel.CreateFileW.assert_not_called()
    kernel.WriteConsoleInputW.assert_not_called()


def test_failed_event_detaches_console(monkeypatch):
    kernel = MagicMock()
    kernel.AttachConsole.return_value = True
    kernel.CreateFileW.return_value = 123
    kernel.MapVirtualKeyW.return_value = 46
    kernel.WriteConsoleInputW.return_value = False
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
    kernel.CloseHandle.assert_called_once_with(123)
    assert kernel.mock_calls[-1] == call.FreeConsole()
