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
                    "prepare_context": {
                        "policy_name": "PowerContextPrepareContext",
                        "tool_type": "network",
                        "target_param": "query",
                    },
                    "artifact_schema": {
                        "policy_name": "PowerContextArtifactSchema",
                        "tool_type": "network",
                        "target_param": "family",
                    },
                    "artifact_search": {
                        "policy_name": "PowerContextArtifactSearch",
                        "tool_type": "network",
                        "target_param": "query",
                    },
                    "artifact_list": {
                        "policy_name": "PowerContextArtifactList",
                        "tool_type": "network",
                        "target_param": "family",
                    },
                    "artifact_get": {
                        "policy_name": "PowerContextArtifactGet",
                        "tool_type": "network",
                        "target_param": "artifact_id",
                    },
                    "artifact_history": {
                        "policy_name": "PowerContextArtifactHistory",
                        "tool_type": "network",
                        "target_param": "artifact_id",
                    },
                    "artifact_create": {
                        "policy_name": "PowerContextArtifactCreate",
                        "tool_type": "network",
                        "target_param": "family",
                    },
                    "artifact_replace": {
                        "policy_name": "PowerContextArtifactReplace",
                        "tool_type": "network",
                        "target_param": "artifact_id",
                    },
                },
            },
        )


plugin = PowerContextMemoryPlugin()
