# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""In-process per-path write locks for filesystem Runtime stores.

QwenPaw Creator's supported topology is one backend process (matching
``src/qwenpaw/utils/io_utils.py``): every supported writer runs in this
process, so writer mutual exclusion only needs threading primitives keyed by
the normalized lock path.  No lock file is ever created — the ``path`` is a
pure identity key and reads throughout the Runtime stores are lock-free
against atomically replaced files.  Revisit this decision only if
multi-process writers are ever supported.

The class keeps its historical name and constructor signature so the ~30
call sites and the ``LockTimeoutError`` -> busy mapping in
``api/dependencies.py`` stay unchanged.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time
from types import TracebackType
from typing import Any
from uuid import uuid4

from .errors import LockTimeoutError, RuntimeFileValidationError

logger = logging.getLogger("qwenpaw.creator.runtime_files.locking")

# A Runtime lock protects only short, local filesystem transitions. Waiting
# longer hides a leaked/nested lock instead of fixing it, so ten seconds stays
# a deadlock fuse.  Readers never take locks, so contention is limited to the
# rare write/write overlap within one Project domain.
DEFAULT_LOCK_TIMEOUT_SECONDS = float(
    os.environ.get("CREATOR_LOCK_TIMEOUT_SECONDS", "10.0"),
)

_SHARED_HOLDER_REPORT_LIMIT = 20


class _PathLockState:
    """Writer-priority read/write lock state for one normalized path.

    Writer priority replaces the old flock admission gate: a waiting
    exclusive holder blocks newly arriving shared holders, so repeated
    shared lifecycle acquisitions can never starve a delete/commit.
    """

    __slots__ = (
        "condition",
        "active_shared",
        "active_exclusive",
        "waiting_exclusive",
        "exclusive_owner",
        "shared_owners",
        "refs",
    )

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.active_shared = 0
        self.active_exclusive = False
        self.waiting_exclusive = 0
        self.exclusive_owner: dict[str, Any] | None = None
        self.shared_owners: dict[str, dict[str, Any]] = {}
        self.refs = 0


_PATH_LOCKS: dict[str, _PathLockState] = {}
_PATH_LOCKS_GUARD = threading.Lock()
_HELD_LOCKS: dict[tuple[str, int], dict[str, Any]] = {}
_HELD_LOCKS_GUARD = threading.RLock()


def _clear_inherited_lock_owners() -> None:
    """A forked child owns none of the parent's in-process locks."""

    with _HELD_LOCKS_GUARD:
        _HELD_LOCKS.clear()
    with _PATH_LOCKS_GUARD:
        _PATH_LOCKS.clear()


if hasattr(os, "register_at_fork"):  # pragma: posix
    os.register_at_fork(after_in_child=_clear_inherited_lock_owners)


def _lock_key(path: Path) -> str:
    """One canonical process-local lock key per filesystem path."""

    return os.path.normcase(str(path.resolve(strict=False)))


def _checkout(key: str) -> _PathLockState:
    with _PATH_LOCKS_GUARD:
        state = _PATH_LOCKS.get(key)
        if state is None:
            state = _PathLockState()
            _PATH_LOCKS[key] = state
        state.refs += 1
        return state


def _checkin(key: str, state: _PathLockState) -> None:
    # Refcounted cleanup keeps the registry bounded even for unbounded key
    # spaces such as per-identity idempotency operation locks.
    with _PATH_LOCKS_GUARD:
        state.refs -= 1
        if state.refs <= 0 and _PATH_LOCKS.get(key) is state:
            del _PATH_LOCKS[key]


class CrossProcessFileLock:
    """An in-process, per-path writer lock (historical name kept).

    ``shared=True`` takes the shared side of a writer-priority read/write
    lock.  Its only remaining consumer is the Project lifecycle lock: Runtime
    domain writers hold the shared side so they exclude Project
    delete/commit (exclusive side) without serializing against one another.

    ``mode`` and ``poll_interval_seconds`` are retained for API
    compatibility; no file is created and waiting uses condition variables.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        timeout_seconds: float | None = DEFAULT_LOCK_TIMEOUT_SECONDS,
        poll_interval_seconds: float = 0.01,
        mode: int = 0o600,
        shared: bool = False,
        cross_thread_hold: bool = False,
    ) -> None:
        self.path = Path(path)
        if timeout_seconds is not None and timeout_seconds < 0:
            raise RuntimeFileValidationError(
                "lock timeout must be non-negative or None",
            )
        if poll_interval_seconds <= 0:
            raise RuntimeFileValidationError(
                "lock poll interval must be positive",
            )
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.mode = mode
        self.shared = shared
        # A detached hold is acquired on one executor thread (often a bare
        # ``asyncio.to_thread(lock.acquire)``) and released from another
        # after async work in between. The worker thread returns to the
        # pool while the lock stays held, so the per-thread nesting guard
        # must neither register this hold nor blame later unrelated jobs
        # that happen to reuse the same pool thread (field incident
        # 2026-09-01: mainline delta persists crashed with a false
        # "same-thread nested" error whenever they landed on the worker
        # that had just performed a route's detached lifecycle acquire).
        self.cross_thread_hold = cross_thread_hold
        self._identity = _lock_key(self.path)
        self._state: _PathLockState | None = None
        self._owner: dict[str, Any] | None = None
        self._held_key: tuple[str, int] | None = None
        self._constructed_by = self._caller_metadata()

    @staticmethod
    def _caller_metadata() -> dict[str, Any]:
        try:
            frame = sys._getframe(1)
            while (
                frame.f_back is not None
                and frame.f_code.co_filename == __file__
            ):
                frame = frame.f_back
            return {
                "file": Path(frame.f_code.co_filename).name,
                "function": frame.f_code.co_name,
                "line": frame.f_lineno,
            }
        except (ValueError, AttributeError):  # pragma: no cover - defensive
            return {}

    def _waiter_metadata(self, *, phase: str) -> dict[str, Any]:
        return {
            "ownerId": f"lock-owner-{uuid4().hex}",
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "threadId": threading.get_ident(),
            "threadName": threading.current_thread().name,
            "mode": "shared" if self.shared else "exclusive",
            "phase": phase,
            "waitStartedAtEpoch": time.time(),
            "caller": self._constructed_by,
            "acquireCaller": self._caller_metadata(),
        }

    def acquired(self) -> bool:
        return self._state is not None

    def _log_acquired(self, elapsed: float) -> None:
        if elapsed > 0.5:
            logger.warning(
                "acquired lock %s after %.2fs (shared=%s)",
                self.path,
                elapsed,
                self.shared,
            )
        else:
            logger.debug(
                "acquired lock %s (shared=%s)",
                self.path,
                self.shared,
            )

    def _holder_metadata(self, state: _PathLockState) -> dict[str, Any]:
        # Caller must hold ``state.condition``.
        if state.exclusive_owner is not None:
            return dict(state.exclusive_owner)
        shared = list(state.shared_owners.values())
        if shared:
            return {
                "observedReaders": shared[:_SHARED_HOLDER_REPORT_LIMIT],
            }
        return {}

    def _timeout_error(
        self,
        state: _PathLockState,
        waiter: dict[str, Any],
    ) -> LockTimeoutError:
        logger.warning(
            "lock %s timed out after %.2fs",
            self.path,
            self.timeout_seconds or 0.0,
        )
        return LockTimeoutError(
            self.path,
            self.timeout_seconds,
            phase="resource",
            waiter=waiter,
            holder=self._holder_metadata(state),
        )

    def acquire(self) -> CrossProcessFileLock:
        if self._state is not None:
            raise RuntimeFileValidationError(
                f"lock is not re-entrant: {self.path}",
            )
        held_key = (self._identity, threading.get_ident())
        with _HELD_LOCKS_GUARD:
            held = (
                None
                if self.cross_thread_hold
                else _HELD_LOCKS.get(
                    held_key,
                )
            )
            if held is not None:
                # The same pool thread already appears as a holder. This is
                # usually NOT a nested call stack: holds that span an await
                # return their thread to the executor pool, and the next
                # request reused it. Waiting is safe — flock release happens
                # on whichever thread resumes the holder — so fall through
                # to the normal timeout-bounded wait instead of failing the
                # innocent request. A genuine nested acquisition surfaces as
                # a retryable LockTimeoutError after the deadline.
                logger.warning(
                    "same-thread lock reuse detected for %s "
                    "(likely executor thread reuse); waiting with timeout. "
                    "holder=%r",
                    self.path,
                    held,
                )

        started = time.monotonic()
        deadline = (
            None
            if self.timeout_seconds is None
            else started + self.timeout_seconds
        )
        waiter = self._waiter_metadata(phase="resource")
        state = _checkout(self._identity)
        owner: dict[str, Any] | None = None
        try:
            with state.condition:
                if self.shared:
                    # Writer priority: a waiting exclusive holder closes
                    # admission to newly arriving shared holders.
                    while state.active_exclusive or state.waiting_exclusive:
                        self._wait(state, deadline, waiter)
                    state.active_shared += 1
                    owner = self._held_owner(waiter, started)
                    state.shared_owners[str(owner["ownerId"])] = owner
                else:
                    state.waiting_exclusive += 1
                    try:
                        while state.active_exclusive or state.active_shared:
                            self._wait(state, deadline, waiter)
                        state.active_exclusive = True
                        owner = self._held_owner(waiter, started)
                        state.exclusive_owner = owner
                    finally:
                        state.waiting_exclusive -= 1
                        state.condition.notify_all()
        except BaseException:
            _checkin(self._identity, state)
            raise
        self._state = state
        self._owner = owner
        if self.cross_thread_hold:
            self._held_key = None
        else:
            self._held_key = held_key
            with _HELD_LOCKS_GUARD:
                _HELD_LOCKS[held_key] = owner
        self._log_acquired(time.monotonic() - started)
        return self

    def _held_owner(
        self,
        waiter: dict[str, Any],
        started: float,
    ) -> dict[str, Any]:
        return {
            **waiter,
            "phase": "held",
            "acquiredAfterSeconds": round(time.monotonic() - started, 6),
            "acquiredAtEpoch": time.time(),
        }

    def _wait(
        self,
        state: _PathLockState,
        deadline: float | None,
        waiter: dict[str, Any],
    ) -> None:
        # Caller must hold ``state.condition`` and re-check its predicate.
        if deadline is None:
            state.condition.wait()
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise self._timeout_error(state, waiter)
        state.condition.wait(remaining)

    def acquire_detached(self) -> CrossProcessFileLock:
        """Acquire for a holder that outlives the acquiring thread.

        ``await asyncio.to_thread(lock.acquire)`` acquires on a pooled
        executor thread that returns to the pool immediately, while the
        coroutine keeps holding the lock across ``await`` boundaries.
        Keeping the thread-based holder registration would falsely flag
        unrelated work later scheduled onto that reused thread (for example
        a shared poll read of the same Project lock) as a same-thread nested
        acquisition.  Dropping the thread association here, before the
        worker thread can pick up other work, keeps the nesting guard for
        true same-stack nesting; a cross-owner wait stays bounded by the
        lock timeout fuse.  ``release`` keeps working from any thread.
        """

        self.acquire()
        held_key = self._held_key
        self._held_key = None
        if held_key is not None:
            with _HELD_LOCKS_GUARD:
                _HELD_LOCKS.pop(held_key, None)
        return self

    def release(self) -> None:
        state = self._state
        if state is None:
            return
        self._state = None
        held_key = self._held_key
        self._held_key = None
        if held_key is not None:
            with _HELD_LOCKS_GUARD:
                _HELD_LOCKS.pop(held_key, None)
        owner = self._owner
        self._owner = None
        with state.condition:
            if self.shared:
                state.active_shared -= 1
                if owner is not None:
                    state.shared_owners.pop(str(owner.get("ownerId")), None)
            else:
                state.active_exclusive = False
                state.exclusive_owner = None
            state.condition.notify_all()
        _checkin(self._identity, state)
        logger.debug("released lock %s", self.path)

    def __enter__(self) -> CrossProcessFileLock:
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, exc_traceback
        self.release()
