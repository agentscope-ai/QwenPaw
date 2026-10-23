# -*- coding: utf-8 -*-
"""Stdlib-only shared-environment admission and process lifetime leases.

This module is also loaded by absolute path before importing qwenpaw or SDKs.
"""

from __future__ import annotations

import atexit
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import errno
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

_READERS = {}
_CAPABILITY_ENV = "QWENPAW_DEPENDENCY_MAINTENANCE"
capability_context = ContextVar(
    "dependency_maintenance_capability",
    default="",
)


def current_capability():
    return capability_context.get() or os.environ.get(_CAPABILITY_ENV, "")


def canonical(path):
    return Path(os.path.normcase(os.path.realpath(path)))


def marker(site):
    root = canonical(site)
    return root.parent / f".{root.name}.dependencies-maintenance"


def repair_marker(site):
    root = canonical(site)
    return root.parent / f".{root.name}.dependencies-repair-required"


def authorized(site):
    try:
        operation_id, token = current_capability().split(":", 1)
        value = json.loads(marker(site).read_text())
        return (
            value["id"] == operation_id
            and value["token_hash"]
            == hashlib.sha256(token.encode()).hexdigest()
        )
    except (ValueError, KeyError, OSError, TypeError):
        return False


def check_admission(site, *, check_repair=True):
    if marker(site).exists() and not authorized(site):
        raise RuntimeError(
            "DEPENDENCY_MAINTENANCE_REQUIRED: shared environment is under maintenance.",
        )
    if check_repair and repair_marker(site).exists() and not authorized(site):
        raise RuntimeError(
            "DEPENDENCY_REPAIR_REQUIRED: recover with the retained absolute dependency worker script.",
        )


def _try_lock(descriptor):
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in {
            errno.EACCES,
            errno.EAGAIN,
            getattr(errno, "EDEADLOCK", errno.EDEADLK),
        }:
            return False
        raise


def _open_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    if os.fstat(descriptor).st_size == 0:
        os.write(descriptor, b"\0")
    return descriptor


@contextmanager
def file_lock(path, timeout=0, *, reader_site=None):
    descriptor = _open_lock(Path(path))
    deadline = time.monotonic() + timeout
    try:
        while not _try_lock(descriptor):
            if reader_site is not None:
                check_admission(reader_site)
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "DEPENDENCY_ENVIRONMENT_BUSY: another operation owns the environment.",
                )
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        yield
    finally:
        os.close(descriptor)


def _gate(site):
    root = canonical(site)
    return root.parent / f".{root.name}.dependencies.lock"


def _readers_dir(site):
    root = canonical(site)
    return root.parent / f".{root.name}.dependencies-readers"


def lease_environment(sites, parent_pid=None, timeout=5):
    """Acquire before importing from sites; descriptors live until exit."""
    deadline = time.monotonic() + timeout
    for root in sorted({canonical(site) for site in sites}):
        if root in _READERS or not root.is_dir():
            continue
        # Read-only system origins cannot be maintained by this user. They
        # still reject an existing maintenance/repair marker, without writes.
        check_admission(root)
        if not os.access(root, os.W_OK) or not os.access(root.parent, os.W_OK):
            continue
        permitted = authorized(root)

        @contextmanager
        def admission():
            # An existing parent lease already excludes maintenance. This
            # also permits its inspection child while its writer gate is held.
            if permitted or (
                parent_pid
                and any(
                    row.get("pid") == parent_pid
                    for row in live_readers((root,))
                )
            ):
                yield
            else:
                with file_lock(
                    _gate(root),
                    timeout=max(0, deadline - time.monotonic()),
                    reader_site=root,
                ):
                    yield

        with admission():
            check_admission(root)
            path = _readers_dir(root) / (
                str(os.getpid()) + "-" + uuid4().hex + ".lease"
            )
            descriptor = _open_lock(path)
            try:
                if not _try_lock(descriptor):
                    raise RuntimeError("DEPENDENCY_LEASE_UNAVAILABLE")
                os.lseek(descriptor, 1, os.SEEK_SET)
                os.write(
                    descriptor,
                    json.dumps(
                        {"pid": os.getpid(), "site": str(root)},
                    ).encode(),
                )
                check_admission(root)
                _READERS[root] = (descriptor, path)
            except BaseException:
                os.close(descriptor)
                path.unlink(missing_ok=True)
                raise


def host_sites():
    """No distribution discovery or third-party imports at package entry."""
    return tuple(
        path
        for path in sys.path
        if path and Path(path).name in {"site-packages", "dist-packages"}
    )


def live_readers(sites, ignore_pid=None):
    readers = []
    for root in sites:
        directory = _readers_dir(root)
        for path in directory.glob("*.lease") if directory.is_dir() else ():
            try:
                descriptor = os.open(path, os.O_RDWR)
            except FileNotFoundError:
                continue
            try:
                stale = _try_lock(descriptor)
                if not stale:
                    try:
                        # Filename identity avoids reading a Windows-locked
                        # byte range; the OS lock supplies liveness evidence.
                        value = {
                            "pid": int(path.name.split("-", 1)[0]),
                            "site": str(root),
                        }
                    except (OSError, ValueError):
                        value = {"pid": None, "site": str(root)}
                    if value.get("pid") != ignore_pid:
                        readers.append(value)
            finally:
                os.close(descriptor)
            if stale:
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    # Another scanner may still hold the verified-stale file.
                    if getattr(exc, "winerror", None) not in {32, 33}:
                        raise
    return readers


@contextmanager
def maintenance(sites, operation_id, capability, *, ignore_pid=None):
    """Keep the admission barrier after writer locks are released."""
    sites = sorted({canonical(site) for site in sites})
    with ExitStack() as stack:
        for root in sites:
            stack.enter_context(file_lock(_gate(root)))
            check_admission(root)
        value = {
            "id": operation_id,
            "token_hash": hashlib.sha256(capability.encode()).hexdigest(),
        }
        created = []
        for root in sites:
            path = marker(root)
            if path.exists() and authorized(root):
                continue
            with path.open("x", encoding="utf-8") as stream:
                os.chmod(path, 0o600)
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            created.append(path)
        if live_readers(sites, ignore_pid):
            for path in created:
                path.unlink()
            raise RuntimeError(
                "DEPENDENCY_ENVIRONMENT_BUSY: another backend or child still uses the environment.",
            )
        yield


def clear_maintenance(sites, operation_id):
    for root in sites:
        path = marker(root)
        if (
            path.exists()
            and json.loads(path.read_text()).get("id") == operation_id
        ):
            path.unlink()


def _close_readers():
    for descriptor, path in _READERS.values():
        os.close(descriptor)
        path.unlink(missing_ok=True)
    _READERS.clear()


atexit.register(_close_readers)
