# -*- coding: utf-8 -*-
"""QwenPaw Plugin System."""

from .loader import PluginLoader
from .registry import PluginRegistry
from .api import PluginApi
from .architecture import PluginManifest, PluginRecord

__all__ = [
    "PluginLoader",
    "PluginRegistry",
    "PluginApi",
    "PluginManifest",
    "PluginRecord",
]
