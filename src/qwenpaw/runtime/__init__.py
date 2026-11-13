# -*- coding: utf-8 -*-
"""QwenPaw runtime — agent lifecycle, streaming, and tool guard."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runtime import Runtime as Runtime

__all__ = ["Runtime"]


def __getattr__(name):
    # Backend declaration imports must not assemble the agent runtime.
    if name == "Runtime":
        from .runtime import Runtime

        globals()[name] = Runtime
        return Runtime
    if name == "GuardedFunctionTool":
        # Deprecated compatibility export; prefer PolicyGuardedTool.
        from .tool_guard import GuardedFunctionTool

        globals()[name] = GuardedFunctionTool
        return GuardedFunctionTool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
