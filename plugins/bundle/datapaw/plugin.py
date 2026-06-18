# -*- coding: utf-8 -*-
# pylint: disable=relative-beyond-top-level
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
        from .core.routers import data_sources_router, tasks_router

        api.register_http_router(
            tasks_router,
            prefix="/tasks",  # final URL: /api/tasks/...
            tags=["datapaw-tasks"],
        )
        api.register_http_router(
            data_sources_router,
            prefix="/datapaw/data-sources",
            tags=["datapaw-data-sources"],
        )

        api.register_skill_provider(
            skills_dir=PLUGIN_DIR / "skills",
            enabled_by_default=True,
            channels=["all"],
        )

        api.register_prompt_section(
            name="datapaw.master",
            after="workspace",
            agent_id="datapaw",
            provider=self._provide_master_md,
        )
        api.register_prompt_section(
            name="datapaw.env_hint",
            after="workspace",
            agent_id="datapaw",
            provider=self._provide_env_hint,
        )

    async def _on_startup(self):
        logger.info("DataPaw plugin starting up")

        from .agents_setup import ensure_builtin_agents
        from .hooks import (
            setup_channel_sse_hook,
            setup_console_request_context_hook,
            setup_mcp_timeout_hook,
            setup_runner_hooks,
        )

        setup_mcp_timeout_hook()
        ensure_builtin_agents()
        setup_runner_hooks()
        setup_channel_sse_hook()
        setup_console_request_context_hook()

        logger.info("DataPaw plugin startup complete")

    @staticmethod
    def _provide_master_md(agent) -> str:
        from .core.agents.base import _read_master_md

        lang = getattr(agent, "_lang", "zh")
        return _read_master_md(lang)

    @staticmethod
    def _provide_env_hint(agent) -> str:
        from pathlib import Path

        from .core.i18n import tr
        from .core.path_context import default_artifacts_root

        agent_config = getattr(agent, "_agent_config", None)
        agent_id: str = agent_config.id if agent_config else "datapaw"
        ws = getattr(agent, "_workspace_dir", None)
        workspace_dir: Path | None = Path(ws) if ws is not None else None
        artifacts_root = default_artifacts_root(agent_id, workspace_dir)
        lang: str = getattr(agent, "_lang", "zh")
        return tr("env.hint", lang, root=artifacts_root)

    def _on_uninstall(self, **_kwargs):
        from .agents_setup import uninstall_builtin_agents

        uninstall_builtin_agents()

    async def _on_shutdown(self):
        logger.info("DataPaw plugin shutting down")


plugin = DataPawPlugin()
