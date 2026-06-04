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
            hook_name="datapaw_shutdown",
            callback=self._on_shutdown,
            priority=50,
        )
        api.register_uninstall_hook(
            hook_name="datapaw_uninstall",
            callback=self._on_uninstall,
            priority=50,
        )

        from .constants import PLUGIN_DIR
        from .core.routers import tasks_router

        api.register_http_router(
            tasks_router,
            prefix="/tasks",  # final URL: /api/tasks/...
            tags=["datapaw-tasks"],
        )

        api.register_skill_provider(
            skills_dir=PLUGIN_DIR / "skills",
            enabled_by_default=True,
            channels=["all"],
        )

    async def _on_startup(self):
        logger.info("DataPaw plugin starting up")

        from .agents_setup import ensure_builtin_agents
        from .hooks import setup_channel_sse_hook, setup_runner_hooks

        ensure_builtin_agents()
        setup_runner_hooks()
        setup_channel_sse_hook()

        logger.info("DataPaw plugin startup complete")

    def _on_uninstall(self, plugin_id: str, delete_files: bool = False):
        from .agents_setup import uninstall_builtin_agents

        uninstall_builtin_agents()

    async def _on_shutdown(self):
        logger.info("DataPaw plugin shutting down")


plugin = DataPawPlugin()
