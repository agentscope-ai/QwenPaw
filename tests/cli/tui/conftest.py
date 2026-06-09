# -*- coding: utf-8 -*-
"""Test fixtures: keep paw's state (logs) out of the real state dir."""

from __future__ import annotations

import os
import tempfile

# Point the TUI's state dir at a unique temp location for the whole test
# session before any TUI module reads it. A unique per-session dir (vs a fixed
# path) avoids cross-run/cross-worker (xdist) pollution and leftover files.
if "PAW_STATE_DIR" not in os.environ:
    os.environ["PAW_STATE_DIR"] = tempfile.mkdtemp(prefix="paw-test-state-")
