# -*- coding: utf-8 -*-
"""Resolve saved conversation settings and request inputs in one place."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from ..config.config import load_persisted_agent_config
from ..config.context import current_runtime_parameters
from ..config.runtime import RuntimeParameters
from ..config.overrides import merge_overrides
from ..config.utils import load_config
from ..providers.model_selection import (
    request_model_override,
    resolve_model_slot_override,
)
from ..utils.io_utils import run_sync_io
from .project_directory import agent_project_dirs_from_config
from .session_thinking import apply_chat_model_settings, get_session_chat

if TYPE_CHECKING:
    from ..runtime.hooks import HookContext

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


async def resolve_runtime_parameters(ctx: HookContext):
    """Construct the execution snapshot before hooks or agent construction."""
    supplied = current_runtime_parameters.get()
    if supplied is None or supplied.profile.id != ctx.agent_id:
        supplied = RuntimeParameters.from_profile(
            await run_sync_io(load_persisted_agent_config, ctx.agent_id),
            global_config=await run_sync_io(load_config),
        )
    chat = await get_session_chat(ctx)
    profile = await apply_chat_model_settings(
        supplied.profile,
        chat.meta if chat else None,
    )
    parameters = replace(supplied, profile=profile)
    request = ctx.request
    request_context = getattr(request, "request_context", None) or {}
    overrides: dict[str, Any] = {}
    if request_context.get("coding_mode") is True:
        overrides = merge_overrides(
            overrides,
            {
                "coding_mode": {"enabled": True},
            },
        )
    selected = request_model_override(request)
    if selected is not None:
        slot = resolve_model_slot_override(selected)
        if slot is not None:
            overrides["active_model"] = slot.model_dump()
    if overrides:
        parameters = parameters.with_overrides(overrides)

    if parameters.config.agent_mode is not None:
        from ..modes.catalog import resolve_mode_activation

        activation = resolve_mode_activation(
            ctx.workspace,
            parameters.config.agent_mode,
        )
        parameters = parameters.with_defaults(
            merge_overrides(activation.config, parameters.defaults),
        )

    config = parameters.config
    session_dirs = await _session_project_dirs(ctx)
    explicit = merge_overrides(parameters.defaults, parameters.overrides)
    if {"project_dir", "project_dirs"}.intersection(explicit):
        session_dirs = None
    state = (getattr(ctx, "mode_state", {}) or {}).get("mission", {})
    loop_dir = state.get("loop_dir") if state.get("active") else None
    workspace_dir = ctx.workspace_dir
    if workspace_dir is None:
        from ..constant import WORKING_DIR

        workspace_dir = Path(config.workspace_dir or WORKING_DIR)
    resolved = await run_sync_io(
        _resolve_turn_project_dirs,
        workspace_dir=workspace_dir,
        agent_project_dir=config.project_dir,
        agent_project_dirs=agent_project_dirs_from_config(config),
        session_project_dirs=session_dirs,
        request_context=request_context,
        mission_loop_dir=loop_dir,
    )
    if resolved is not None and resolved.source != "workspace_fallback":
        parameters = parameters.with_overrides(
            {
                "project_dir": str(resolved.primary_path),
                "project_dirs": [
                    {"path": str(item.path), "label": item.label}
                    for item in resolved.dirs
                ],
            },
        )
    return parameters, resolved


def _resolve_turn_project_dirs(
    *,
    workspace_dir: Path,
    agent_project_dir: str | None,
    session_project_dirs: Optional[list],
    request_context: Optional[dict],
    mission_loop_dir: str | None,
    agent_project_dirs: Optional[list] = None,
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
    pinned; the caller then clears the current project context.
    """
    from ..services.project_directory import (
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
        from ..agents.fork_project import resolve_allowed_fork_project_dir

        allowed_dirs: list[str] = []
        allowed_dirs.extend(
            _entry_path_strings(agent_project_dirs)
            if agent_project_dirs
            else ([agent_project_dir] if agent_project_dir else []),
        )
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
    if request_context is not None:
        active_project = request_context.get("active_mode_project_dir")
        if isinstance(active_project, str) and active_project.strip():
            mode_override = [active_project]
    if mission_loop_dir:
        from ..modes.mission.state import read_loop_config

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
            agent_project_dirs=agent_project_dirs,
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

    Accept a pre-validated ``project_dir`` from server-side callers.

    Per-run only: never written back to the agent's saved default.
    """
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
    from ..services.project_directory import normalize_project_dir_list

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

    from ..app.channels.schema import DEFAULT_CHANNEL
    from ..services.project_directory import (
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
