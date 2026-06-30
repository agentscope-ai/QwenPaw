# -*- coding: utf-8 -*-
"""Backward-compatibility shim.

All public API has moved to ``qwenpaw.loop.gates``.
This module re-exports everything for existing imports.
"""
from .gates import (  # noqa: F401
    DoomLoopGate,
    StopAction,
    StopGate,
    StopHandler,
    StopHandlerRegistration,
    StopHandlerResult,
)

__all__ = [
    "DoomLoopGate",
    "StopAction",
    "StopGate",
    "StopHandler",
    "StopHandlerRegistration",
    "StopHandlerResult",
]
