# -*- coding: utf-8 -*-
"""QwenPaw runtime — agent lifecycle, streaming, and tool guard."""

from .runtime import Runtime

# GuardedFunctionTool is deprecated; use governance.PolicyGuardedTool instead.
# Kept for backward compatibility of existing imports.
from .tool_guard import GuardedFunctionTool  # noqa: F401 (deprecated)

__all__ = ["Runtime"]
