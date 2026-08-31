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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import uuid

from ..base import LifecycleHook
from ...runtime.hooks import HookAction, HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)


class SessionProjectDirsUnavailable(RuntimeError):
    """The chat's project-directory override could not be read.

    Distinct from "this chat has no override": the difference decides
    whether the turn may run. See :func:`_session_project_dirs`.
    """


@dataclass(frozen=True)
class _ResolvedTurn:
    """What one turn's project-dir resolution produced."""

    dirs: tuple
    primary_path: Path
    source: str


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

        try:
            session_project_dirs = await _session_project_dirs(ctx)
        except SessionProjectDirsUnavailable:
            # Fail closed. Reporting "no override" here would silently run
            # the turn in the agent default, so a relative write lands in
            # a different repository than the one the chat is bound to and
            # the next successful read makes the mistake invisible.
            logger.warning(
                "contextvars_setup: session project dirs unreadable; "
                "refusing to run the turn in a different directory",
                exc_info=True,
            )
            set_current_workspace_dir(workspace_dir)
            return HookResult(
                action=HookAction.SHORT_CIRCUIT,
                payload=_project_dirs_unavailable_msg(),
            )

        # The workspace ContextVar always points at the agent's own storage.
        # Never repoint it to a project: memory, skills, cache, approvals
        # and audit records resolve from it and must stay inside the agent.
        set_current_workspace_dir(workspace_dir)

        # A running Mission pins the directories for the whole run. The pin
        # lives in the on-disk loop config (it must survive process
        # restarts); the snapshot is taken when the mission starts, so a
        # mid-run session switch cannot move the worker. Reading it is
        # filesystem I/O, so only the path is collected here and the read
        # itself happens inside the worker thread below.
        mission_loop_dir = None
        mode_state = getattr(ctx, "mode_state", {}) or {}
        mission_state = mode_state.get("mission", {})
        if isinstance(mission_state, dict) and mission_state.get("active"):
            loop_dir = mission_state.get("loop_dir")
            if isinstance(loop_dir, str) and loop_dir:
                mission_loop_dir = loop_dir

        from ...utils.io_utils import run_sync_io

        resolved = await run_sync_io(
            _resolve_turn_project_dirs,
            workspace_dir=workspace_dir,
            agent_project_dir=agent_project_dir,
            session_project_dirs=session_project_dirs,
            request_context=(
                request_context if isinstance(request_context, dict) else None
            ),
            mission_loop_dir=mission_loop_dir,
        )
        if resolved is not None:
            # Set on the event loop, never inside the worker thread:
            # ``to_thread`` runs with a *copy* of the context, so a
            # ContextVar written there is discarded when the thread ends.
            set_current_project_dirs(resolved.dirs)
            set_current_project_dir(resolved.primary_path)
            set_current_project_dir_source(resolved.source)
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


def _project_dirs_unavailable_msg():
    """The turn-ending notice for an unreadable session override."""
    from agentscope.message import Msg
    from agentscope.message._block import TextBlock

    return Msg(
        name="system",
        role="system",
        content=[
            TextBlock(
                type="text",
                text=(
                    "This chat's project directories could not be read, so "
                    "the turn was stopped rather than run somewhere else. "
                    "Retry in a moment; if it keeps failing, re-pick the "
                    "directories for this chat."
                ),
            ),
        ],
    )


def _resolve_turn_project_dirs(
    *,
    workspace_dir: Path,
    agent_project_dir: str | None,
    session_project_dirs: Optional[list],
    request_context: Optional[dict],
    mission_loop_dir: str | None,
) -> Optional[_ResolvedTurn]:
    """Resolve this turn's project directories in one blocking pass.

    Every step here touches the filesystem — ``resolve()`` per configured
    path, ``is_dir()`` for the client-supplied lists, the fork worktree
    check, the Mission pin read, and the ``exists`` snapshot. They are
    kept in one synchronous function so the caller can hand the whole
    thing to a single worker thread: an unresponsive mount then stalls
    that thread instead of the event loop. Offloading only part of it
    would just move the stall somewhere else — which is why this must not
    be called directly from a coroutine.

    Returns ``None`` when the workspace is unusable and nothing can be
    pinned; the caller then leaves the ContextVars alone.
    """
    from ...services.project_directory import (
        SOURCE_INHERITED,
        SOURCE_SESSION,
        resolve_effective_project_dirs,
    )

    inherited = False
    fork_dir = None
    request_override = None

    if request_context is not None:
        # Forked subagents must resolve relative file/shell paths against
        # the worktree they were assigned, and must not be able to escape
        # it. Validate before handing it to the resolver, which trusts it.
        # Allowed roots: every bound project dir (agent default and the
        # session list alike) plus the workspace — a fork may target any
        # repository the user attached to this agent/chat.
        from ...agents.fork_project import resolve_allowed_fork_project_dir

        allowed_dirs: list[str] = []
        if isinstance(agent_project_dir, str) and agent_project_dir:
            allowed_dirs.append(agent_project_dir)
        allowed_dirs.extend(_entry_path_strings(session_project_dirs))
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
                session_project_dirs = _pending_project_dirs(request_context)

    mode_override = None
    if mission_loop_dir:
        from ...modes.mission.state import read_loop_config

        mission_config = read_loop_config(Path(mission_loop_dir))
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
        return None

    source = resolved.source
    if inherited and source == SOURCE_SESSION:
        # Distinguish parent-snapshot inheritance from a genuine per-chat
        # override in audit/UI.
        source = SOURCE_INHERITED

    primary = resolved.primary
    if not primary.exists and not resolved.is_workspace_fallback:
        # Do not silently fall back: writing to the wrong place is far
        # worse than a clear tool error the user can act on.
        logger.warning(
            "Effective primary project dir does not exist: %s (source=%s)",
            primary.path,
            source,
        )
    logger.debug(
        "contextvars_setup: project dirs resolved source=%s dirs=%s",
        source,
        [str(entry.path) for entry in resolved.dirs],
    )
    return _ResolvedTurn(
        dirs=resolved.dirs,
        primary_path=primary.path,
        source=source,
    )


def _entry_path_strings(entries: Optional[list]) -> list[str]:
    """Path strings from raw entries, **without** normalizing them.

    Only used to seed the fork worktree allow-list, which resolves the
    roots it is given anyway — normalizing here would resolve every
    directory an extra time for no added information.
    """
    if not entries:
        return []
    paths: list[str] = []
    for entry in entries:
        raw: Any = entry
        if isinstance(entry, dict):
            raw = entry.get("path")
        elif isinstance(entry, (list, tuple)):
            raw = entry[0] if entry else None
        if isinstance(raw, (str, Path)) and str(raw).strip():
            paths.append(str(raw))
    return paths


def _trusted_request_project_dir(request_context: dict) -> str | None:
    """Return an ephemeral PRIMARY project override from a trusted source.

    Recognised sources:

    * ACP session metadata (``qwenpaw.project_dir``)
    * a pre-validated ``project_dir`` injected by server-side callers

    Per-run only: never written back to the agent's saved default.
    """
    from ...agents.acp.meta import ACP_PROJECT_DIR_META_KEY

    value = request_context.get(ACP_PROJECT_DIR_META_KEY)
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
    router normally consumes those keys — it persists the pick onto the
    chat and removes them, and from then on ``_session_project_dirs``
    reads the chat. They only survive to here when the router could not
    persist them (or when a non-console client sends them directly), and
    reading them then is what keeps the **first** turn running in the
    directories the user picked instead of the agent default.

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


async def _session_project_dirs(ctx: HookContext) -> list | None:
    """Read the persisted per-chat project-dirs override, if any.

    Runs on **every** turn: the override lives on the chat, so this is
    what keeps session-level directories in effect after the turn that
    set them.

    Three outcomes, and the caller must keep them apart:

    * a list — the chat's override (possibly empty, meaning "explicitly
      nothing bound").
    * ``None`` — there is legitimately no override to read: no session
      id, no chat manager, or no chat for this session/channel. Cron and
      heartbeat turns routinely land here. The resolver reads it as
      "inherit the agent default", which is correct.
    * :class:`SessionProjectDirsUnavailable` — the override *may* exist
      but could not be read (repository error, malformed record).
      Returning ``None`` for this would resolve to the agent default and
      run the turn in the wrong directory, so it is raised instead.

    The entries are returned **unnormalized**; the resolver normalizes
    what it is handed, and doing it twice would ``resolve()`` every
    directory twice per turn.
    """
    if not ctx.session_id:
        return None

    from ...app.channels.schema import DEFAULT_CHANNEL
    from ...services.project_directory import (
        session_project_dirs_raw_from_meta,
    )

    workspace = getattr(ctx, "workspace", None)
    chat_manager = getattr(workspace, "chat_manager", None)
    if chat_manager is None:
        return None

    request = getattr(ctx, "request", None)
    # `channel` is required by the lookup: chats are indexed per channel,
    # so omitting it finds nothing. Cron/heartbeat turns may not carry
    # one, hence the default.
    channel = getattr(request, "channel", None) or DEFAULT_CHANNEL
    user_id = getattr(request, "user_id", None) or None

    try:
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
        return session_project_dirs_raw_from_meta(chat.meta)
    except Exception as exc:
        raise SessionProjectDirsUnavailable(
            f"could not read project dirs for session {ctx.session_id}",
        ) from exc


__all__ = [
    "ContextVarsSetupHook",
    "MailF1CleanupHook",
    "SessionProjectDirsUnavailable",
]
