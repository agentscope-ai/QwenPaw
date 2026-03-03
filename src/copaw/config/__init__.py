# -*- coding: utf-8 -*-
from .config import (
    Config,
    ChannelConfig,
    ChannelConfigUnion,
    AgentsRunningConfig,
    HeartbeatConfig,
)
from .utils import (
    get_available_channels,
    get_config_path,
    get_heartbeat_config,
    get_heartbeat_query_path,
    get_playwright_chromium_executable_path,
    is_running_in_container,
    load_config,
    save_config,
    update_last_dispatch,
)

# ConfigWatcher is provided by __getattr__ (lazy-loaded).
# pylint: disable=undefined-all-variable
__all__ = [
    "AgentsRunningConfig",
    "Config",
    "ChannelConfig",
    "ChannelConfigUnion",
    "HeartbeatConfig",
    "ConfigWatcher",
    "get_available_channels",
    "get_config_path",
    "get_heartbeat_config",
    "get_heartbeat_query_path",
    "get_playwright_chromium_executable_path",
    "is_running_in_container",
    "load_config",
    "save_config",
    "update_last_dispatch",
]


def __getattr__(name: str):
    """Lazy-load ConfigWatcher to avoid pulling app.channels/lark_oapi."""
    if name == "ConfigWatcher":
        from .watcher import ConfigWatcher

        return ConfigWatcher
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
