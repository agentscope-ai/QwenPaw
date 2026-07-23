# -*- coding: utf-8 -*-
"""Async and atomic filesystem utilities.

Choose an API by the required filesystem semantics:

* Use :func:`read_text_async` or :func:`read_bytes_async` for standalone
  reads.
* Use :func:`append_text_async` when content must remain in the same file
  and replacing the whole file would be incorrect.
* Use the ``write_*_atomic_async`` functions when replacing durable state,
  configuration, JSON, or YAML. Readers observe either the old complete
  file or the new complete file.
* Hold :func:`get_path_lock` across a complete read-modify-write sequence,
  then use an atomic writer for the replacement.
* Use :func:`run_sync_io` only to adapt an already-composed legacy
  filesystem, subprocess, or network workflow when no semantic helper fits.

Async application code should not call ``asyncio.to_thread`` directly for
file I/O. The public async functions in this module own thread offloading.
Path locks are process-local; cross-process transactions still require an
OS-level file lock.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import tempfile
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

import yaml

_P = ParamSpec("_P")
_R = TypeVar("_R")

_PATH_LOCKS: weakref.WeakValueDictionary[
    str,
    asyncio.Lock,
] = weakref.WeakValueDictionary()


def get_path_lock(path: Path | str) -> asyncio.Lock:
    """Return the process-local lock for one normalized filesystem path.

    Use this around the complete transaction, not around individual reads
    and writes. For example, an editor must hold one lock while it reads,
    modifies, and atomically replaces the file.
    """
    key = os.path.normcase(str(Path(path).resolve(strict=False)))
    lock = _PATH_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _PATH_LOCKS[key] = lock
    return lock


async def run_sync_io(
    operation: Callable[_P, _R],
    /,
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> _R:
    """Run one composed synchronous I/O operation in a worker thread.

    Prefer a semantic helper from this module. This escape hatch is for
    legacy operations that already combine multiple blocking steps, such
    as a subprocess download followed by file validation. It provides no
    locking or atomicity by itself.
    """
    return await asyncio.to_thread(operation, *args, **kwargs)


def _read_text(
    path: Path | str,
    encoding: str,
    errors: str | None,
) -> str:
    return Path(path).read_text(encoding=encoding, errors=errors)


async def read_text_async(
    path: Path | str,
    *,
    encoding: str = "utf-8",
    errors: str | None = None,
) -> str:
    """Read text without blocking the event loop.

    Use this for a standalone read or while the caller holds a path/domain
    lock. Do not build a read-modify-write transaction from separately
    locked calls.
    """
    return await run_sync_io(_read_text, path, encoding, errors)


async def read_bytes_async(path: Path | str) -> bytes:
    """Read bytes without blocking the event loop."""
    return await run_sync_io(Path(path).read_bytes)


async def path_exists_async(path: Path | str) -> bool:
    """Check whether a path exists without blocking the event loop."""
    return await run_sync_io(Path(path).exists)


def _append_text(
    path: Path | str,
    content: str,
    encoding: str,
) -> None:
    with open(path, "a", encoding=encoding) as handle:
        handle.write(content)


async def append_text_async(
    path: Path | str,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Serialize and offload one in-process append operation.

    Choose this instead of atomic replacement when existing content must
    remain in place. The process-local path lock prevents coroutine-level
    interleaving. It does not make a multi-process append transaction.
    """
    async with get_path_lock(path):
        await run_sync_io(_append_text, path, content, encoding)


def _write_bytes(path: Path | str, content: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(content)


async def write_bytes_async(
    path: Path | str,
    content: bytes,
) -> None:
    """Serialize and offload a non-atomic byte-file write.

    Use this for generated or downloaded artifacts whose path is published
    only after this coroutine returns. Durable shared state should use an
    atomic replacement API instead.
    """
    async with get_path_lock(path):
        await run_sync_io(_write_bytes, path, content)


async def make_dirs_async(path: Path | str) -> None:
    """Create a directory tree without blocking the event loop."""
    await run_sync_io(Path(path).mkdir, parents=True, exist_ok=True)


async def unlink_async(
    path: Path | str,
    *,
    missing_ok: bool = True,
) -> None:
    """Unlink one path without blocking the event loop."""
    await run_sync_io(Path(path).unlink, missing_ok=missing_ok)


def _resolve_write_target(path: Path) -> Path:
    """Return the real target so replacing a file preserves symlinks."""
    if path.is_symlink():
        return path.resolve(strict=False)
    return path


def read_json(path: Path | str) -> Any:
    """Synchronously read one complete UTF-8 JSON document.

    Synchronous worker functions may use this directly. Async application
    code should use :func:`read_json_async`.
    """
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_text_atomic(
    path: Path | str,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Synchronously replace a file with complete text content.

    The temporary file is created beside the destination so ``os.replace``
    stays on one filesystem on Windows, Linux, and macOS. Existing file
    modes and symlinks are preserved. Async application code should use
    :func:`write_text_atomic_async`.
    """
    target = _resolve_write_target(Path(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    original_mode = (
        stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    )
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
            encoding=encoding,
            newline="\n",
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, target)
        temp_path = None
        if original_mode is not None:
            target.chmod(original_mode)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def write_json_atomic(
    path: Path | str,
    payload: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = False,
) -> None:
    """Synchronously serialize and atomically replace one JSON file.

    Synchronous worker functions may use this directly. Async application
    code should use :func:`write_json_atomic_async`.
    """
    write_text_atomic(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=indent,
            sort_keys=sort_keys,
        ),
    )


def write_yaml_atomic(
    path: Path | str,
    payload: Any,
    *,
    default_flow_style: bool = False,
    allow_unicode: bool = True,
    sort_keys: bool = False,
    extra_content: str = "",
) -> None:
    """Synchronously serialize and atomically replace one YAML file.

    Synchronous worker functions may use this directly. Async application
    code should use :func:`write_yaml_atomic_async`.
    """
    content = yaml.dump(
        payload,
        default_flow_style=default_flow_style,
        allow_unicode=allow_unicode,
        sort_keys=sort_keys,
    )
    if extra_content:
        content = f"{content}{extra_content}"
    write_text_atomic(path, content)


async def read_json_async(path: Path | str) -> Any:
    """Read a complete JSON document without blocking the event loop.

    Atomic writers make standalone reads safe from partial-file visibility.
    A caller performing read-modify-write must still hold its domain or path
    lock across both this read and the following atomic write.
    """
    return await run_sync_io(read_json, path)


async def write_text_atomic_async(
    path: Path | str,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Atomically replace text without blocking the event loop.

    Choose this for overwrite semantics. Callers should not add another
    ``to_thread`` layer.
    """
    await run_sync_io(
        write_text_atomic,
        path,
        content,
        encoding=encoding,
    )


async def write_json_atomic_async(
    path: Path | str,
    payload: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = False,
) -> None:
    """Serialize and atomically replace JSON off the event loop.

    Choose this for durable JSON state and configuration files.
    """
    await run_sync_io(
        write_json_atomic,
        path,
        payload,
        indent=indent,
        sort_keys=sort_keys,
    )


async def write_yaml_atomic_async(
    path: Path | str,
    payload: Any,
    *,
    default_flow_style: bool = False,
    allow_unicode: bool = True,
    sort_keys: bool = False,
    extra_content: str = "",
) -> None:
    """Serialize and atomically replace YAML off the event loop.

    Choose this for durable YAML state and configuration files.
    """
    await run_sync_io(
        write_yaml_atomic,
        path,
        payload,
        default_flow_style=default_flow_style,
        allow_unicode=allow_unicode,
        sort_keys=sort_keys,
        extra_content=extra_content,
    )


__all__ = [
    "append_text_async",
    "get_path_lock",
    "make_dirs_async",
    "path_exists_async",
    "read_bytes_async",
    "read_json",
    "read_json_async",
    "read_text_async",
    "run_sync_io",
    "unlink_async",
    "write_bytes_async",
    "write_json_atomic",
    "write_json_atomic_async",
    "write_text_atomic",
    "write_text_atomic_async",
    "write_yaml_atomic",
    "write_yaml_atomic_async",
]
