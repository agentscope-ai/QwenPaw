# -*- coding: utf-8 -*-
"""QwenPaw Plugin System."""

from .loader import PluginLoader, ENTRY_POINT_GROUP
from .registry import PluginRegistry
from .api import PluginApi, get_tool_config
from .architecture import InstallSource, PluginManifest, PluginRecord

__all__ = [
    "ENTRY_POINT_GROUP",
    "InstallSource",
    "PluginLoader",
    "PluginRegistry",
    "PluginApi",
    "PluginManifest",
    "PluginRecord",
    "get_tool_config",
]
