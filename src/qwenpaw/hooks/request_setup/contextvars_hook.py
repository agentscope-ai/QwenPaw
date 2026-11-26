# -*- coding: utf-8 -*-
"""Publish resolved runtime parameters to the tool execution context."""

from __future__ import annotations

import uuid

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase


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
            set_current_project_dir_source,
            set_current_project_dirs,
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

        config = ctx.agent_config
        running = config.running
        pruning = running.light_context_config.tool_result_pruning_config
        set_current_recent_max_bytes(pruning.pruning_recent_msg_max_bytes)
        set_current_shell_command_timeout(running.shell_command_timeout)
        set_current_shell_command_executable(
            running.shell_command_executable or None,
        )
        set_current_workspace_dir(ctx.workspace_dir)
        resolved = ctx.project_directories
        if resolved is not None:
            set_current_project_dirs(resolved.dirs)
            set_current_project_dir(resolved.primary_path)
            set_current_project_dir_source(resolved.source)
        else:
            set_current_project_dirs(())
            set_current_project_dir(None)
            set_current_project_dir_source(None)
        return HookResult()


class MailF1CleanupHook(LifecycleHook):
    """Clear mail F1 exploration mode for the session in FINALLY.

    F1 mode is scoped to one request ("for the remainder of this
    request"). The session-level registry outlives the request, so this
    hook guarantees deactivation for every entry point — not only the
    mail monitor's own finally block — preventing STRICT gating from
    leaking into later requests of the same session.
    """

    phase = Phase.FINALLY
    name = "mail_f1_cleanup"
    priority = 30

    async def run(self, ctx: HookContext) -> HookResult:
        from ...config.context import deactivate_f1_for_session

        deactivate_f1_for_session(ctx.session_id or "")
        return HookResult()
