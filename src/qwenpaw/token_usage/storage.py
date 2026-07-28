# -*- coding: utf-8 -*-
"""File I/O for token usage data with atomic writes.
"""

import json
import logging
import os
from pathlib import Path

import aiofiles

logger = logging.getLogger(__name__)


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

    Returns ``True`` on success, ``False`` on failure.  The caller is
    responsible for deciding whether to retry on transient errors.
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
