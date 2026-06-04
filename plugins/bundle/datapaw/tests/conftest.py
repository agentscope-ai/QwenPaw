# -*- coding: utf-8 -*-
"""Pytest harness for the DataPaw plugin tests.

Registers the plugin directory as package ``plugin_datapaw`` in
sys.modules so relative imports resolve correctly, mirroring what
PluginLoader does at runtime.
"""
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
HOST_SRC = PLUGIN_DIR.parent.parent.parent / "src"

# Host source on sys.path (for qwenpaw.* imports)
if str(HOST_SRC) not in sys.path:
    sys.path.insert(0, str(HOST_SRC))

# Register plugin directory as package "plugin_datapaw" so relative
# imports inside plugin modules resolve correctly.
_PKG = "plugin_datapaw"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(PLUGIN_DIR)]
    pkg.__package__ = _PKG
    sys.modules[_PKG] = pkg
