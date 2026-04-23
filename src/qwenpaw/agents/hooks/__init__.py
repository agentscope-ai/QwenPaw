# -*- coding: utf-8 -*-
"""Agent hooks package.

This package provides hook implementations for QwenPawAgent that follow
AgentScope's hook interface (any Callable).

Available Hooks:
    - BootstrapHook: First-time setup guidance
"""

from .bootstrap import BootstrapHook

__all__ = [
    "BootstrapHook",
]
