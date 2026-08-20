# -*- coding: utf-8 -*-
"""Supported shell matrix for managed terminal transports."""

from __future__ import annotations

_POSIX_TTY_SHELLS = frozenset({"sh", "bash", "zsh"})
_WINDOWS_TTY_SHELLS = frozenset(
    {
        "cmd",
        "cmd.exe",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
    },
)


def shell_name(shell: str) -> str:
    """Return the case-normalized executable basename."""
    return shell.replace("\\", "/").rsplit("/", 1)[-1].lower()


def shell_kind(shell: str) -> str:
    """Return the completion-protocol family for a shell executable."""
    name = shell_name(shell)
    if name in {"cmd", "cmd.exe"}:
        return "cmd"
    if name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return "powershell"
    return "posix"


def supports_native_tty(shell: str, *, windows: bool) -> bool:
    """Whether the shell has a tested native PTY/ConPTY protocol."""
    name = shell_name(shell)
    supported = _WINDOWS_TTY_SHELLS if windows else _POSIX_TTY_SHELLS
    return name in supported
