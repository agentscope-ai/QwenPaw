# -*- coding: utf-8 -*-
"""PTY interrupt contracts and a Windows-only native smoke test."""

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
