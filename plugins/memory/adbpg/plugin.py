# -*- coding: utf-8 -*-
"""ADBPG memory plugin entry point."""

from backend import ADBPGMemoryConfig, ADBPGMemoryManager
from qwenpaw.plugins.api import PluginApi


class ADBPGMemoryPlugin:
    def register(self, api: PluginApi) -> None:
        api.register_memory_backend(
            backend_id="adbpg",
            factory=ADBPGMemoryManager,
            label="ADBPG",
            config_schema=ADBPGMemoryConfig,
            metadata={
                "description": "AnalyticDB for PostgreSQL memory",
                "network_access": True,
                "secret_fields": ["rest_api_key"],
            },
        )


plugin = ADBPGMemoryPlugin()
