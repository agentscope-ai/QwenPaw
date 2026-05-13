# -*- coding: utf-8 -*-
"""Shell sandbox abstraction for file guard pre-hook."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shlex
import shutil
from typing import Protocol

from .whitelist import FileWhitelistPolicy, normalize_access_path


@dataclass
class SandboxPreparation:
    """Prepared command payload returned by sandbox providers."""

    command: str
    warning: str = ""
    blocked_reason: str = ""


class ShellSandboxProvider(Protocol):
    """Platform-specific shell sandbox provider interface."""

    def prepare(self, command: str, working_dir: str) -> SandboxPreparation:
        """Return wrapped command or a blocking reason."""


def _load_shell_sandbox_config() -> tuple[str, str]:
    try:
        from qwenpaw.config import load_config

        fg = load_config().security.file_guard
        mode = str(getattr(fg, "shell_sandbox_mode", "audit") or "audit")
        provider = str(
            getattr(fg, "shell_sandbox_provider", "auto") or "auto",
        )
        return mode, provider
    except Exception:
        return "audit", "auto"


class MacOSSandboxExecProvider:
    """macOS sandbox provider using sandbox-exec profile strings."""

    @staticmethod
    def _profile_text(policy: FileWhitelistPolicy, working_dir: str) -> str:
        read_roots, write_roots = policy.allowed_roots_for_shell()
        wd = normalize_access_path(working_dir)
        if wd:
            read_roots = sorted(set(read_roots) | {wd})
            write_roots = sorted(set(write_roots) | {wd})
        lines = [
            "(version 1)",
            "(deny default)",
            '(import "system.sb")',
            "(allow process*)",
            "(allow sysctl-read)",
        ]
        for root in read_roots:
            lines.append(f'(allow file-read* (subpath "{root}"))')
        for root in write_roots:
            lines.append(f'(allow file-write* (subpath "{root}"))')
        return "\n".join(lines)

    def prepare(self, command: str, working_dir: str) -> SandboxPreparation:
        policy = FileWhitelistPolicy.from_config()
        profile = self._profile_text(policy, working_dir=working_dir)
        wrapped = (
            f"sandbox-exec -p {shlex.quote(profile)} "
            f"/bin/sh -c {shlex.quote(command)}"
        )
        return SandboxPreparation(command=wrapped)


class UnsupportedSandboxProvider:
    """Placeholder provider for Linux/Windows until implemented."""

    def __init__(self, platform_name: str, mode: str) -> None:
        self._platform_name = platform_name
        _ = mode

    def prepare(self, command: str, working_dir: str) -> SandboxPreparation:
        _ = working_dir
        msg = (
            "Shell sandbox is configured but not implemented on "
            f"{self._platform_name} yet."
        )
        return SandboxPreparation(command=command, warning=msg)


def _resolve_provider(mode: str, configured_provider: str) -> ShellSandboxProvider:
    if configured_provider == "macos_sandbox_exec":
        return MacOSSandboxExecProvider()
    if configured_provider == "linux_placeholder":
        return UnsupportedSandboxProvider("linux", mode)
    if configured_provider == "windows_placeholder":
        return UnsupportedSandboxProvider("windows", mode)
    # auto mode
    if os.name == "posix" and shutil.which("sandbox-exec") is not None:
        return MacOSSandboxExecProvider()
    if os.name == "nt":
        return UnsupportedSandboxProvider("windows", mode)
    return UnsupportedSandboxProvider("linux", mode)


def prepare_sandboxed_shell_command(
    command: str,
    working_dir: str,
) -> SandboxPreparation:
    """Prepare command for platform sandbox execution."""
    mode, configured_provider = _load_shell_sandbox_config()

    if mode not in ("enforce", "audit"):
        mode = "enforce"

    provider = _resolve_provider(mode, configured_provider)
    return provider.prepare(command=command, working_dir=working_dir)
