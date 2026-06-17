# -*- coding: utf-8 -*-
"""Port persistence utilities for desktop backends.

Provides helpers to persist and reuse the backend port across restarts
so that the browser origin (http://127.0.0.1:{port}) stays stable and
localStorage data (selected agent, plugin flags, etc.) survives.

Supports user-configured fixed ports via the
QWENPAW_DESKTOP_PORT environment variable.
"""

from __future__ import annotations

import logging
import secrets
import socket
import sys
from pathlib import Path

from ..constant import QWENPAW_DESKTOP_PORT

logger = logging.getLogger(__name__)


def read_last_port(port_file: str | Path) -> int | None:
    """Read the previously used port from *port_file*.

    Returns the port number if the file exists and contains a valid
    integer in the range 1024–65535, otherwise ``None``.
    """
    try:
        with open(port_file, "r", encoding="utf-8") as fh:
            port = int(fh.read().strip())
            if 1024 <= port <= 65535:
                return port
    except (OSError, ValueError):
        pass
    return None


def write_port_file(port_file: str | Path, port: int) -> None:
    """Atomically persist *port* to *port_file*.

    Uses a temp-file-then-replace strategy so a crash mid-write cannot
    leave a truncated or empty file.  On failure the error is logged
    but not raised (the caller degrades to a random port next time).
    """
    port_file = Path(port_file)
    try:
        port_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = port_file.with_name(
            f"{port_file.name}.tmp.{secrets.token_hex(4)}",
        )
        try:
            tmp.write_text(str(port), encoding="utf-8")
            tmp.replace(port_file)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
    except (OSError, ValueError):
        logger.debug("Failed to write port file: %s", port_file)


def try_bind_port(host: str, port: int) -> socket.socket | None:
    """Try to bind and listen on *host*:*port*.

    On Windows, uses ``SO_EXCLUSIVEADDRUSE`` so the probe fails if any
    other process is already listening (Windows ``SO_REUSEADDR`` would
    silently succeed, hiding the conflict).  On POSIX, uses
    ``SO_REUSEADDR`` to allow rebinding ports in ``TIME_WAIT``.

    Returns the bound+listening socket on success, or ``None`` if the
    port is unavailable.  The caller is responsible for closing the
    socket (or passing it to a server that will).
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sys.platform == "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(1)
        return sock
    except OSError:
        try:
            sock.close()
        except OSError:
            pass
        return None


def find_free_port(host: str = "127.0.0.1") -> int:
    """Bind to port 0 and return the OS-assigned free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(1)
        return sock.getsockname()[1]


def get_stable_port(
    port_file: str | Path,
    host: str = "127.0.0.1",
) -> tuple[int, socket.socket | None]:
    """Return ``(port, socket | None)`` for a stable desktop backend.

    Tries to reuse the port recorded in *port_file*.  If that port is
    available, the **bound+listening socket** is returned so the caller
    can pass it directly to the server — eliminating the TOCTOU window
    where another process could grab the port between our check and
    the server's bind.

    If the previous port is unavailable or the file is missing/invalid,
    a random port is allocated (socket is ``None`` in this case because
    the OS-assigned port is obtained via a throw-away socket).

    The chosen port is always persisted back to *port_file*.

    If QWENPAW_DESKTOP_PORT environment variable is set, it takes priority
    and the port is fixed (not persisted).
    """
    # Check for user-configured port via environment variable
    if QWENPAW_DESKTOP_PORT:
        try:
            port = int(QWENPAW_DESKTOP_PORT)
        except (TypeError, ValueError):
            logger.warning(
                "QWENPAW_DESKTOP_PORT=%r is not a valid "
                "integer, falling back to auto-assign",
                QWENPAW_DESKTOP_PORT,
            )
            port = None
        if port is not None:
            if not 1024 <= port <= 65535:
                logger.warning(
                    "QWENPAW_DESKTOP_PORT=%d out of range "
                    "1024-65535, falling back to auto-assign",
                    port,
                )
            else:
                sock = try_bind_port(host, port)
                if sock:
                    logger.info(
                        "Using QWENPAW_DESKTOP_PORT: %d",
                        port,
                    )
                    return port, sock
                logger.warning(
                    "QWENPAW_DESKTOP_PORT=%d is "
                    "unavailable, falling back "
                    "to auto-assign",
                    port,
                )

    last_port = read_last_port(port_file)
    reused_socket: socket.socket | None = None

    if last_port is not None:
        reused_socket = try_bind_port(host, last_port)
        if reused_socket:
            logger.debug("Reusing previous desktop port %d", last_port)
            return last_port, reused_socket
        logger.debug(
            "Previous port %d unavailable, falling back to random",
            last_port,
        )

    port = find_free_port(host)
    logger.debug("Allocated new desktop port %d", port)
    write_port_file(port_file, port)
    return port, None
