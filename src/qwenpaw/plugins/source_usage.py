# -*- coding: utf-8 -*-
"""Cooperative source-use locks shared by host processes.

Readers exclude guarded source replacement until teardown has completed.
These locks do not restrict direct filesystem access by plugin code.
"""

# TODO: Move Loader operation selection out of this lock module, then integrate
# process-shared source leases with RuntimeOwners. Preserve source exclusion
# until invocations and teardown finish; locks alone do not model service
# dependencies or enforce filesystem isolation.

from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
import inspect
import os
from pathlib import Path
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


def mutates_source(method):
    """Guard source transactions before teardown or persistent changes."""
    signature = inspect.signature(method)

    @wraps(method)
    async def guarded(self, *args, **kwargs):
        from ..utils.io_utils import run_sync_io

        params = signature.bind(self, *args, **kwargs).arguments
        if method.__name__ == "unload_plugin_with_mode":
            from .lifecycle import UnloadMode

            if params["mode"] is not UnloadMode.UNINSTALL and not params.get(
                "delete_files",
            ):
                return await method(self, *args, **kwargs)
        plugin_id = params.get("plugin_id")
        if plugin_id is None:
            _, manifest = await run_sync_io(
                self._read_source_manifest,
                Path(params["source_path"]),
            )
            plugin_id = manifest.id
        record = self.get_loaded_plugin(plugin_id)
        installed = (
            record.source_path
            if record is not None
            else await run_sync_io(self.find_installed_plugin_dir, plugin_id)
        )
        destination = params.get("install_dir") or (
            self.plugin_dirs[0] if self.plugin_dirs else None
        )
        target = (
            Path(destination) / plugin_id
            if destination is not None
            else installed
        )
        if target is None:
            return await method(self, *args, **kwargs)
        async with AsyncExitStack() as stack:
            try:
                roots = {Path(installed or target), target}
                for root in sorted(roots):
                    await stack.enter_async_context(_async_writer(root))
            except (RuntimeSourceBusyError, InstallLockError) as exc:
                raise SourceBusyError(plugin_id) from exc
            return await method(self, *args, **kwargs)

    return guarded
