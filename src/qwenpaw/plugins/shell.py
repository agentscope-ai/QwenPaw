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
    """Match an exact identity, including disconnected-but-selected targets.

    matches is a quick synchronous predicate over plugin-owned state. Return
    False only when this identity has deliberately deselected the backend.
    A selected but failed connection must still match and raise from execute.
    After reload, an unmatched previous selection stays blocked until the
    new instance explicitly matches again; reload is not a local fallback.
    cwd is the original argument, never a translated local workspace path.
    """

    name: str
    matches: Callable[[RequestContext], bool]
    execute: Callable[[ToolContext, ShellRequest], Awaitable[ShellResult]]
