# -*- coding: utf-8 -*-
"""Shell sandbox abstraction for file guard pre-hook."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shlex
import shutil
from typing import Protocol

from .whitelist import FileWhitelistPolicy, normalize_access_path

_MACOS_BASELINE_READ_ROOTS: tuple[str, ...] = (
    "/private/var/select/",
    "/bin/",
    "/sbin/",
    "/usr/bin/",
    "/usr/sbin/",
    "/usr/lib/",
    "/usr/libexec/",
    "/System/",
    "/Library/",
    "/dev/",
)
_MACOS_BASELINE_WRITE_ROOTS: tuple[str, ...] = (
    "/tmp/",
    "/private/tmp/",
    "/private/var/tmp/",
)


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
    def _normalized_roots(paths: list[str]) -> set[str]:
        roots: set[str] = set()
        for path in paths:
            normalized = normalize_access_path(path)
            if normalized:
                roots.add(normalized)
        return roots

    @staticmethod
    def _profile_text(policy: FileWhitelistPolicy, working_dir: str) -> str:
        read_roots, write_roots = policy.allowed_roots_for_shell()
        read_set = MacOSSandboxExecProvider._normalized_roots(read_roots)
        write_set = MacOSSandboxExecProvider._normalized_roots(write_roots)

        read_set.update(
            MacOSSandboxExecProvider._normalized_roots(
                list(_MACOS_BASELINE_READ_ROOTS),
            ),
        )
        write_set.update(
            MacOSSandboxExecProvider._normalized_roots(
                list(_MACOS_BASELINE_WRITE_ROOTS),
            ),
        )

        wd = normalize_access_path(working_dir)
        if wd:
            read_set.add(wd)
            write_set.add(wd)
        read_roots = sorted(read_set)
        write_roots = sorted(write_set)
        lines = [
            "(version 1)",
            "(deny default)",
            '(import "system.sb")',
            "(allow process*)",
            "(allow sysctl-read)",
            # Allow metadata reads globally so basic traversal operations
            # (`ls -la`, resolving `..`, `find` walking) keep working,
            # while file content access is still controlled by read/write roots.
            "(allow file-read-metadata)",
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


def _resolve_provider(
    mode: str,
    configured_provider: str,
) -> ShellSandboxProvider:
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
        mode = "audit"

    provider = _resolve_provider(mode, configured_provider)
    return provider.prepare(command=command, working_dir=working_dir)
