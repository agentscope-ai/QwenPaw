# -*- coding: utf-8 -*-
"""PTY interrupt contracts and a Windows-only native smoke test."""

import ctypes
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from qwenpaw.services import terminal_windows as windows


def worker_ignoring_ctrl_c(*args):
    """Reproduce a launcher that passes Ctrl+C suppression to its children."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    if not kernel.SetConsoleCtrlHandler(None, True):
        raise ctypes.WinError(ctypes.get_last_error())
    windows.pty_worker(*args)


@pytest.mark.skipif(sys.platform != "win32", reason="Real Windows console")
@pytest.mark.parametrize("inherited_ignore", [False, True])
def test_native_ping_interrupt_and_host_cleanup(
    tmp_path,
    monkeypatch,
    inherited_ignore,
):
    pytest.importorskip("winpty")
    if inherited_ignore:
        # multiprocessing spawn imports this module afresh in the worker,
        # where windows.pty_worker still refers to the production function.
        monkeypatch.setattr(windows, "pty_worker", worker_ignoring_ctrl_c)
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
        adapter.write("function prompt { 'QWENPAW_' + 'READY>' }; \r")
        until("QWENPAW_READY>")
        adapter.write("ping -n 30 127.0.0.1\r")
        until("TTL=")
        adapter.write("\x03")
        until("QWENPAW_READY>")
        adapter.write("echo ('QWENPAW_' + 'INTERRUPT_OK')\r")
        until("QWENPAW_INTERRUPT_OK")
        owned = adapter.owner.children(recursive=True)
    finally:
        adapter.close()
    assert all(not process.is_running() for process in owned)


@pytest.mark.parametrize("success", [True, False])
def test_enable_ctrl_c_clears_inherited_ignore(monkeypatch, success):
    kernel = MagicMock()
    kernel.SetConsoleCtrlHandler.return_value = success
    monkeypatch.setattr(windows, "sys", SimpleNamespace(platform="win32"))
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
        lambda _: OSError("reset failed"),
        raising=False,
    )
    if success:
        windows.enable_ctrl_c()
    else:
        with pytest.raises(OSError, match="reset failed"):
            windows.enable_ctrl_c()
    assert kernel.mock_calls == [call.SetConsoleCtrlHandler(None, False)]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("hello", [call.write("hello")]),
        ("\x03", [call.sendintr()]),
        ("\x03\x03", [call.sendintr(), call.sendintr()]),
        (
            "before\x03after\x03",
            [
                call.write("before"),
                call.sendintr(),
                call.write("after"),
                call.sendintr(),
            ],
        ),
    ],
)
def test_control_c_uses_owned_pty_and_preserves_text_order(data, expected):
    process = MagicMock()
    windows.write_input(process, data)
    assert process.mock_calls == expected


def test_failed_interrupt_does_not_write_following_command():
    process = MagicMock()
    process.sendintr.side_effect = OSError("PTY closed")
    with pytest.raises(OSError, match="PTY closed"):
        windows.write_input(process, "\x03next command\r")
    process.write.assert_not_called()
