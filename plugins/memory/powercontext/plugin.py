# -*- coding: utf-8 -*-
"""PowerContext memory plugin entry point."""

from backend import PowerContextMemoryConfig, PowerContextMemoryManager
from qwenpaw.plugins.api import PluginApi


class PowerContextMemoryPlugin:
    def register(self, api: PluginApi) -> None:
        api.register_memory_backend(
            backend_id="powercontext",
            factory=PowerContextMemoryManager,
            label="PowerContext",
            config_schema=PowerContextMemoryConfig,
            metadata={
                "description": "PowerContext memory",
                "network_access": True,
                "secret_fields": ["token"],
                "tools": {
                    "memory_search": {
                        "policy_name": "PowerContextMemorySearch",
                        "tool_type": "network",
                        "target_param": "query",
                    },
                    "memory_remember": {
                        "policy_name": "PowerContextMemoryRemember",
                        "tool_type": "network",
                    },
                },
            },
        )


plugin = PowerContextMemoryPlugin()
