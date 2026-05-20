# -*- coding: utf-8 -*-
"""DataPaw plugin shared constants and sys.path injection.

Importing this module has a side effect: it inserts the plugin
directory into sys.path so that submodules like ``datapaw.agents``
can be imported with absolute paths from inside the plugin.
"""
from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ID = "datapaw"
BUILTIN_DATAPAW_AGENT_ID = "datapaw"
PLUGIN_DIR = Path(__file__).resolve().parent

_plugin_dir_str = str(PLUGIN_DIR)
if _plugin_dir_str not in sys.path:
    sys.path.insert(0, _plugin_dir_str)
