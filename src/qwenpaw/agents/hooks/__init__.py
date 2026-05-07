# -*- coding: utf-8 -*-
"""Agent hooks package.

This package provides hook implementations for QwenPawAgent that follow
AgentScope's hook interface (any Callable).

Available Hooks:
    - BootstrapHook: First-time setup guidance
    - MemoryHook: Auto memory retrieval and storage (LanceDB + 百炼)
"""

from .bootstrap import BootstrapHook
from .memory_hook import MemoryHook

__all__ = [
    "BootstrapHook",
    "MemoryHook",
]
