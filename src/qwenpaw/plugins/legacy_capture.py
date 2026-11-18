# -*- coding: utf-8 -*-
"""Small filesystem primitives shared by official legacy-state readers."""

import hashlib
import json
import os
from pathlib import Path

from .install_lock import plugin_install_lock


def read_json_snapshot(path):
    """Return original JSON, provenance and physical identity without writes."""
    path = Path(path)
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("LEGACY_STATE_INVALID")
    with path.open("rb") as stream:
        info = os.fstat(stream.fileno())
        content = stream.read()
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("LEGACY_STATE_INVALID")
    return (
        data,
        {
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        (info.st_dev, info.st_ino),
    )


def capture_once(path, *, load, build):
    """Serialize first capture; domain readers validate both old and new data."""
    from ..utils.io_utils import write_json_atomic

    with plugin_install_lock(path.with_suffix(".lock")):
        existing = load()
        if existing is not None:
            return existing
        result = build()
        write_json_atomic(path, result)
        return result
