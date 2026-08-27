# -*- coding: utf-8 -*-
# pylint: disable=protected-access,too-many-branches,too-many-statements
"""Short cross-process locks for filesystem Runtime stores.

Lock files are stable coordination inodes and are intentionally never unlinked
after release.  Removing an advisory lock file can create two lock domains when
one process still has the old inode open.
"""

from __future__ import annotations

import errno
import json
import logging
import os
from pathlib import Path
import socket
import stat
import sys
import threading
import time
from types import TracebackType
from uuid import uuid4

from .errors import LockTimeoutError, RuntimeFileValidationError

logger = logging.getLogger("qwenpaw.creator.runtime_files.locking")
_HELD_LOCKS: dict[tuple[str, int], dict[str, object]] = {}
_HELD_LOCKS_GUARD = threading.RLock()


def _clear_inherited_lock_owners() -> None:
    """A forked child does not own the parent's Python lock registry."""

    with _HELD_LOCKS_GUARD:
        _HELD_LOCKS.clear()


if hasattr(os, "register_at_fork"):  # pragma: posix
    os.register_at_fork(after_in_child=_clear_inherited_lock_owners)

# A Runtime lock protects only short, local filesystem transitions. Waiting
# longer hides a leaked/nested lock instead of fixing it, so ten seconds stays
# a deadlock fuse. Contention is reduced structurally by domain-sharded Runtime
# locks and by the writer admission gate below.
DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0

if os.name == "nt":  # pragma: posix no cover
    import msvcrt

    def _try_lock(descriptor: int, *, shared: bool) -> None:
        """Windows byte-range lock; shared degrades to exclusive.

        ``msvcrt.locking`` exposes only exclusive region locks, so reader
        locks serialize on Windows.  Correctness (mutual exclusion with
        writers) is preserved; only reader concurrency is reduced.
        """

        del shared
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)

    def _unlock(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)

    _BLOCKED_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EDEADLK})
else:
    import fcntl

    def _try_lock(descriptor: int, *, shared: bool) -> None:
        lock_op = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        fcntl.flock(descriptor, lock_op | fcntl.LOCK_NB)

    def _unlock(descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)

    _BLOCKED_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN})


class CrossProcessFileLock:
    """An exclusive, process-crash-safe cross-platform file lock.

    POSIX uses ``fcntl.flock``; Windows uses ``msvcrt.locking`` byte-range
    locks.  The lock only protects writers that share this primitive.  Runtime
    locks must therefore be acquired at a single documented boundary and kept
    out of model/provider calls.  The operating system releases the lock when
    the descriptor or process exits; the file itself contains no authoritative
    state.

    Pass ``shared=True`` for a ``LOCK_SH`` reader lock.  On POSIX reader locks
    do not block each other, so concurrent read-only polling never serializes
    against itself; they still exclude ``LOCK_EX`` writers (and vice versa).
    POSIX ``flock`` merges multiple descriptors on the same inode within one
    process, so reader locks are safe across threads of the same process.  On
    Windows shared locks degrade to exclusive locks.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        timeout_seconds: float | None = DEFAULT_LOCK_TIMEOUT_SECONDS,
        poll_interval_seconds: float = 0.01,
        mode: int = 0o600,
        shared: bool = False,
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
        self._descriptor: int | None = None
        self._identity = str(self.path.absolute())
        self._owner: dict[str, object] | None = None
        self._reader_metadata_path: Path | None = None
        self._held_key: tuple[str, int] | None = None
        self._constructed_by = self._caller_metadata()

    @staticmethod
    def _caller_metadata() -> dict[str, object]:
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

    def _waiter_metadata(self, *, phase: str) -> dict[str, object]:
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

    @staticmethod
    def _write_metadata(descriptor: int, value: dict[str, object]) -> None:
        payload = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")[:8192]
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, payload)

    @staticmethod
    def _clear_metadata(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)

    @staticmethod
    def _read_metadata(path: Path) -> dict[str, object]:
        try:
            raw = path.read_bytes()[:8192]
            value = json.loads(raw) if raw else {}
        except (OSError, ValueError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _reader_metadata_root(self) -> Path:
        return self.path.with_name(f"{self.path.name}.readers")

    def _write_reader_metadata(self, owner: dict[str, object]) -> None:
        root = self._reader_metadata_root()
        root.mkdir(mode=0o700, parents=False, exist_ok=True)
        root_stat = root.lstat()
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(
            root_stat.st_mode,
        ):
            raise OSError(
                f"reader metadata root is not a real directory: {root}",
            )
        owner_id = str(owner["ownerId"])
        target = root / f"{owner_id}.json"
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(target, flags, 0o600)
        try:
            os.write(
                descriptor,
                json.dumps(
                    owner,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("utf-8")[:8192],
            )
        finally:
            os.close(descriptor)
        self._reader_metadata_path = target

    def _read_holder_metadata(self) -> dict[str, object]:
        holder = self._read_metadata(self.path)
        readers: list[dict[str, object]] = []
        root = self._reader_metadata_root()
        try:
            candidates = list(root.glob("*.json")) if root.is_dir() else []
        except OSError:
            candidates = []
        for candidate in candidates[:100]:
            value = self._read_metadata(candidate)
            if value:
                readers.append(value)
        if readers:
            holder = {**holder, "observedReaders": readers}
        return holder

    def _clear_stale_reader_metadata(self) -> None:
        root = self._reader_metadata_root()
        try:
            candidates = list(root.glob("*.json")) if root.is_dir() else []
        except OSError:
            return
        for candidate in candidates:
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "failed to clear stale reader lock metadata %s",
                    candidate,
                    exc_info=True,
                )

    def acquired(self) -> bool:
        return self._descriptor is not None

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

    def acquire(self) -> CrossProcessFileLock:
        if self._descriptor is not None:
            raise RuntimeFileValidationError(
                f"lock is not re-entrant: {self.path}",
            )
        held_key = (self._identity, threading.get_ident())
        with _HELD_LOCKS_GUARD:
            held = _HELD_LOCKS.get(held_key)
            if held is not None:
                message = (
                    "same-thread nested Runtime lock acquisition "
                    + "would deadlock: "
                )
                raise RuntimeFileValidationError(
                    f"{message}path={self.path} held={held!r}",
                )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW

        def open_descriptor(path: Path) -> int:
            opened = os.open(path, flags, self.mode)
            if hasattr(os, "fchmod"):
                os.fchmod(opened, self.mode)
            return opened

        descriptor = open_descriptor(self.path)
        # A short exclusive admission gate gives waiting writers priority over
        # newly arriving shared poll readers. Without it, repeated UI reads can
        # continuously reacquire LOCK_SH and starve a commit/stop writer until
        # its timeout. Readers release the gate immediately after acquiring the
        # real shared lock, so they remain concurrent with one another.
        try:
            gate_descriptor = open_descriptor(
                self.path.with_name(f"{self.path.name}.gate"),
            )
        except BaseException:
            os.close(descriptor)
            raise
        gate_acquired = False
        started = time.monotonic()
        waiter = self._waiter_metadata(phase="admission")
        try:
            while True:
                try:
                    _try_lock(gate_descriptor, shared=False)
                    gate_acquired = True
                    self._write_metadata(gate_descriptor, waiter)
                    break
                except OSError as exc:
                    if exc.errno not in _BLOCKED_ERRNOS:
                        raise
                if self.timeout_seconds is not None:
                    elapsed = time.monotonic() - started
                    if elapsed >= self.timeout_seconds:
                        logger.warning(
                            "lock admission gate %s timed out after %.2fs",
                            self.path,
                            elapsed,
                        )
                        raise LockTimeoutError(
                            self.path,
                            self.timeout_seconds,
                            phase="admission",
                            waiter=waiter,
                            holder=self._read_metadata(
                                self.path.with_name(f"{self.path.name}.gate"),
                            ),
                        )
                    remaining = self.timeout_seconds - elapsed
                    time.sleep(min(self.poll_interval_seconds, remaining))
                else:
                    time.sleep(self.poll_interval_seconds)
            while True:
                try:
                    _try_lock(descriptor, shared=self.shared)
                    owner = {
                        **waiter,
                        "phase": "held",
                        "acquiredAfterSeconds": round(
                            time.monotonic() - started,
                            6,
                        ),
                        "acquiredAtEpoch": time.time(),
                    }
                    if not self.shared:
                        self._clear_stale_reader_metadata()
                        self._write_metadata(descriptor, owner)
                    else:
                        try:
                            self._write_reader_metadata(owner)
                        except OSError:
                            logger.warning(
                                "failed to persist shared lock metadata "
                                + "for %s",
                                self.path,
                                exc_info=True,
                            )
                    self._descriptor = descriptor
                    self._owner = owner
                    self._held_key = held_key
                    with _HELD_LOCKS_GUARD:
                        _HELD_LOCKS[held_key] = owner
                    self._log_acquired(time.monotonic() - started)
                    return self
                except OSError as exc:
                    if exc.errno not in _BLOCKED_ERRNOS:
                        raise
                if self.timeout_seconds is not None:
                    elapsed = time.monotonic() - started
                    if elapsed >= self.timeout_seconds:
                        logger.warning(
                            "lock %s timed out after %.2fs",
                            self.path,
                            elapsed,
                        )
                        raise LockTimeoutError(
                            self.path,
                            self.timeout_seconds,
                            phase="resource",
                            waiter={**waiter, "phase": "resource"},
                            holder=self._read_holder_metadata(),
                        )
                    remaining = self.timeout_seconds - elapsed
                    time.sleep(min(self.poll_interval_seconds, remaining))
                else:
                    time.sleep(self.poll_interval_seconds)
        except BaseException:
            os.close(descriptor)
            raise
        finally:
            if gate_acquired:
                try:
                    self._clear_metadata(gate_descriptor)
                finally:
                    _unlock(gate_descriptor)
            os.close(gate_descriptor)

    def release(self) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            return
        self._descriptor = None
        held_key = self._held_key
        self._held_key = None
        if held_key is not None:
            with _HELD_LOCKS_GUARD:
                _HELD_LOCKS.pop(held_key, None)
        self._owner = None
        try:
            try:
                if self.shared:
                    reader_metadata_path = self._reader_metadata_path
                    self._reader_metadata_path = None
                    if reader_metadata_path is not None:
                        reader_metadata_path.unlink(missing_ok=True)
                else:
                    self._clear_metadata(descriptor)
            finally:
                _unlock(descriptor)
            logger.debug("released lock %s", self.path)
        finally:
            os.close(descriptor)

    def __enter__(self) -> CrossProcessFileLock:
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.release()
