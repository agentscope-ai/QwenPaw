# -*- coding: utf-8 -*-
"""Singleton adapter for the active FileSystemBackend.

Tools call ``get_backend()`` to obtain the current backend instance.
The runner sets the backend at startup via ``set_backend()``.

Usage::

    from copaw.agents.fs_backend.adapter import get_backend, set_backend

    # At startup (runner.py):
    set_backend(E2BBackend(sandbox))

    # In tools:
    backend = get_backend()
    result = await backend.run_command("ls")
"""

import logging
from typing import Optional

from .fs_backend import FileSystemBackend
from .local_backend import LocalBackend

logger = logging.getLogger(__name__)

_backend: Optional[FileSystemBackend] = None


def get_backend() -> FileSystemBackend:
    """Return the active FileSystemBackend.

    Falls back to LocalBackend if none has been set.
    """
    global _backend
    if _backend is None:
        logger.debug("fs_backend adapter: no backend set, using LocalBackend")
        _backend = LocalBackend()
    return _backend


def set_backend(backend: FileSystemBackend) -> None:
    """Set the active FileSystemBackend singleton.

    Args:
        backend: A FileSystemBackend implementation.
    """
    global _backend
    _backend = backend
    logger.info(
        "fs_backend adapter: backend set to %s (cloud=%s)",
        type(backend).__name__,
        backend.is_cloud(),
    )


def reset_backend() -> None:
    """Reset the backend to None (forces re-initialization on next get)."""
    global _backend
    _backend = None
    logger.info("fs_backend adapter: backend reset")
