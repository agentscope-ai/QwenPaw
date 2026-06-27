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
        from .core.routers import data_sources_router, docs_router, tasks_router

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
        api.register_http_router(
            docs_router,
            prefix="/v1/docs",  # final URL: /api/v1/docs/...
            tags=["datapaw-docs"],
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
        api.register_prompt_section(
            name="datapaw.selected_data_source",
            after="workspace",
            agent_id="datapaw",
            provider=self._provide_selected_data_source,
        )

    async def _on_startup(self):
        logger.info("DataPaw plugin starting up")

        from qwenpaw.constant import EnvVarLoader

        import asyncio
        import os

        from .constants import DATAPAW_DATA_SOURCE_BACKEND_ENV
        from .core.oss_sync import reload_from_oss

        if EnvVarLoader.get_bool("DATAPAW_OSS_RELOAD", False):
            try:
                await asyncio.to_thread(reload_from_oss)
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "DataPaw OSS reload on startup failed",
                    exc_info=True,
                )

        if (
            os.environ.get(DATAPAW_DATA_SOURCE_BACKEND_ENV) or "json"
        ).strip().lower() == "hologres":
            from .core.data_sources.hologres_store import ensure_data_source_table

            try:
                await asyncio.to_thread(ensure_data_source_table)
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "DataPaw Hologres table init on startup failed",
                    exc_info=True,
                )

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

    @staticmethod
    def _provide_selected_data_source(agent) -> str:
        from .core.data_sources.runtime_context import (
            format_data_source_prompt,
        )

        return format_data_source_prompt(
            getattr(agent, "_datasource_context", None),
        )

    def _on_uninstall(self, **_kwargs):
        from .agents_setup import uninstall_builtin_agents

        uninstall_builtin_agents()

    async def _on_shutdown(self):
        logger.info("DataPaw plugin shutting down")


plugin = DataPawPlugin()
