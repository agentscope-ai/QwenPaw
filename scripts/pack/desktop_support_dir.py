# -*- coding: utf-8 -*-
"""Platform-specific app support dir for desktop builds (macOS .app / Windows exe)."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def desktop_support_dir() -> Path:
    """
    Default COPAW_WORKING_DIR for the packaged desktop app.
    macOS: ~/Library/Application Support/CoPaw
    Windows: %APPDATA%\\CoPaw
    Else: ~/.copaw
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return Path(base) / "CoPaw"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CoPaw"
    return Path.home() / ".copaw"
