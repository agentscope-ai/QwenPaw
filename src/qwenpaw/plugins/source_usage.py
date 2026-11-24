# -*- coding: utf-8 -*-
"""Cooperative source-use locks shared by host processes.

Readers exclude guarded source replacement until teardown has completed.
These locks do not restrict direct filesystem access by plugin code.
"""

from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from contextvars import ContextVar
import hashlib
import os
from uuid import uuid4

from .install_lock import (
    InstallLockError,
    _acquire_os_lock,
    async_lock,
    plugin_install_lock,
)
from .ownership import RuntimeSourceBusyError
from .activity import PluginBusyError
from .dependency_maintenance import canonical, state_root

_writers = ContextVar("plugin_source_writers", default=frozenset())


class SourceBusyError(PluginBusyError, RuntimeSourceBusyError):
    """A terminal reader or another process excludes source replacement."""

    def __init__(self, plugin_id):
        super().__init__(plugin_id, 0, can_interrupt=False)
        message = "Plugin source is in use by another operation; retry after it finishes"
        self.args = (message,)
        self.detail.update(
            message=message,
            source_busy=True,
            needs_restart=False,
        )


def _location(source):
    source = canonical(source)
    key = hashlib.sha256(os.path.normcase(str(source)).encode()).hexdigest()
    return state_root() / "sources" / key


@contextmanager
def source_reader(source):
    root = _location(source)
    with plugin_install_lock(root / "gate", timeout=0):
        lease = root / (uuid4().hex + ".reader")
        fd = os.open(lease, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if not _acquire_os_lock(fd):
                raise RuntimeSourceBusyError("PLUGIN_SOURCE_BUSY")
        except BaseException:
            os.close(fd)
            lease.unlink(missing_ok=True)
            raise
    try:
        yield
    finally:
        os.close(fd)
        try:
            lease.unlink(missing_ok=True)
        except PermissionError:
            pass  # A Windows reader scan can still have this file open.


@contextmanager
def _writer_at(root):
    with plugin_install_lock(root / "gate", timeout=0):
        for lease in root.glob("*.reader"):
            try:
                fd = os.open(lease, os.O_RDWR)
            except FileNotFoundError:
                continue
            try:
                if not _acquire_os_lock(fd):
                    raise RuntimeSourceBusyError("PLUGIN_SOURCE_BUSY")
            finally:
                os.close(fd)
            try:
                lease.unlink(missing_ok=True)
            except PermissionError:
                pass
        yield


@contextmanager
def source_writer(source):
    """Synchronously exclude source readers and other mutations."""
    with _writer_at(_location(source)):
        yield


@asynccontextmanager
async def _async_writer(source):
    import asyncio
    from ..utils.io_utils import run_sync_io

    root = await run_sync_io(_location, source)
    key = (str(root), asyncio.current_task())
    if key in _writers.get():
        yield
        return
    async with async_lock(_writer_at(root)):
        token = _writers.set(_writers.get() | {key})
        try:
            yield
        finally:
            _writers.reset(token)


@asynccontextmanager
async def source_writers(plugin_id, paths):
    """Exclude readers of all affected source directories for one transaction."""
    async with AsyncExitStack() as locks:
        try:
            for path in sorted(set(paths)):
                await locks.enter_async_context(_async_writer(path))
        except (RuntimeSourceBusyError, InstallLockError) as exc:
            raise SourceBusyError(plugin_id) from exc
        yield
