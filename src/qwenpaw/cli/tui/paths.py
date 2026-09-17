# -*- coding: utf-8 -*-
"""Where paw keeps its own state (logs, etc.).

Self-owned so paw never depends on QwenPaw's working dir. Honors
``PAW_STATE_DIR`` and ``XDG_STATE_HOME``; falls back to a platform default.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def state_dir() -> Path:
    """Return paw's state directory, creating it if needed."""
    override = os.environ.get("PAW_STATE_DIR")
    if override:
        base = Path(override).expanduser()
    elif sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or "~"
        base = Path(root).expanduser() / "paw"
    elif sys.platform == "darwin":
        base = Path("~/Library/Application Support/paw").expanduser()
    else:
        root = os.environ.get("XDG_STATE_HOME") or "~/.local/state"
        base = Path(root).expanduser() / "paw"
    base.mkdir(parents=True, exist_ok=True)
    return base


def log_path(name: str = "acp.log") -> Path:
    """Path to a log file under the state dir."""
    return state_dir() / name
