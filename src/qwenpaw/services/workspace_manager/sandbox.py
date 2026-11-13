# -*- coding: utf-8 -*-
"""Lightweight resource-boundary sandbox (interface only).

The concrete implementation is provided by a separate workstream.
This module defines the contracts that tool execution code programs
against — ``check_path`` / ``check_tool`` raise
:class:`SandboxViolationError` when a tool call violates boundaries.

Guard = content safety (``tool_guard/engine.py``), Sandbox = resource
boundary (paths / tool whitelist).  The two layers are orthogonal;
both run before ``tool.func()``.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Literal

from qwenpaw.exceptions import SandboxViolationError


class Sandbox:
    """Per-workspace resource boundary enforcer.

    Parameters
    ----------
    allowed_paths:
        Directories the agent is allowed to access.
    denied_tools:
        Tool names that are unconditionally blocked.
    shell_executable:
        Shell binary for ``execute_shell_command``.
    shell_timeout:
        Default timeout (seconds) for shell commands.
    """

    def __init__(
        self,
        *,
        allowed_paths: list[Path] | None = None,
        denied_tools: set[str] | None = None,
        shell_executable: str | None = None,
        shell_timeout: int = 60,
    ) -> None:
        self.allowed_paths: list[Path] = allowed_paths or []
        self.denied_tools: set[str] = denied_tools or set()
        self.shell_executable: str = shell_executable or self._default_shell()
        self.shell_timeout: int = shell_timeout

    @staticmethod
    def _default_shell() -> str:
        if sys.platform == "win32":
            return shutil.which("cmd") or "cmd.exe"
        return shutil.which("sh") or "/bin/sh"

    def check_path(
        self,
        path: str,
        op: Literal["read", "write", "exec"],
    ) -> None:
        """Raise :class:`SandboxViolationError` if *path* is
        outside allowed roots.

        Concrete implementation will resolve symlinks and compare
        against ``allowed_paths``.  Stub raises ``NotImplementedError``.
        """
        raise NotImplementedError(
            "Sandbox.check_path: provided by separate workstream",
        )

    def check_tool(self, tool_name: str) -> None:
        """Raise :class:`SandboxViolationError` if *tool_name* is denied.

        Concrete implementation checks ``denied_tools``.  Stub raises
        ``NotImplementedError``.
        """
        raise NotImplementedError(
            "Sandbox.check_tool: provided by separate workstream",
        )


__all__ = ["Sandbox", "SandboxViolationError"]
