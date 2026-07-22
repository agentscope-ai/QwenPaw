# -*- coding: utf-8 -*-
"""Cross-platform atomic file writes for synchronous worker functions."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_text_atomic(path: Path, content: str) -> None:
    """Replace *path* atomically with UTF-8 *content*.

    The temporary file is created beside the destination so ``os.replace``
    remains on one filesystem on Windows, Linux, and macOS.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def write_json_atomic(path: Path, payload: Any) -> None:
    """Serialize *payload* and atomically replace one JSON file."""
    write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )


__all__ = ["write_json_atomic", "write_text_atomic"]
