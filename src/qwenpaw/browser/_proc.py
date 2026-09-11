# -*- coding: utf-8 -*-
"""Shared synchronous process lifecycle helpers for browser resources."""

from __future__ import annotations

import contextlib
from typing import Any


def _alive(proc: Any) -> bool:
    """Return whether either supported process family is still running."""
    poll = getattr(proc, "poll", None)
    if poll is not None:
        return poll() is None
    is_alive = getattr(proc, "is_alive", None)
    return bool(is_alive()) if is_alive is not None else False


def _wait(proc: Any, timeout: float) -> None:
    """Wait for and reap either subprocess or multiprocessing instances."""
    waiter = getattr(proc, "wait", None) or getattr(proc, "join", None)
    if waiter is None:
        return
    with contextlib.suppress(Exception):
        waiter(timeout)


def kill_process_sync(proc: Any, *, grace: float = 1.0) -> None:
    """Terminate one child process idempotently: TERM -> wait -> KILL."""
    if not _alive(proc):
        _wait(proc, 0)
        return
    for signaller in ("terminate", "kill"):
        send = getattr(proc, signaller, None)
        if send is None:
            continue
        with contextlib.suppress(ProcessLookupError, OSError):
            send()
        _wait(proc, grace)
        if not _alive(proc):
            return
