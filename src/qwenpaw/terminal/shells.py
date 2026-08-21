# -*- coding: utf-8 -*-
"""Supported shell matrix for managed terminal transports."""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class ShellSpec:
    """One shell executable's protocol family and launch arguments."""

    executable: str
    name: str
    family: str

    def supports_native_tty(self, *, windows: bool) -> bool:
        """Whether this shell has a tested native terminal protocol."""
        supported = _WINDOWS_TTY_SHELLS if windows else _POSIX_TTY_SHELLS
        return self.name in supported

    def posix_pty_argv(self) -> list[str]:
        """Return predictable interactive arguments for a POSIX PTY."""
        if self.name == "zsh":
            return [self.executable, "-f", "-i"]
        if self.name == "bash":
            return [
                self.executable,
                "--noprofile",
                "--norc",
                "--noediting",
                "-i",
            ]
        return [self.executable, "-i"]

    def windows_conpty_argv(self) -> list[str]:
        """Return argv for pywinpty without pre-quoting the executable."""
        if self.family == "cmd":
            return [self.executable, "/D", "/Q", "/K"]
        if self.family == "powershell":
            return [self.executable, "-NoLogo", "-NoProfile"]
        return [self.executable]

    def pipe_argv(self, *, windows: bool) -> list[str]:
        """Return argv for the explicitly degraded pipe transport."""
        if self.family == "cmd":
            return [self.executable, "/D", "/Q", "/K"]
        if self.family == "powershell":
            return [
                self.executable,
                "-NoLogo",
                "-NoProfile",
                "-Command",
                "-",
            ]
        if windows:
            return [self.executable]
        return [self.executable]


def shell_name(shell: str) -> str:
    """Return the case-normalized executable basename."""
    return shell.replace("\\", "/").rsplit("/", 1)[-1].lower()


def shell_spec(shell: str) -> ShellSpec:
    """Resolve one executable into the shared managed-shell model."""
    name = shell_name(shell)
    if name in {"cmd", "cmd.exe"}:
        family = "cmd"
    elif name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        family = "powershell"
    else:
        family = "posix"
    return ShellSpec(executable=shell, name=name, family=family)


def shell_kind(shell: str) -> str:
    """Return the completion-protocol family for a shell executable."""
    return shell_spec(shell).family


def supports_native_tty(shell: str, *, windows: bool) -> bool:
    """Whether the shell has a tested native PTY/ConPTY protocol."""
    return shell_spec(shell).supports_native_tty(windows=windows)
