# -*- coding: utf-8 -*-
"""Cross-platform atomic file writes for synchronous worker functions."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import tempfile
import weakref
from pathlib import Path
from typing import Any

import yaml


_PATH_LOCKS: weakref.WeakValueDictionary[
    str,
    asyncio.Lock,
] = weakref.WeakValueDictionary()


def get_path_lock(path: Path | str) -> asyncio.Lock:
    """Return one in-process async lock for a resolved path."""
    key = os.path.normcase(str(Path(path).resolve(strict=False)))
    lock = _PATH_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _PATH_LOCKS[key] = lock
    return lock


def _resolve_write_target(path: Path) -> Path:
    """Return the real target so replacing a file preserves symlinks."""
    if path.is_symlink():
        return path.resolve(strict=False)
    return path


def read_json(path: Path | str) -> Any:
    """Read and deserialize one complete UTF-8 JSON document."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_text_atomic(
    path: Path | str,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Replace *path* atomically with UTF-8 *content*.

    The temporary file is created beside the destination so ``os.replace``
    remains on one filesystem on Windows, Linux, and macOS. Existing file
    modes and symlinks are preserved.
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
    """Serialize *payload* and atomically replace one JSON file."""
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
    """Serialize YAML and atomically replace one file."""
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
    """Read JSON in a worker thread without blocking the event loop."""
    return await asyncio.to_thread(read_json, path)


async def write_text_atomic_async(
    path: Path | str,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Atomically write text in a worker thread."""
    await asyncio.to_thread(
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
    """Serialize and atomically write JSON in a worker thread."""
    await asyncio.to_thread(
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
    """Serialize and atomically write YAML in a worker thread."""
    await asyncio.to_thread(
        write_yaml_atomic,
        path,
        payload,
        default_flow_style=default_flow_style,
        allow_unicode=allow_unicode,
        sort_keys=sort_keys,
        extra_content=extra_content,
    )


__all__ = [
    "get_path_lock",
    "read_json",
    "read_json_async",
    "write_json_atomic",
    "write_json_atomic_async",
    "write_text_atomic",
    "write_text_atomic_async",
    "write_yaml_atomic",
    "write_yaml_atomic_async",
]
