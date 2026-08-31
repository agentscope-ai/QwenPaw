# -*- coding: utf-8 -*-
"""Public terminal state and result models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SessionState(str, Enum):
    CREATING = "creating"
    IDLE = "idle"
    RUNNING = "running"
    INTERRUPTING = "interrupting"
    TERMINATING = "terminating"
    CLOSED = "closed"


@dataclass(frozen=True)
class SessionResult:
    session_id: str | None
    chunk_id: str
    running: bool
    exit_code: int | None
    output: str
    original_bytes: int
    omitted_bytes: int
    next_cursor: int
    wall_time_ms: int
    tty: bool
    degraded: bool = False
    timed_out: bool = False
    output_bytes: int = 0
    pending_bytes: int = 0
    output_drained: bool = True
    terminated: bool = False
