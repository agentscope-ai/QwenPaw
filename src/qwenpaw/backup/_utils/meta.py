# -*- coding: utf-8 -*-
"""Backup metadata helpers: system info collection and zip meta reading."""
from __future__ import annotations

import platform
import re
import zipfile
from datetime import datetime, timezone
from uuid import uuid4

from .constants import META_FILE


def get_qwenpaw_version() -> str:
    """Return the installed QwenPaw package version, or ``'unknown'``."""
    try:
        from qwenpaw.__version__ import __version__

        return __version__
    except Exception:
        return "unknown"


def generate_backup_id() -> str:
    """Return a human-readable, filesystem-safe backup ID.

    Format: ``qwenpaw-{version}-{YYYYMMDDTHHmmssZ}-{short8}``

    Example: ``qwenpaw-1.2.3-20260420T093000Z-ab12cd34``
    """
    ver = re.sub(r"[^a-zA-Z0-9._-]", "_", get_qwenpaw_version())
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = uuid4().hex[:8]
    return f"qwenpaw-{ver}-{ts}-{short}"


def get_system_info() -> dict:
    """Return a snapshot of OS and Python runtime information."""
    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
    }


def finalize_backup_meta(meta, agent_count: int) -> None:
    """Populate *meta* with agent count, version, and system info in-place."""
    meta.agent_count = agent_count
    meta.qwenpaw_version = get_qwenpaw_version()
    meta.system_info = get_system_info()


def read_meta_from_zip(zf: zipfile.ZipFile) -> str | None:
    """Read meta.json from zip root. Returns raw JSON string or None."""
    if META_FILE in zf.namelist():
        return zf.read(META_FILE).decode("utf-8")
    return None
