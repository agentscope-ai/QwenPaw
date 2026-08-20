# -*- coding: utf-8 -*-
"""Tests for stateful managed-terminal input policy."""

import pytest

from qwenpaw.terminal import backends
from qwenpaw.terminal.input_policy import (
    TerminalInputBuffer,
    normalize_terminal_input,
)
from qwenpaw.terminal.shells import supports_native_tty


def test_input_buffer_withholds_fragments_until_line_is_complete():
    buffer = TerminalInputBuffer()

    assert buffer.commit("rm /tmp/sensi") == ""
    assert buffer.preview("tive.txt\n") == "rm /tmp/sensitive.txt\n"
    assert buffer.commit("tive.txt\n") == "rm /tmp/sensitive.txt\n"
    assert buffer.preview("next") == "next"


def test_terminal_input_normalizes_ctrl_c_aliases():
    assert normalize_terminal_input(r"\u0003", interrupt=False) == "\x03"
    assert normalize_terminal_input("ignored", interrupt=True) == "\x03"


def test_supported_shell_matrix_is_explicit():
    for shell in ("/bin/sh", "/bin/bash", "/bin/zsh"):
        assert supports_native_tty(shell, windows=False)
    assert not supports_native_tty("/usr/bin/fish", windows=False)
    assert not supports_native_tty("/usr/bin/nu", windows=False)

    for shell in ("cmd.exe", "powershell.exe", "pwsh.exe"):
        assert supports_native_tty(shell, windows=True)
    assert not supports_native_tty("nu.exe", windows=True)


@pytest.mark.asyncio
async def test_unknown_posix_shell_uses_explicit_degraded_fallback(
    monkeypatch,
    tmp_path,
):
    degraded = object()

    async def pipe_fallback(*_args, **_kwargs):
        return degraded

    monkeypatch.setattr(backends.sys, "platform", "linux")
    monkeypatch.setattr(backends.PipeTerminalBackend, "spawn", pipe_fallback)

    result = await backends.spawn_terminal_backend(
        "/usr/bin/fish",
        tmp_path,
        {},
        1024,
        tty=True,
    )

    assert result is degraded
