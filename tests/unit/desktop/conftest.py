# -*- coding: utf-8 -*-
"""Make the in-repo Record & Replay plugin package importable."""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_DIR = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "bundle"
    / "record-and-replay"
)

if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))
