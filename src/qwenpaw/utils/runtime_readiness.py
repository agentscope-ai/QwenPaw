# -*- coding: utf-8 -*-
"""Process-wide runtime readiness gate for request admission.

The application lifespan runs a heavy background startup phase after the
HTTP server starts listening.  ``app.state.startup_ready`` only tracks the
core agents, so chat requests can otherwise enter while plugin projections,
tool registries and provider state are still being populated.

This module owns the *runtime* readiness signal used by request handlers
and by :class:`~qwenpaw.runtime.builder.AgentBuilder`.  Keeping the state
here (instead of on ``app.state``) lets non-HTTP entry points such as
channels, cron jobs and sub-agents consult the same gate without importing
the FastAPI application.

The gate is intentionally inert until :func:`bind_runtime_ready` is called.
CLI, embedded and unit-test callers therefore keep their existing
behaviour and never block on a lifecycle they do not run.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_WAIT_TIMEOUT_SECONDS = 180.0
DEFAULT_HTTP_WAIT_TIMEOUT_SECONDS = 5.0

_WAIT_TIMEOUT_ENV = "QWENPAW_RUNTIME_READY_TIMEOUT"
_HTTP_WAIT_TIMEOUT_ENV = "QWENPAW_RUNTIME_READY_HTTP_TIMEOUT"

_ready_event: Optional[asyncio.Event] = None
_failure_reason: Optional[str] = None
_bound_at: Optional[float] = None
_bound_loop: Optional[asyncio.AbstractEventLoop] = None


class RuntimeNotReadyError(RuntimeError):
    """The runtime did not become ready within the caller's budget."""

    def __init__(self, reason: str, waited_seconds: float) -> None:
        self.reason = reason
        self.waited_seconds = waited_seconds
        super().__init__(
            "Runtime is not ready "
            f"({reason}; startup has been in progress for "
            f"{waited_seconds:.1f}s). Please retry after startup completes.",
        )


def _read_timeout(env_name: str, default: float) -> float:
    """Read one non-negative timeout override from the environment."""
    raw = os.getenv(env_name, "")
    if not raw:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Ignoring invalid %s=%r; using %.1fs",
            env_name,
            raw,
            default,
        )
        return default
    if value < 0:
        logger.warning(
            "Ignoring negative %s=%r; using %.1fs",
            env_name,
            raw,
            default,
        )
        return default
    return value


def default_wait_timeout() -> float:
    """Return the default readiness budget for non-HTTP callers."""
    return _read_timeout(_WAIT_TIMEOUT_ENV, DEFAULT_WAIT_TIMEOUT_SECONDS)


def http_wait_timeout() -> float:
    """Return the short readiness budget used before HTTP admission."""
    return _read_timeout(
        _HTTP_WAIT_TIMEOUT_ENV,
        DEFAULT_HTTP_WAIT_TIMEOUT_SECONDS,
    )


def bind_runtime_ready(event: asyncio.Event) -> None:
    """Bind the lifespan-owned readiness event.

    Calling this again replaces the previous binding.  The previous event
    (if any) is left untouched; callers that already hold a reference may
    still observe its state.
    """
    global _ready_event, _failure_reason, _bound_at, _bound_loop
    _ready_event = event
    _failure_reason = None
    _bound_at = time.monotonic()
    try:
        _bound_loop = asyncio.get_running_loop()
    except RuntimeError:
        _bound_loop = None


def reset_runtime_readiness() -> None:
    """Clear the process-wide binding (lifespan teardown and tests)."""
    global _ready_event, _failure_reason, _bound_at, _bound_loop
    _ready_event = None
    _failure_reason = None
    _bound_at = None
    _bound_loop = None


def mark_runtime_ready() -> None:
    """Publish a successful background startup."""
    global _failure_reason
    if _ready_event is None:
        return
    _failure_reason = None
    _ready_event.set()


def mark_runtime_failed(reason: str) -> None:
    """Publish a failed background startup and wake every waiter.

    A late failure after a successful publication is ignored: the runtime
    was usable, and overwriting readiness would turn a teardown error into
    permanent request rejection.
    """
    global _failure_reason
    if _ready_event is None:
        return
    if _ready_event.is_set() and _failure_reason is None:
        return
    _failure_reason = reason or "background startup failed"
    _ready_event.set()


def is_runtime_ready() -> bool:
    """Return whether request admission is currently allowed.

    An unbound gate is treated as ready: CLI and embedded callers do not
    run the application lifespan and must not be blocked by it.
    """
    if _ready_event is None:
        return True
    return _ready_event.is_set() and _failure_reason is None


def runtime_failure_reason() -> str | None:
    """Return the recorded startup failure reason, if any."""
    return _failure_reason


def _startup_elapsed_seconds() -> float:
    if _bound_at is None:
        return 0.0
    return max(0.0, time.monotonic() - _bound_at)


async def wait_runtime_ready(timeout: float | None = None) -> None:
    """Wait until the runtime is ready or raise :class:`RuntimeNotReadyError`.

    Args:
        timeout: Budget in seconds.  ``None`` uses
            ``QWENPAW_RUNTIME_READY_TIMEOUT`` (default 180s).  ``0`` checks
            the current state without yielding.
    """
    event = _ready_event
    if event is None:
        return

    if _failure_reason is not None:
        raise RuntimeNotReadyError(
            _failure_reason,
            _startup_elapsed_seconds(),
        )
    if event.is_set():
        return

    if _bound_loop is not None:
        current_loop = asyncio.get_running_loop()
        if current_loop is not _bound_loop:
            raise RuntimeNotReadyError(
                "runtime gate is bound to a different event loop",
                _startup_elapsed_seconds(),
            )

    budget = default_wait_timeout() if timeout is None else max(0.0, timeout)
    if budget == 0:
        raise RuntimeNotReadyError(
            "startup timeout",
            _startup_elapsed_seconds(),
        )

    try:
        await asyncio.wait_for(event.wait(), timeout=budget)
    except asyncio.TimeoutError as exc:
        reason = _failure_reason or "startup timeout"
        raise RuntimeNotReadyError(
            reason,
            _startup_elapsed_seconds(),
        ) from exc

    # ``mark_runtime_failed`` sets the event as well so waiters wake up;
    # convert that wake-up into the explicit failure it represents.
    if _failure_reason is not None:
        raise RuntimeNotReadyError(
            _failure_reason,
            _startup_elapsed_seconds(),
        )


__all__ = [
    "DEFAULT_HTTP_WAIT_TIMEOUT_SECONDS",
    "DEFAULT_WAIT_TIMEOUT_SECONDS",
    "RuntimeNotReadyError",
    "bind_runtime_ready",
    "default_wait_timeout",
    "http_wait_timeout",
    "is_runtime_ready",
    "mark_runtime_failed",
    "mark_runtime_ready",
    "reset_runtime_readiness",
    "runtime_failure_reason",
    "wait_runtime_ready",
]
