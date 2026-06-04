# -*- coding: utf-8 -*-
"""DataPaw plugin entry."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class DataPawPlugin:
    """DataPaw plugin entry. Wires startup / shutdown hooks only."""

    def register(self, api):
        api.register_startup_hook(
            hook_name="datapaw_init",
            callback=self._on_startup,
            priority=50,
        )
        api.register_shutdown_hook(
            hook_name="datapaw_cleanup",
            callback=self._on_shutdown,
            priority=50,
        )

        from .core.routers import tasks_router

        api.register_http_router(
            tasks_router,
            prefix="/tasks",  # final URL: /api/tasks/...
            tags=["datapaw-tasks"],
        )

    async def _on_startup(self):
        logger.info("DataPaw plugin starting up")

        from .agents_setup import ensure_builtin_agents
        from .hooks import (
            patch_plugin_loader_unload,
            setup_channel_sse_hook,
            setup_runner_hooks,
        )

        ensure_builtin_agents()
        setup_runner_hooks()
        setup_channel_sse_hook()
        patch_plugin_loader_unload()

        logger.info("DataPaw plugin startup complete")

    async def _on_shutdown(self):
        # PluginLoader uninstall handles profile/workspace cleanup; nothing
        # to do at lifespan-end teardown beyond logging.
        logger.info("DataPaw plugin shutting down")


plugin = DataPawPlugin()
