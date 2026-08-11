# -*- coding: utf-8 -*-
"""File I/O for token usage data with atomic writes.
"""

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import aiofiles

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None

logger = logging.getLogger(__name__)


@contextmanager
def _file_write_lock(path: Path) -> Iterator[None]:
    """Serialize writes across processes (fcntl / msvcrt)."""
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


async def load_data(path: Path) -> dict:
    """Load token usage data from *path*."""
    if not path.exists():
        return {}

    try:
        async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
            raw = await f.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "token_usage: failed to read %s: %s — starting with empty data",
            path,
            exc,
        )
        return {}

    return data


def save_data_sync(path: Path, data: dict) -> bool:
    """Persist *data* to *path* using an atomic write (tmp → replace).

    This is intentionally synchronous so it can be called from the buffer
    flush task without blocking the event loop via ``asyncio.to_thread``.

    Returns:
        ``True`` on success, ``False`` when the atomic write fails.
    """
    tmp_path = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        with open(tmp_path, mode="w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, path)
        return True
    except OSError as exc:
        logger.warning(
            "token_usage: failed to write %s: %s",
            path,
            exc,
        )
        # Clean up orphaned tmp file if it was created.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        return False


__all__ = [
    "load_data",
    "save_data_sync",
]
