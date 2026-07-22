# -*- coding: utf-8 -*-
"""Unified Workspace bootstrap factory.

Shared by the web app lifespan and ACP server to eliminate duplicated
bootstrap logic that previously drifted independently.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..workspace.workspace import Workspace

logger = logging.getLogger(__name__)


class WorkspaceBootstrapFactory:
    """Build the kwargs dict consumed by ``Workspace.bootstrap_plugins()``.

    Components are split into two tiers:

    * **Required** – missing triggers a warning log (not silent).
    * **Optional** – missing is silently skipped (debug log only).
    """

    @staticmethod
    def build_bootstrap_kwargs(
        app_services: Any | None = None,  # pylint: disable=unused-argument
        *,
        extra_hook_clses: list[type] | None = None,
        extra_command_specs: list[Any] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}

        # --- Required components (warn on failure) -----------------------

        try:
            from ...agents.tools import discover_builtin_tool_funcs

            kwargs["builtin_tool_funcs"] = discover_builtin_tool_funcs()
        except Exception:
            logger.warning(
                "Bootstrap: builtin_tool_funcs unavailable",
                exc_info=True,
            )

        try:
            from ...runtime.builtin_commands import (
                collect_builtin_command_specs,
                get_skill_fallback_handler,
            )

            kwargs["builtin_command_specs"] = collect_builtin_command_specs()
            kwargs["builtin_fallback_handler"] = get_skill_fallback_handler()
        except Exception:
            logger.warning(
                "Bootstrap: builtin_command_specs unavailable",
                exc_info=True,
            )

        try:
            from ...hooks.bootstrap.bootstrap_hook import BootstrapHook
            from ...hooks.cron.cron_hook import (
                CronContextHook,
                CronMemoryIsolateHook,
                CronMemoryRestoreHook,
            )
            from ...hooks.error.error_hook import (
                CancelCleanupHook,
                ErrorNormalizeHook,
            )
            from ...hooks.request_setup.contextvars_hook import (
                ContextVarsSetupHook,
            )
            from ...hooks.request_setup.media_hook import MediaProcessHook
            from ...hooks.session.session_hook import (
                SessionLoadHook,
                SessionSaveHook,
            )
            from ...hooks.skill_env.skill_env_hook import (
                SkillEnvCleanupHook,
                SkillEnvHook,
            )

            hook_clses: list[type] = [
                CronContextHook,
                CronMemoryIsolateHook,
                CronMemoryRestoreHook,
                SessionLoadHook,
                SessionSaveHook,
                BootstrapHook,
                SkillEnvHook,
                SkillEnvCleanupHook,
                ContextVarsSetupHook,
                MediaProcessHook,
                ErrorNormalizeHook,
                CancelCleanupHook,
            ]
            if extra_hook_clses:
                hook_clses.extend(extra_hook_clses)
            kwargs["builtin_hook_clses"] = hook_clses
        except Exception:
            logger.warning(
                "Bootstrap: builtin_hook_clses unavailable",
                exc_info=True,
            )

        # --- Optional components (silent skip) ---------------------------

        try:
            from ...hooks.observability.langfuse_hook import (
                LangfuseTraceCleanupHook,
                LangfuseTraceHook,
            )

            kwargs.setdefault("builtin_hook_clses", []).extend(
                [LangfuseTraceHook, LangfuseTraceCleanupHook],
            )
        except Exception:
            logger.debug("Langfuse hooks not available", exc_info=True)

        try:
            from ...runtime.prompt_contributors import _ALL_CONTRIBUTORS

            kwargs["builtin_contributor_clses"] = _ALL_CONTRIBUTORS
        except Exception:
            logger.debug("Prompt contributors not available", exc_info=True)

        try:
            from ...modes.coding import CodingMode
            from ...modes.default import DefaultMode
            from ...modes.goal import GoalMode
            from ...modes.mission import MissionMode

            kwargs["builtin_mode_clses"] = [
                DefaultMode,
                CodingMode,
                MissionMode,
                GoalMode,
            ]
        except Exception:
            logger.debug("Modes not available", exc_info=True)

        # --- Extra command specs (caller-supplied) -----------------------

        if extra_command_specs:
            kwargs.setdefault("builtin_command_specs", []).extend(
                extra_command_specs,
            )

        return kwargs
