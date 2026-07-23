# -*- coding: utf-8 -*-
"""Make the bundled ``computer_use_tool`` package importable for tests."""

from __future__ import annotations

import os
import sys

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)
