# -*- coding: utf-8 -*-
"""Agent hooks package.

This package provides hook implementations for CoPawAgent that follow
AgentScope's hook interface (any Callable).

Available Hooks:
    - BootstrapHook: First-time setup guidance
    - MemoryCompactionHook: Automatic context window management
    - HandoffHook: Session continuity via handoff manifests
"""

from .bootstrap import BootstrapHook
from .memory_compaction import MemoryCompactionHook
from .handoff import HandoffHook

__all__ = [
    "BootstrapHook",
    "MemoryCompactionHook",
    "HandoffHook",
]
