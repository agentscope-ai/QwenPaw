# -*- coding: utf-8 -*-
"""Core integration points for the Computer Use native runtime."""

from .runtime import (
    COMPUTER_USE_PROTOCOL_VERSION,
    HostRuntimeProvider,
    RuntimeCapability,
    RuntimeStatus,
    get_current_computer_use_turn_id,
    set_current_computer_use_turn_id,
)

__all__ = [
    "COMPUTER_USE_PROTOCOL_VERSION",
    "HostRuntimeProvider",
    "RuntimeCapability",
    "RuntimeStatus",
    "get_current_computer_use_turn_id",
    "set_current_computer_use_turn_id",
]
