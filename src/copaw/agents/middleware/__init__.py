# -*- coding: utf-8 -*-
"""Middleware package for CoPaw agents.

Provides pluggable middleware that runs as pre_reasoning hooks,
adding safety and intelligence to the agent loop.
"""

from .loop_detection import LoopDetectionMiddleware
from .todo_reminder import TodoReminderMiddleware
from .stop_interrupt import StopInterruptMiddleware
from .auto_poll import AutoPollMiddleware

__all__ = [
    "LoopDetectionMiddleware",
    "TodoReminderMiddleware",
    "StopInterruptMiddleware",
    "AutoPollMiddleware",
]
