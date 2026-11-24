# -*- coding: utf-8 -*-
"""Alternative shell execution after the host's normal permission checks."""

from dataclasses import dataclass
from typing import Awaitable, Callable

from .context import RequestContext
from .tools import ToolContext


@dataclass(frozen=True)
class ShellRequest:
    command: str
    cwd: str | None = None
    timeout: float = 60.0


@dataclass(frozen=True)
class ShellResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class ShellBackendSpec:
    """Provide an alternate shell for an explicitly selected conversation.

    Use call.select_shell_backend(name) from an app or control command to
    select it before executing anything. matches checks ownership and
    readiness synchronously; False blocks execution of a selected backend.
    A failed execute also blocks; neither changes the selection.
    Use call.select_shell_backend(None) on explicit deselection.
    cwd is the original argument, never a translated local workspace path.
    """

    name: str
    matches: Callable[[RequestContext], bool]
    execute: Callable[[ToolContext, ShellRequest], Awaitable[ShellResult]]
