# -*- coding: utf-8 -*-
"""Test fixtures: keep paw's state (logs) out of the real state dir."""

from __future__ import annotations

import os
import tempfile

# Point paw's state dir at a temp location for the whole test session before
# any paw module reads it.
os.environ.setdefault(
    "PAW_STATE_DIR", os.path.join(tempfile.gettempdir(), "paw-test-state")
)
