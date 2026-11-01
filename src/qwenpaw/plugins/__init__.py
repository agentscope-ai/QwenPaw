# -*- coding: utf-8 -*-
# pylint: disable=undefined-all-variable
"""Public SDK and legacy exports, resolved lazily for execution workers.

The supported versioned author API is the whitelist in ``compliance.PUBLIC_API``.
Legacy exports such as PluginApi and PluginLoader remain compatibility APIs.
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Describe lazy exports for static analyzers without loading host modules.
    from .api import get_tool_config
    from .sdk import PluginContext

_EXPORTS = {
    "Plugin": "sdk",
    "PluginContext": "sdk",
    "SDK_VERSION": "sdk_version",
    "SDK_CAPABILITIES": "sdk_version",
    "SDKError": "errors",
    "SDKAccessError": "errors",
    "SDKCompatibilityError": "errors",
    "SDKRestartRequiredError": "errors",
    "StaleContextError": "errors",
    "ResourceError": "errors",
    "ToolInputError": "errors",
    "PluginBusyError": "activity",
    "PluginLoader": "loader",
    "PluginRegistry": "registry",
    "PluginApi": "api",
    "get_tool_config": "api",
    "PluginManifest": "architecture",
    "PluginRecord": "architecture",
    "PluginLifecycle": "lifecycle",
    "ConfigUpdateReport": "lifecycle",
    "ReloadReport": "lifecycle",
    "UnloadMode": "lifecycle",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
