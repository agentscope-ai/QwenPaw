# -*- coding: utf-8 -*-
"""ContextVar setup hook.

Injects per-request ContextVars before agent execution so that tools
(shell, file_io, etc.) see correct workspace_dir, session_id, etc.

This hook is the **single resolver** of the effective project
directories for a turn: console routers no longer pre-resolve, they
only persist pending picks onto the chat. Resolution precedence is
fork worktree → mode pin → trusted request override → session list
(per-chat, or inherited from a parent agent, or pending from the
client) → agent default (single dir) → workspace fallback.
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

        from ...constant import WORKING_DIR

        workspace_dir = ctx.workspace_dir or Path(WORKING_DIR)

        session_project_dirs = await _session_project_dirs(ctx)
        inherited = False

        # Forked subagents must resolve relative file/shell paths against
        # the worktree they were assigned, and must not be able to escape
        # it. Validate before handing it to the resolver, which trusts it.
        # Allowed roots: every bound project dir (agent default and the
        # session list alike) plus the workspace — a fork may target any
        # repository the user attached to this agent/chat.
        fork_dir = None
        request_override = None
        if isinstance(request_context, dict):
            from ...agents.fork_project import (
                resolve_allowed_fork_project_dir,
            )

            allowed_dirs: list[str] = []
            if isinstance(agent_project_dir, str) and agent_project_dir:
                allowed_dirs.append(agent_project_dir)
            if session_project_dirs:
                allowed_dirs.extend(
                    entry["path"]
                    for entry in session_project_dirs
                    if isinstance(entry, dict) and entry.get("path")
                )
            fork_dir = resolve_allowed_fork_project_dir(
                request_context.get("fork_project_dir"),
                workspace_dir=workspace_dir,
                project_dirs=allowed_dirs,
            )
            request_override = _trusted_request_project_dir(request_context)
            if session_project_dirs is None:
                inherited_dirs = _inherited_project_dirs(request_context)
                if inherited_dirs is not None:
                    session_project_dirs = inherited_dirs
                    inherited = True
                else:
                    session_project_dirs = _pending_project_dirs(
                        request_context,
                    )

        # The workspace ContextVar always points at the agent's own storage.
        # Never repoint it to a project: memory, skills, cache, approvals
        # and audit records resolve from it and must stay inside the agent.
        set_current_workspace_dir(workspace_dir)

        self._apply_project_dirs(
            ctx,
            workspace_dir=workspace_dir,
            agent_project_dir=agent_project_dir,
            session_project_dirs=session_project_dirs,
            request_override=request_override,
            fork_dir=fork_dir,
            inherited=inherited,
        )
        return HookResult()

    @staticmethod
    def _apply_project_dirs(
        ctx: HookContext,
        *,
        workspace_dir: Path,
        agent_project_dir: str | None,
        session_project_dirs: list[dict] | None,
        request_override: str | None,
        fork_dir: object | None,
        inherited: bool,
    ) -> None:
        """Resolve the effective project dirs once and pin them."""
        from ...config.context import (
            set_current_project_dir,
            set_current_project_dir_source,
            set_current_project_dirs,
        )
        from ...services.project_directory import (
            SOURCE_INHERITED,
            SOURCE_SESSION,
            resolve_effective_project_dirs,
        )

        # A running Mission pins the directories for the whole run. The
        # pin lives in the on-disk loop config (it must survive process
        # restarts); the snapshot is taken when the mission starts, so a
        # mid-run session switch cannot move the worker.
        mode_override = None
        mode_state = getattr(ctx, "mode_state", {}) or {}
        mission_state = mode_state.get("mission", {})
        if isinstance(mission_state, dict) and mission_state.get("active"):
            loop_dir = mission_state.get("loop_dir")
            if isinstance(loop_dir, str) and loop_dir:
                from ...modes.mission.state import read_loop_config

                mission_config = read_loop_config(Path(loop_dir))
                pinned = mission_config.get("source_project_dirs")
                if isinstance(pinned, list) and pinned:
                    mode_override = pinned
                else:
                    value = mission_config.get("source_project_dir")
                    if isinstance(value, str) and value:
                        mode_override = [value]

        try:
            resolved = resolve_effective_project_dirs(
                workspace_dir,
                agent_project_dir=agent_project_dir,
                session_project_dirs=session_project_dirs,
                request_override=request_override,
                mode_override=mode_override,
                fork_project_dir=str(fork_dir) if fork_dir else None,
            )
        except ValueError:
            logger.warning(
                "contextvars_setup: could not resolve project dirs",
                exc_info=True,
            )
            return

        if inherited and resolved.source == SOURCE_SESSION:
            # Distinguish parent-snapshot inheritance from a genuine
            # per-chat override in audit/UI.
            from dataclasses import replace as _dc_replace

            resolved = _dc_replace(resolved, source=SOURCE_INHERITED)

        primary = resolved.primary
        if not primary.exists and not resolved.is_workspace_fallback:
            # Do not silently fall back: writing to the wrong place is far
            # worse than a clear tool error the user can act on.
            logger.warning(
                "Effective primary project dir does not exist: %s "
                "(source=%s)",
                primary.path,
                resolved.source,
            )

        set_current_project_dirs(resolved.dirs)
        set_current_project_dir(primary.path)
        set_current_project_dir_source(resolved.source)
        logger.debug(
            "contextvars_setup: project dirs resolved source=%s dirs=%s",
            resolved.source,
            [str(entry.path) for entry in resolved.dirs],
        )


def _trusted_request_project_dir(request_context: dict) -> str | None:
    """Return an ephemeral PRIMARY project override from a trusted source.

    Recognised sources:

    * ACP session metadata (``qwenpaw.project_dir``)
    * cron task config (``cron_project_dir``)
    * a pre-validated ``project_dir`` injected by server-side callers

    Per-run only: never written back to the agent's saved default.
    """
    from ...agents.acp.meta import ACP_PROJECT_DIR_META_KEY

    for key in (ACP_PROJECT_DIR_META_KEY, "cron_project_dir"):
        value = request_context.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = request_context.get("project_dir")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _inherited_project_dirs(request_context: dict) -> list[dict] | None:
    """Read a parent agent's resolved project-dir snapshot, if present.

    Non-fork subagents do not share the parent's chat, so the parent's
    resolved list is handed down explicitly and fills the session slot.
    Client-supplied, so every entry must be an existing directory —
    anything else is dropped rather than granted.
    """
    raw = request_context.get("inherited_project_dirs")
    if not isinstance(raw, list) or not raw:
        return None
    return _validated_dir_entries(raw, kind="inherited")


def _pending_project_dirs(request_context: dict) -> list[dict] | None:
    """Read console pending picks for a brand-new chat, if present.

    A chat without a server id cannot persist a session override yet, so
    the console sends the chosen list with the first message. The console
    router also persists it onto the chat as soon as the chat exists;
    reading it here too is what makes the **first** turn already run in
    the chosen directories if the persistence has not landed yet.

    Accepts ``session_project_dirs`` (the list) and the legacy singular
    ``session_project_dir``. Client-supplied, so every entry is
    validated here: a non-directory is dropped rather than granted.
    """
    raw: list | None = None
    pending_list = request_context.get("session_project_dirs")
    if isinstance(pending_list, list) and pending_list:
        raw = pending_list
    else:
        pending_single = request_context.get("session_project_dir")
        if isinstance(pending_single, str) and pending_single.strip():
            raw = [pending_single]
    if raw is None:
        return None
    return _validated_dir_entries(raw, kind="pending")


def _validated_dir_entries(raw: list, *, kind: str) -> list[dict] | None:
    """Normalize raw entries and keep only existing directories."""
    from ...services.project_directory import normalize_project_dir_list

    entries = []
    for path, label in normalize_project_dir_list(raw):
        if not path.is_dir():
            logger.warning(
                "Ignoring %s project dir that is not a directory: %s",
                kind,
                path,
            )
            continue
        entries.append({"path": str(path), "label": label})
    return entries or None


async def _session_project_dirs(ctx: HookContext) -> list[dict] | None:
    """Read the persisted per-chat project-dirs override, if any.

    Runs on **every** turn: the override lives on the chat, so this is
    what keeps session-level directories in effect after the turn that
    set them.
    """
    if not ctx.session_id:
        return None
    try:
        from ...app.channels.schema import DEFAULT_CHANNEL
        from ...services.project_directory import (
            session_project_dirs_from_meta,
        )

        workspace = getattr(ctx, "workspace", None)
        chat_manager = getattr(workspace, "chat_manager", None)
        if chat_manager is None:
            return None

        request = getattr(ctx, "request", None)
        # `channel` is required by the lookup: chats are indexed per
        # channel, so omitting it finds nothing. Cron/heartbeat turns may
        # not carry one, hence the default.
        channel = getattr(request, "channel", None) or DEFAULT_CHANNEL
        user_id = getattr(request, "user_id", None) or None

        chat_id = await chat_manager.get_chat_id_by_session(
            ctx.session_id,
            channel,
            user_id,
        )
        if not chat_id:
            return None
        chat = await chat_manager.get_chat(chat_id)
        if chat is None:
            return None
        return session_project_dirs_from_meta(chat.meta)
    except Exception:
        # Warning, not debug: a silent failure here degrades to the agent
        # default, which looks like "the setting reverted on its own" and
        # is very hard to trace from the UI.
        logger.warning(
            "contextvars_setup: session project dirs lookup failed; "
            "falling back to the agent default",
            exc_info=True,
        )
        return None


__all__ = ["ContextVarsSetupHook"]
