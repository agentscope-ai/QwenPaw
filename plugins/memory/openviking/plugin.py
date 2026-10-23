# -*- coding: utf-8 -*-
"""OpenViking memory plugin entry point."""

try:
    # The plugin loader executes this file from the plugin root.
    from backend import OpenVikingMemoryConfig, OpenVikingMemoryManager
except ModuleNotFoundError:  # pragma: no cover - package-import test path
    from .backend import OpenVikingMemoryConfig, OpenVikingMemoryManager
from qwenpaw.plugins.api import PluginApi


class OpenVikingMemoryPlugin:
    """Register the OpenViking backend and its governance metadata."""

    def register(self, api: PluginApi) -> None:
        api.register_memory_backend(
            backend_id="openviking",
            factory=OpenVikingMemoryManager,
            label="OpenViking",
            config_schema=OpenVikingMemoryConfig,
            metadata={
                "description": "OpenViking long-term memory",
                "network_access": True,
                "secret_fields": ["api_key"],
                "tools": {
                    "memory_search": {
                        "policy_name": "OpenVikingMemorySearch",
                        "tool_type": "network",
                        "target_param": "query",
                    },
                },
            },
        )


plugin = OpenVikingMemoryPlugin()
