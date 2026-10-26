# -*- coding: utf-8 -*-
"""Public plugin SDK and legacy compatibility exports.

The versioned author API is the explicit whitelist in
``compliance.PUBLIC_API``.
Exports such as PluginApi, PluginLoader and PluginRegistry remain for legacy
compatibility; their presence here does not make them supported SDK contracts.
"""

from .loader import PluginLoader
from .registry import PluginRegistry
from .api import PluginApi, get_tool_config
from .architecture import PluginManifest, PluginRecord
from .activity import PluginBusyError
from .errors import (
    SDKError,
    SDKAccessError,
    SDKCompatibilityError,
    SDKRestartRequiredError,
    StaleContextError,
    ResourceError,
    ToolInputError,
)
from .sdk import Plugin, PluginContext
from .sdk_version import SDK_VERSION, SDK_CAPABILITIES
from .lifecycle import (
    ConfigUpdateReport,
    PluginLifecycle,
    ReloadReport,
    UnloadMode,
)

__all__ = [
    "Plugin",
    "PluginContext",
    "SDK_VERSION",
    "SDK_CAPABILITIES",
    "SDKError",
    "SDKAccessError",
    "SDKCompatibilityError",
    "SDKRestartRequiredError",
    "StaleContextError",
    "ResourceError",
    "ToolInputError",
    "PluginBusyError",
    "PluginLoader",
    "PluginRegistry",
    "PluginApi",
    "PluginManifest",
    "PluginRecord",
    "PluginLifecycle",
    "ConfigUpdateReport",
    "ReloadReport",
    "UnloadMode",
    "get_tool_config",
]
