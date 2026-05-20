# -*- coding: utf-8 -*-
"""Pytest harness for the DataPaw plugin tests.

Adds the plugin directory and the host source root to sys.path so
test files can import plugin modules (``from agents_setup import ...``)
and host modules (``from qwenpaw.config import ...``) without an
editable install.
"""
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
HOST_SRC = PLUGIN_DIR.parent.parent.parent / "src"

for p in (str(PLUGIN_DIR), str(HOST_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)
