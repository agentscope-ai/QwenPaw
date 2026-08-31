# -*- coding: utf-8 -*-
"""Managed terminal sessions with bounded background output capture."""

from .capture import BackgroundCapture, CaptureChunk
from .manager import TerminalSessionManager
from .models import SessionResult, SessionState
from .process_tree import ProcessSupervisor

__all__ = [
    "BackgroundCapture",
    "CaptureChunk",
    "ProcessSupervisor",
    "SessionResult",
    "SessionState",
    "TerminalSessionManager",
]
