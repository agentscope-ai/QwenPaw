# -*- coding: utf-8 -*-
"""Tool call lifecycle management for QwenPaw."""

from ._context import CancelReason, OffloadReason, ToolCallContext
from ._coordinator import ToolCoordinator
from ._ctxvars import get_call_context, reset_call_context, set_call_context
from ._entry import ToolCallEntry, ToolCallStatus
from ._hooks import ToolHookRegistry
from ._middleware import ToolCoordinatorMiddleware
from ._stream import ToolStream
from ._timeout_helper import (
    COORDINATOR_OWNED_EXEC_TIMEOUT_SECS,
    MIN_BACKGROUND_WINDOW_SECS,
    OFFLOAD_TIMEOUT_RATIO,
    arm_kill_deadline,
    cancellable_wait,
    effective_timeout,
)

__all__ = [
    "COORDINATOR_OWNED_EXEC_TIMEOUT_SECS",
    "CancelReason",
    "MIN_BACKGROUND_WINDOW_SECS",
    "OFFLOAD_TIMEOUT_RATIO",
    "OffloadReason",
    "ToolCallContext",
    "ToolCallEntry",
    "ToolCallStatus",
    "ToolCoordinator",
    "ToolCoordinatorMiddleware",
    "ToolHookRegistry",
    "ToolStream",
    "arm_kill_deadline",
    "cancellable_wait",
    "effective_timeout",
    "get_call_context",
    "reset_call_context",
    "set_call_context",
]
