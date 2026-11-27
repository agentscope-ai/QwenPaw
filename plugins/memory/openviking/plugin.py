# -*- coding: utf-8 -*-
"""OpenViking memory plugin entry point."""

from qwenpaw.plugins.api import PluginApi

from .backend import OpenVikingMemoryConfig, OpenVikingMemoryManager


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
