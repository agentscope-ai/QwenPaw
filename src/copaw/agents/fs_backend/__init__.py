# -*- coding: utf-8 -*-
"""fs_backend: Unified file system backend abstraction.

Provides a common interface for local, E2B, and AgentScope sandbox
file system operations. Tools use the adapter singleton to route
operations to the active backend transparently.

Usage::

    from copaw.agents.fs_backend.adapter import get_backend
    backend = get_backend()
    result = await backend.run_command("ls -la")
"""

from .fs_backend import FileSystemBackend
from .adapter import get_backend, set_backend, reset_backend

__all__ = [
    "FileSystemBackend",
    "get_backend",
    "set_backend",
    "reset_backend",
]
