# -*- coding: utf-8 -*-
"""Agent hooks package.

This package provides hook implementations for CoPawAgent that follow
AgentScope's hook interface (any Callable).

Available Hooks:
    - BootstrapHook: First-time setup guidance
    - MemoryCompactionHook: Automatic context window management

Example:
    >>> from rypaw.agents.hooks import BootstrapHook, MemoryCompactionHook
    >>> from pathlib import Path
    >>>
    >>> # Create hooks (they are callables following AgentScope's interface)
    >>> bootstrap = BootstrapHook(Path("~/.copaw"), language="zh")
    >>> memory_compact = MemoryCompactionHook(
    ...     memory_manager=mm,
    ...     memory_compact_threshold=100000,
    ... )
    >>>
    >>> # Register with agent using AgentScope's register_instance_hook
    >>> agent.register_instance_hook("pre_reasoning", "bootstrap", bootstrap)
    >>> agent.register_instance_hook(
    ...     "pre_reasoning", "compact", memory_compact
    ... )
"""

from .bootstrap import BootstrapHook
from .memory_compaction import MemoryCompactionHook

__all__ = [
    "BootstrapHook",
    "MemoryCompactionHook",
]
