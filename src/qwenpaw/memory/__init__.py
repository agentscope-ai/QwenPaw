# -*- coding: utf-8 -*-
"""Public, versioned memory backend plugin API.

Plugins should import memory contracts from this module rather than from the
internal ``qwenpaw.agents`` package. Resolving a public contract initializes
built-in backends; host ownership checks use the lightweight registry module.
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qwenpaw.agents.memory.base_memory_manager import (
        AutoMemorySearchOptions,
        BaseMemoryManager,
        MemoryBackendContext,
        MemoryBackendRegistration,
        MemoryBackendRegistry,
        MemoryBackendUnavailableError,
        NO_RELEVANT_MEMORIES,
        get_memory_manager_backend,
        memory_registry,
    )

# pylint: disable=undefined-all-variable
__all__ = [
    "AutoMemorySearchOptions",
    "BaseMemoryManager",
    "MemoryBackendContext",
    "MemoryBackendRegistration",
    "MemoryBackendRegistry",
    "MemoryBackendUnavailableError",
    "NO_RELEVANT_MEMORIES",
    "get_memory_manager_backend",
    "memory_registry",
]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(
        import_module("qwenpaw.agents.memory.base_memory_manager"),
        name,
    )
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
