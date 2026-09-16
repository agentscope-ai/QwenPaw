# -*- coding: utf-8 -*-
"""跨进程维护门禁：共享操作租约与独占维护租约。"""

from __future__ import annotations

import asyncio
import contextvars
import errno
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path


class MaintenanceBusy(TimeoutError):
    """平台维护门禁等待超时，当前操作未进入。"""


class _FileLock:
    def __init__(self, path: Path):
        self.fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        self.locked = False

    def try_acquire(self, exclusive: bool) -> bool:
        if os.name == "nt":
            import ctypes
            import msvcrt
            from ctypes import wintypes

            class Overlapped(ctypes.Structure):
                _fields_ = [
                    ("Internal", ctypes.c_size_t),
                    ("InternalHigh", ctypes.c_size_t),
                    ("Offset", wintypes.DWORD),
                    ("OffsetHigh", wintypes.DWORD),
                    ("hEvent", wintypes.HANDLE),
                ]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            lock = kernel.LockFileEx
            lock.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped),
            ]
            lock.restype = wintypes.BOOL
            overlap = Overlapped()
            if not lock(msvcrt.get_osfhandle(self.fd), 1 | (2 if exclusive else 0),
                        0, 1, 0, ctypes.byref(overlap)):
                error = ctypes.get_last_error()
                if error == 33:  # ERROR_LOCK_VIOLATION
                    return False
                raise ctypes.WinError(error)
        else:
            import fcntl

            try:
                fcntl.flock(
                    self.fd,
                    (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB,
                )
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    return False
                raise
        self.locked = True
        return True

    def close(self) -> None:
        if self.fd >= 0:
            # Both flock and LockFileEx release this handle's lock on close.
            os.close(self.fd)
            self.fd = -1
            self.locked = False


@dataclass
class _Lease:
    root: str
    task: asyncio.Task
    exclusive: bool
    active: bool = True


_LEASES: contextvars.ContextVar[tuple[_Lease, ...]] = contextvars.ContextVar(
    "platform_maintenance_leases", default=(),
)


def maintenance_active() -> bool:
    """只有当前任务自己持有有效独占租约时返回真。"""
    try:
        task = asyncio.current_task()
    except RuntimeError:
        return False
    return any(lease.active and lease.exclusive and lease.task is task
               for lease in _LEASES.get())


class MaintenanceCoordinator:
    """同一工作目录的跨进程租约；显式 root 不受多用户开关影响。"""

    def __init__(self, root: str | Path | None = None, *,
                 timeout: float = 30.0, poll_interval: float = 0.05):
        self.root = Path(root) if root is not None else None
        self.timeout = timeout
        self.poll_interval = max(0.001, poll_interval)

    def _root(self) -> Path | None:
        if self.root is not None:
            return self.root
        from .. import constant
        from ..identity.runtime import is_multi_user_enabled

        return Path(constant.WORKING_DIR) if is_multi_user_enabled() else None

    async def _wait(self, lock: _FileLock, exclusive: bool, deadline: float) -> None:
        while not lock.try_acquire(exclusive):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MaintenanceBusy("platform_maintenance_busy")
            await asyncio.sleep(min(self.poll_interval, remaining))

    @asynccontextmanager
    async def _enter(self, exclusive: bool, timeout: float | None):
        root = self._root()
        if root is None:
            yield
            return
        key = os.path.normcase(str(root.resolve()))
        task = asyncio.current_task()
        assert task is not None
        leases = _LEASES.get()
        own = next((lease for lease in reversed(leases)
                    if lease.active and lease.root == key and lease.task is task), None)
        if own is not None:
            if exclusive and not own.exclusive:
                raise MaintenanceBusy("maintenance_lease_upgrade_denied")
            yield
            return

        # A child must hold its own data lock before its parent's lease ends.
        # It may bypass the closed gate only while that shared parent is active,
        # otherwise middleware/task-group children can deadlock a draining writer.
        shared_parent = any(lease.active and lease.root == key and not lease.exclusive
                            for lease in leases)
        lock_root = root / ".maintenance"
        lock_root.mkdir(parents=True, exist_ok=True)
        gate = _FileLock(lock_root / "gate.lock")
        data = None
        token = None
        lease = None
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        try:
            data = _FileLock(lock_root / "data.lock")
            if exclusive or not shared_parent:
                await self._wait(gate, exclusive, deadline)
            await self._wait(data, exclusive, deadline)
            if not exclusive:
                gate.close()
            lease = _Lease(key, task, exclusive)
            token = _LEASES.set((*leases, lease))
            yield
        finally:
            if lease is not None:
                lease.active = False
            try:
                if token is not None:
                    try:
                        _LEASES.reset(token)
                    except ValueError:
                        # Async-generator finalizers may run in a new Context.
                        # The origin retains only an inactive, unusable lease.
                        _LEASES.set(tuple(item for item in _LEASES.get() if item.active))
            finally:
                try:
                    if data is not None:
                        data.close()
                finally:
                    gate.close()

    def operation(self, *, timeout: float | None = None):
        """进入普通读写操作；多个进程可同时持有共享租约。"""
        return self._enter(False, timeout)

    def exclusive(self, *, timeout: float | None = None):
        """关闭新入口，排空在途操作后进入独占维护。"""
        return self._enter(True, timeout)


def operation(*, timeout: float | None = None):
    return MaintenanceCoordinator().operation(timeout=timeout)


def exclusive(*, timeout: float | None = None):
    return MaintenanceCoordinator().exclusive(timeout=timeout)
