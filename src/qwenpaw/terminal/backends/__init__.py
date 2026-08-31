# -*- coding: utf-8 -*-
"""Terminal backend selection."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from .base import TerminalBackend
from .pipe_fallback import PipeTerminalBackend
from ..shells import supports_native_tty


async def spawn_terminal_backend(
    shell: str,
    cwd: Path,
    env: dict[str, str],
    capture_bytes: int,
    *,
    tty: bool,
) -> TerminalBackend:
    native_tty = tty and supports_native_tty(
        shell,
        windows=sys.platform == "win32",
    )
    if native_tty and sys.platform != "win32":
        from .posix_pty import PosixPtyBackend

        return await PosixPtyBackend.spawn(shell, cwd, env, capture_bytes)
    if native_tty and sys.platform == "win32":
        try:
            from .windows_conpty import WindowsConPtyBackend

            return await WindowsConPtyBackend.spawn(
                shell,
                cwd,
                env,
                capture_bytes,
            )
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "ConPTY initialization failed; using degraded pipe terminal",
                exc_info=True,
            )
    elif tty:
        logging.getLogger(__name__).warning(
            "Managed terminal shell %r is outside the supported TTY matrix; "
            "using degraded pipe terminal",
            shell,
        )
    return await PipeTerminalBackend.spawn(shell, cwd, env, capture_bytes)


__all__ = ["TerminalBackend", "spawn_terminal_backend"]
