# -*- coding: utf-8 -*-
"""Shared fixtures for plugin unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

_PLUGINS_BUNDLE_DIR = Path(__file__).parents[3] / "plugins" / "bundle"

# Make bundled plugins importable by their directory name at import time.
_bundle_dir = str(_PLUGINS_BUNDLE_DIR)
if _bundle_dir not in sys.path:
    sys.path.insert(0, _bundle_dir)
