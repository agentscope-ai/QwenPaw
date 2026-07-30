# -*- coding: utf-8 -*-
"""Chrome plugin entry point."""

from __future__ import annotations

import logging
from qwenpaw.plugins.api import PluginApi

# Kept for the milestone-A bridge wiring contract.  A semantic dispatcher is
# deliberately not registered until the later control milestone.
# no-name-in-module: astroid confuses this namespace-relative "api" package
# with other plugins' top-level "api" packages during whole-repo lint runs.
# pylint: disable=unused-import,no-name-in-module
from .api.routes import (
    api_router,
    configure_nm_bridge,
    get_extension_status,
)

logger = logging.getLogger(__name__)


class ChromePlugin:
    """Register Chrome plugin capabilities."""

    def startup(self) -> None:
        """Write the single Native Messaging backend configuration."""
        configure_nm_bridge()

    async def shutdown(self) -> None:
        """Keep the installed Native Messaging configuration on unload."""

    def register(self, api: PluginApi) -> None:
        """Register plugin integrations."""
        api.register_http_router(
            api_router,
            prefix="/chrome",
            tags=["chrome"],
        )
        api.register_shutdown_hook(
            hook_name="chrome_clear_connection_manager",
            callback=self.shutdown,
            priority=120,
        )
        api.register_startup_hook(
            hook_name="chrome_register_manifest",
            callback=self.startup,
            priority=110,
        )
        logger.info("Chrome plugin registered: %s", api.plugin_id)

    async def get_runtime_status(self) -> dict:
        """Return Chrome runtime status for plugin detail pages."""
        return await get_extension_status()


plugin = ChromePlugin()
