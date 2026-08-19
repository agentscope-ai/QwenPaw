# -*- coding: utf-8 -*-
"""ContextVar setup hook.

Injects per-request ContextVars before agent execution so that tools
(shell, file_io, etc.) see correct workspace_dir, session_id, etc.
"""

from __future__ import annotations

import logging
from pathlib import Path
import uuid

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)


class ContextVarsSetupHook(LifecycleHook):
    """Inject per-request ContextVars before agent execution."""

    phase = Phase.PRE_DISPATCH
    name = "contextvars_setup"
    priority = 10

    async def run(  # pylint: disable=too-many-statements
        self,
        ctx: HookContext,
    ) -> HookResult:
        from ...config.context import (
            set_current_project_dir,
            set_current_workspace_dir,
            set_current_session_id,
            set_current_recent_max_bytes,
            set_current_shell_command_timeout,
            set_current_shell_command_executable,
        )
        from ...app.agent_context import (
            set_current_agent_id,
            set_current_approval_route,
            set_current_channel,
            set_current_root_session_id,
            set_current_session_id as _set_app_session_id,
            set_current_user_id,
        )

        set_current_agent_id(ctx.agent_id or "default")
        _session_id = ctx.session_id or ""
        set_current_session_id(_session_id)
        _set_app_session_id(_session_id)
        set_current_root_session_id(
            ctx.root_session_id or ctx.session_id or "",
        )
        from ...app.computer_use import set_current_computer_use_turn_id

        set_current_computer_use_turn_id(uuid.uuid4().hex)
        set_current_user_id(ctx.request.user_id)
        set_current_channel(getattr(ctx.request, "channel", None))
        request_context = getattr(ctx.request, "request_context", None)
        if isinstance(request_context, dict) and request_context.get(
            "_spawn_subagent",
        ):
            approval_route = {
                key: request_context.get(key)
                for key in (
                    "root_session_id",
                    "user_id",
                    "channel",
                    "channel_meta",
                )
            }
        else:
            approval_route = {
                "root_session_id": ctx.root_session_id or ctx.session_id or "",
                "user_id": getattr(ctx.request, "user_id", None) or "",
                "channel": getattr(ctx.request, "channel", None) or "",
                "channel_meta": getattr(ctx.request, "channel_meta", None),
            }
        if isinstance(request_context, dict) and request_context.get(
            "approval_level",
        ):
            approval_route["approval_level"] = request_context.get(
                "approval_level",
            )
        set_current_approval_route(approval_route)

        agent_project_dir = None
        try:
            from ...config.config import load_agent_config

            cfg = load_agent_config(ctx.agent_id)
            running = cfg.running
            pruning_cfg = (
                running.light_context_config.tool_result_pruning_config
            )
            set_current_recent_max_bytes(
                pruning_cfg.pruning_recent_msg_max_bytes,
            )
            set_current_shell_command_timeout(running.shell_command_timeout)
            set_current_shell_command_executable(
                running.shell_command_executable or None,
            )
            agent_project_dir = cfg.project_dir
        except Exception:
            logger.warning(
                "contextvars_setup: config-derived vars failed; "
                "tools may see defaults",
                exc_info=True,
            )

        # Forked subagents must resolve relative file/shell paths against
        # the worktree, not the parent workspace.
        from ...constant import WORKING_DIR

        workspace_dir = ctx.workspace_dir or Path(WORKING_DIR)
        fork_dir = None
        if isinstance(request_context, dict):
            from ...agents.fork_project import resolve_allowed_fork_project_dir

            fork_dir = resolve_allowed_fork_project_dir(
                request_context.get("fork_project_dir"),
                workspace_dir=workspace_dir,
                coding_project_dir=agent_project_dir,
            )
        from ...services.project_directory import (
            resolve_effective_project_dir,
        )

        trusted_override = None
        if isinstance(request_context, dict):
            value = request_context.get("project_dir")
            if isinstance(value, str):
                trusted_override = value
        active_mode_override = None
        mode_state = getattr(ctx, "mode_state", {}) or {}
        mission_state = mode_state.get("mission", {})
        if isinstance(mission_state, dict) and mission_state.get("active"):
            loop_dir = mission_state.get("loop_dir")
            if isinstance(loop_dir, str) and loop_dir:
                from ...modes.mission.state import read_loop_config

                mission_config = read_loop_config(Path(loop_dir))
                value = mission_config.get("source_project_dir")
                if isinstance(value, str) and value:
                    active_mode_override = value
        project_dir, _source = resolve_effective_project_dir(
            workspace_dir,
            agent_project_dir=agent_project_dir,
            trusted_override=trusted_override,
            active_mode_override=active_mode_override,
            fork_project_dir=str(fork_dir) if fork_dir else None,
        )
        set_current_workspace_dir(workspace_dir)
        set_current_project_dir(project_dir)
        return HookResult()


__all__ = ["ContextVarsSetupHook"]
