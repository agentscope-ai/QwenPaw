# -*- coding: utf-8 -*-
"""Core integration points for the Computer Use native runtime."""

from .runtime import (
    HostRuntimeProvider,
    RuntimeCapability,
    get_current_computer_use_turn_id,
    set_current_computer_use_turn_id,
)

__all__ = [
    "HostRuntimeProvider",
    "RuntimeCapability",
    "get_current_computer_use_turn_id",
    "set_current_computer_use_turn_id",
]
