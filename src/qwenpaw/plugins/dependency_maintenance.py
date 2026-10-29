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
import threading
from uuid import uuid4

_READERS = {}
_READERS_LOCK = threading.Lock()
_STATE_ENV = "QWENPAW_DEPENDENCY_STATE_DIR"
_STATE_ROOT = None
_CAPABILITY_ENV = "QWENPAW_DEPENDENCY_MAINTENANCE"
capability_context = ContextVar(
    "dependency_maintenance_capability",
    default="",
)


def current_capability():
    return capability_context.get() or os.environ.get(_CAPABILITY_ENV, "")


def _enumerated_path(path):
    """Recover filesystem spelling, without creating or caching directories.

    Missing suffixes are candidates only. Existing components must be readable
    and remain the same objects throughout resolution; inode evidence is never
    retained as the coordination key.
    """
    resolved = Path(os.path.realpath(path))
    current = Path(os.path.normcase(resolved.anchor))
    observed = [(current, current.stat())]
    for index, part in enumerate(resolved.parts[1:], 1):
        candidate = current / part
        try:
            expected = candidate.stat()
        except FileNotFoundError:
            # A dangling link is not an absent, unambiguous suffix.
            if candidate.is_symlink():
                raise
            current = current.joinpath(*resolved.parts[index:])
            break
        with os.scandir(current) as entries:
            match = next(
                (entry for entry in entries if entry.name == part),
                None,
            )
        if match is None:
            with os.scandir(current) as entries:
                match = next(
                    (
                        entry
                        for entry in entries
                        if os.path.samestat(
                            expected,
                            os.stat(entry.path, follow_symlinks=False),
                        )
                    ),
                    None,
                )
        elif not os.path.samestat(
            expected,
            os.stat(match.path, follow_symlinks=False),
        ):
            raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
        if match is None or match.is_symlink():
            raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
        current = current / match.name
        observed.append((current, expected))
    if os.path.realpath(path) != str(resolved) or any(
        not os.path.samestat(before, component.stat())
        for component, before in observed
    ):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
    return current


def _existing_path(path):
    """Query kernel spelling without requiring directory enumeration."""
    if sys.platform == "darwin":
        import fcntl

        flags = getattr(os, "O_EVTONLY", 0x8000)
    elif sys.platform.startswith("linux") and hasattr(os, "O_PATH"):
        flags = os.O_PATH
    else:
        return _enumerated_path(path)
    expected = path.stat()
    descriptor = os.open(path, flags | getattr(os, "O_CLOEXEC", 0))
    try:
        if sys.platform == "darwin":
            value = fcntl.fcntl(
                descriptor,
                getattr(fcntl, "F_GETPATH", 50),
                bytes(1024),
            ).split(b"\0", 1)[0]
            actual = Path(os.fsdecode(value))
        else:
            try:
                actual = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
            except OSError as exc:
                if exc.errno not in {errno.ENOENT, errno.ENOTDIR}:
                    raise
                # No procfs: the old resolver must establish the same spelling
                # or fail closed (including on search-only ancestors).
                actual = _enumerated_path(path)
        held = os.fstat(descriptor)
        if (
            held.st_nlink == 0
            or not actual.is_absolute()
            or any(
                not os.path.samestat(held, value)
                for value in (expected, path.stat(), actual.stat())
            )
        ):
            raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
        return actual
    finally:
        os.close(descriptor)


def canonical(path):
    """Resolve existing identity; append only genuinely absent suffixes."""
    ancestor = Path(path)
    if not ancestor.is_absolute():
        ancestor = Path.cwd() / ancestor
    original = str(ancestor)
    missing = []
    while True:
        try:
            resolved = Path(os.path.realpath(ancestor, strict=True))
            break
        except FileNotFoundError:
            # lstat distinguishes a missing name from a dangling symlink.
            try:
                ancestor.lstat()
            except FileNotFoundError:
                missing.append(ancestor.name)
                ancestor = ancestor.parent
            else:
                raise
    current = _existing_path(resolved)
    if not os.path.samestat(ancestor.stat(), current.stat()):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
    suffix = tuple(reversed(missing))
    result = current.joinpath(*suffix)
    if os.path.realpath(ancestor, strict=True) != str(resolved):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
    # A candidate becoming real during resolution needs a new observation.
    for index in range(len(missing)):
        candidate = current.joinpath(*suffix[: index + 1])
        try:
            candidate.lstat()
        except FileNotFoundError:
            continue
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
    if os.path.realpath(original) != str(
        resolved.joinpath(*reversed(missing)),
    ):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
    return result


def contains_environment_path(root, path):
    """Containment using actual spelling, even on case-sensitive Windows dirs."""
    parent = canonical(root).parts
    return canonical(path).parts[: len(parent)] == parent


def state_root():
    """Select once at trusted startup, before user configuration or leases."""
    global _STATE_ROOT
    if _STATE_ROOT is None:
        override = os.environ.get(_STATE_ENV)
        if override:
            if not Path(override).is_absolute():
                raise RuntimeError(
                    "DEPENDENCY_STATE_ROOT_UNAVAILABLE: "
                    "QWENPAW_DEPENDENCY_STATE_DIR must be absolute.",
                )
            root = canonical(override)
        else:
            if os.name == "nt":
                home = Path(os.environ["USERPROFILE"])
            else:
                import pwd

                try:
                    value = getattr(pwd.getpwuid(os.getuid()), "pw_dir", None)
                except KeyError:
                    value = None
                if not value or not Path(value).is_absolute():
                    value = os.environ.get("HOME")
                if not value or not Path(value).is_absolute():
                    raise RuntimeError(
                        "DEPENDENCY_STATE_ROOT_UNAVAILABLE: provide a stable "
                        "absolute startup HOME or an absolute shared "
                        "QWENPAW_DEPENDENCY_STATE_DIR.",
                    )
                home = Path(value)
            root = canonical(home / ".qwenpaw" / "dependency-environments")
        _STATE_ROOT = root
        os.environ[_STATE_ENV] = str(root)
    return _STATE_ROOT


def _sidecar(site, suffix):
    root = canonical(site)
    identity = hashlib.sha256(os.fsencode(root)).hexdigest()
    return state_root() / identity / f".{root.name}.dependencies{suffix}"


def marker(site):
    return _sidecar(site, "-maintenance")


def repair_marker(site):
    return _sidecar(site, "-repair-required")


def _authorized(path):
    try:
        operation_id, token = current_capability().split(":", 1)
        value = json.loads(path.read_text())
        return (
            value["id"] == operation_id
            and value["token_hash"]
            == hashlib.sha256(token.encode()).hexdigest()
        )
    except (ValueError, KeyError, OSError, TypeError):
        return False


def authorized(site):
    return _authorized(marker(site))


def _check_admission(maintenance_path, repair_path, check_repair):
    permitted = _authorized(maintenance_path)
    if maintenance_path.exists() and not permitted:
        raise RuntimeError(
            "DEPENDENCY_MAINTENANCE_REQUIRED: shared environment is under maintenance.",
        )
    if check_repair and repair_path.exists() and not permitted:
        raise RuntimeError(
            "DEPENDENCY_REPAIR_REQUIRED: recover with the retained absolute dependency worker script.",
        )


def check_admission(site, *, check_repair=True):
    _check_admission(marker(site), repair_marker(site), check_repair)


def check_lock_admission(path, *, check_repair=True):
    """Check installation barriers without reversing the hashed identity."""
    stem = str(path)[: -len(".lock")]
    _check_admission(
        Path(stem + "-maintenance"),
        Path(stem + "-repair-required"),
        check_repair,
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
    return os.open(path, os.O_CREAT | os.O_RDWR, 0o600)


@contextmanager
def file_lock(path, timeout=0, *, reader_site=None):
    descriptor = _open_lock(Path(path))
    deadline = time.monotonic() + timeout
    try:
        while not _try_lock(descriptor):
            if reader_site is not None:
                check_admission(reader_site, check_repair=False)
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "DEPENDENCY_ENVIRONMENT_BUSY: another operation owns the environment.",
                )
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        yield
    finally:
        os.close(descriptor)


def _gate(site):
    return _sidecar(site, ".lock")


def _admission_gate(site):
    # Observations hold the writer gate for their entire scan. Only actual
    # publication or maintenance admission must exclude new readers.
    return _sidecar(site, ".admission.lock")


def _readers_dir(site):
    return _sidecar(site, "-readers")


def lease_environment(sites, parent_pid=None, timeout=5):
    """Serialize process-owned reader publication, including worker callers."""
    with _READERS_LOCK:
        _lease_environment(sites, parent_pid, timeout)


def _lease_environment(sites, parent_pid=None, timeout=5):
    """Acquire before importing from sites; descriptors live until exit."""
    deadline = time.monotonic() + timeout
    for identity in sorted({str(canonical(site)) for site in sites}):
        root = Path(identity)
        if identity in _READERS or not root.is_dir():
            continue
        # A live additive writer also holds a temporary repair marker. Classify
        # it only under the gate; maintenance still blocks new readers now.
        check_admission(root, check_repair=False)
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
                    _admission_gate(root),
                    timeout=max(0, deadline - time.monotonic()),
                    reader_site=root,
                ):
                    yield

        with admission():
            if identity in _READERS:
                continue
            check_admission(root)
            _READERS[identity] = _publish_reader(root)


def _publish_reader(root):
    """Publish one OS-owned reader; caller holds gate or parent custody."""
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
            json.dumps({"pid": os.getpid(), "site": str(root)}).encode(),
        )
        check_admission(root)
        return descriptor, path
    except BaseException:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise


@contextmanager
def observation_readers(sites):
    """Temporary parent proof for inspection children, under caller's gates.

    Separate lease files give overlapping scopes independent custody without
    altering or releasing the process lifetime reader table.
    """
    readers = []
    try:
        for site in sites:
            readers.append(_publish_reader(Path(site)))
        yield
    finally:
        # Release every live lease before attempting pathname cleanup. A
        # Windows scanner can still have a stale lease file open for reading.
        with ExitStack() as cleanup:
            for descriptor, _path in readers:
                cleanup.callback(os.close, descriptor)
        with ExitStack() as cleanup:
            for _descriptor, path in readers:
                cleanup.callback(_unlink_observation_reader, path)


def _unlink_observation_reader(path):
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) not in {32, 33}:
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
    sites = [
        Path(key) for key in sorted({str(canonical(site)) for site in sites})
    ]
    with ExitStack() as stack:
        for root in sites:
            if not root.is_dir():
                raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
            stack.enter_context(file_lock(_gate(root)))
            if str(canonical(root)) != str(root) or not root.is_dir():
                raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
            check_admission(root)
        with maintenance_barrier(
            sites,
            operation_id,
            capability,
            ignore_pid=ignore_pid,
        ):
            yield


@contextmanager
def maintenance_barrier(sites, operation_id, capability, *, ignore_pid=None):
    """Create maintenance markers; caller must hold every site's gate."""
    value = {
        "id": operation_id,
        "token_hash": hashlib.sha256(capability.encode()).hexdigest(),
    }
    created = []
    with ExitStack() as admission:
        for root in sorted(sites, key=str):
            admission.enter_context(file_lock(_admission_gate(root)))
        try:
            for root in sites:
                path = marker(root)
                if path.exists() and authorized(root):
                    continue
                with path.open("x", encoding="utf-8") as stream:
                    created.append(path)
                    os.chmod(path, 0o600)
                    json.dump(value, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
            if live_readers(sites, ignore_pid):
                raise RuntimeError(
                    "DEPENDENCY_ENVIRONMENT_BUSY: another backend or child still uses the environment.",
                )
        except BaseException:
            # No mutation has started; all gates still exclude other writers.
            for path in created:
                path.unlink(missing_ok=True)
            raise
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
