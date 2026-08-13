# -*- coding: utf-8 -*-
"""Session management slash commands.

Adds the ``/sessions`` and ``/session`` slash commands so users on
channels without a session-switching UI (TUI, IM channels, direct HTTP
calls) can inspect, switch, create and close their conversations:

- ``/sessions``            — list this user's chats (id, name, channel,
  message count), marking the current one
- ``/session switch <id>`` — continue another conversation by loading its
  persisted context into the current dialogue
- ``/session new``         — clear the context and register a fresh chat
- ``/session close <id>``  — delete a chat spec, its checkpoints and its
  persisted session state

The commands are backed by the same persistence layer as the chat REST
API: :class:`~qwenpaw.app.chats.manager.ChatManager` (``chats.json``) for
the session registry and
:class:`~qwenpaw.app.chats.session.SafeJSONSession` (``sessions/``) for
conversation state.  Requests are scoped to the sender's ``user_id`` so
one user can never list, switch to, or close another user's sessions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from agentscope.message import Msg, TextBlock

from ..slash_command_registry import CommandSpec

if TYPE_CHECKING:
    from ..hooks import HookContext

logger = logging.getLogger(__name__)

_HELP_SESSIONS = "List your sessions"
_HELP_SESSION = "Manage sessions: switch <id> | new | close <id>"


def _make_msg(text: str) -> Msg:
    """Build a system reply message for a slash command."""
    return Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text=text)],
    )


def _user_id(ctx: "HookContext") -> str:
    """Resolve the effective user id for the request."""
    request = getattr(ctx, "request", None)
    user_id = (getattr(request, "user_id", "") if request else "") or ""
    return user_id or ctx.session_id


def _channel(ctx: "HookContext") -> str:
    """Resolve the effective channel for the request."""
    request = getattr(ctx, "request", None)
    return (getattr(request, "channel", "") if request else "") or ""


async def _resolve_target(
    mgr: Any,
    target: str,
    *,
    user_id: str,
) -> Any | None:
    """Resolve a ``<id>`` argument to a chat spec owned by *user_id*.

    Accepts a chat UUID (``ChatSpec.id``) or a session id
    (``ChatSpec.session_id``).  Only chats owned by *user_id* match, so a
    user can never address another user's conversation.
    """
    if not target:
        return None
    chats = await mgr.list_chats(user_id=user_id)
    for chat in chats:
        if chat.id == target:
            return chat
    for chat in chats:
        if chat.session_id == target:
            return chat
    return None


async def _read_state(
    session: Any,
    session_id: str,
    user_id: str,
    channel: str,
) -> tuple[Any | None, dict]:
    """Read the persisted ``AgentState`` and mode state for one session.

    Best effort: returns ``(None, {})`` when the session has no persisted
    state (or reading fails), so callers degrade to an empty conversation.
    The mode-state dict mirrors the ``mode_state`` block persisted by the
    session save hook.
    """
    from agentscope.state import AgentState

    try:
        data = await session.get_session_state_dict(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "failed to read session state for session=%s",
            str(session_id)[:30],
            exc_info=True,
        )
        return None, {}
    agent = data.get("agent") or {}
    raw = agent.get("state")
    if raw is None:
        return None, {}
    try:
        state = AgentState.model_validate(raw)
    except Exception:  # noqa: BLE001
        logger.warning(
            "failed to parse session state for session=%s",
            str(session_id)[:30],
            exc_info=True,
        )
        return None, {}
    mode_state = agent.get("mode_state")
    return state, (dict(mode_state) if isinstance(mode_state, dict) else {})


async def _message_counts(
    session: Any,
    chats: list[Any],
) -> dict[str, int]:
    """Count persisted context messages for each chat (parallel, best
    effort)."""
    if session is None or not chats:
        return {}

    async def one(chat: Any) -> int:
        try:
            state, _mode = await _read_state(
                session,
                chat.session_id,
                chat.user_id,
                chat.channel,
            )
            if state is None:
                return 0
            return len(state.context or [])
        except Exception:  # noqa: BLE001
            return 0

    counts = await asyncio.gather(*[one(chat) for chat in chats])
    return {chat.id: count for chat, count in zip(chats, counts)}


def _render_list(
    chats: list[Any],
    *,
    current_session_id: str,
    counts: dict[str, int],
) -> str:
    """Render the ``/sessions`` listing as Markdown."""
    if not chats:
        return (
            "**No sessions found.**\n\n"
            "- Start a conversation to create your first session\n"
            "- Or use `/session new` to start a fresh one"
        )
    lines: list[str] = ["**Sessions** (most recent first):", ""]
    ordered = sorted(chats, key=lambda c: c.updated_at, reverse=True)
    for index, chat in enumerate(ordered, start=1):
        count = counts.get(chat.id, 0)
        marker = " ← current" if chat.session_id == current_session_id else ""
        archived = " [archived]" if chat.archived else ""
        lines.append(
            f"{index}. **{chat.name}**{marker}{archived} — "
            f"{count} msg · `{chat.channel}`\n"
            f"   id: `{chat.id}`",
        )
    return "\n".join(lines)


def _make_session_list_adapter() -> CommandSpec:
    """Build the ``/sessions`` command spec."""

    async def _handler(ctx: "HookContext", _args: str) -> Msg | None:
        workspace = getattr(ctx, "workspace", None)
        mgr = getattr(workspace, "chat_manager", None) if workspace else None
        if mgr is None:
            return _make_msg(
                "**Session list unavailable.**\n\n"
                "- Chat manager is not initialised for this workspace",
            )
        session = getattr(workspace, "session", None)
        user_id = _user_id(ctx)
        chats = await mgr.list_chats(user_id=user_id)
        counts = await _message_counts(session, chats)
        return _make_msg(
            _render_list(
                chats,
                current_session_id=ctx.session_id,
                counts=counts,
            ),
        )

    return CommandSpec(
        name="sessions",
        handler=_handler,
        category="session",
        help_text=_HELP_SESSIONS,
    )


async def _do_switch(
    ctx: "HookContext",
    workspace: Any,
    mgr: Any,
    session: Any,
    target: str,
) -> Msg:
    """Continue another conversation: load its context into this dialogue."""
    # Lazy imports avoid a module cycle: builtin_commands collects the
    # session specs while session_commands reuses its state plumbing.
    from ..builtin_commands import _load_agent_state, _save_agent_state

    user_id = _user_id(ctx)
    chat = await _resolve_target(mgr, target, user_id=user_id)
    if chat is None:
        return _make_msg(
            "**Switch failed — session not found.**\n\n"
            f"- No session matches `{target}` for the current user\n"
            "- Use `/sessions` to list available sessions\n"
            "- Usage: `/session switch <id>` (chat UUID or session id)",
        )

    # Safety point: switching replaces the current dialogue, so snapshot
    # it first (``pre-restore`` kind, like checkpoint restore's safety
    # points) so a mistaken switch can be rolled back via
    # ``/checkpoint restore``.  Failures are non-fatal — switching still
    # works when checkpoints are unavailable (e.g. Git missing).
    try:
        from qwenpaw.checkpoints.runtime import (
            RUNTIME as CHECKPOINT_RUNTIME,
        )

        engine = await CHECKPOINT_RUNTIME.get_for_workspace_async(workspace)
        await engine.make_snapshot(
            kind="pre-restore",
            session_id=ctx.session_id,
            user_id=user_id,
            channel=_channel(ctx),
            message="/session switch safety point",
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "failed to create switch safety point for session=%s",
            ctx.session_id[:30],
            exc_info=True,
        )

    target_state, target_mode = await _read_state(
        session,
        chat.session_id,
        chat.user_id,
        chat.channel,
    )
    target_context = list(target_state.context) if target_state else []
    target_summary = target_state.summary if target_state is not None else ""
    if isinstance(target_summary, list):
        target_summary = ""

    state, _payload = await _load_agent_state(ctx)
    # Replace the current dialogue with the target conversation.
    state.context.clear()
    state.context.extend(target_context)
    if hasattr(state, "summary"):
        state.summary = target_summary or ""
    # Carry the target's per-mode state (mission/coding/…) so the resumed
    # conversation continues in the same mode it was left in.
    ctx.mode_state = dict(target_mode)

    # ``/session switch`` behaves like /new and /clear w.r.t. the scroll
    # checkpoint: the window was replaced wholesale, so a stale eviction
    # index must not resurface old turns.  Pass ``None`` to reset it.
    await _save_agent_state(ctx, state, scroll_block=None)

    try:
        await mgr.touch_chat(chat.id)
    except Exception:  # noqa: BLE001
        logger.warning("failed to touch chat %s", chat.id, exc_info=True)

    return _make_msg(
        "**Switched to session.**\n\n"
        f"- Session: **{chat.name}** (`{chat.id}`)\n"
        f"- Channel: `{chat.channel}`\n"
        f"- Loaded {len(target_context)} message(s) into the current "
        "dialogue\n\n"
        "Note: on the web console, use the sidebar to switch chats so "
        "each conversation keeps its own history.  This command replaces "
        "the current dialogue with the target conversation.",
    )


async def _do_new(
    ctx: "HookContext",
    mgr: Any,
) -> Msg:
    """Start a fresh conversation: clear context and register a new chat."""
    from ..builtin_commands import _load_agent_state, _save_agent_state

    user_id = _user_id(ctx)
    channel = _channel(ctx)
    new_session_id = uuid4().hex
    try:
        await mgr.get_or_create_chat(
            new_session_id,
            user_id,
            channel,
            name="New Chat",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to register new chat")
        return _make_msg(
            "**New session failed.**\n\n" f"- Error: {exc}",
        )

    # Clear the current dialogue (mirrors the /new reset; the scroll
    # checkpoint and per-mode state are dropped because the window was
    # wiped).
    state, _payload = await _load_agent_state(ctx)
    state.context.clear()
    if hasattr(state, "summary"):
        state.summary = ""
    ctx.mode_state = {}
    await _save_agent_state(ctx, state, scroll_block=None)

    return _make_msg(
        "**New Session Started.**\n\n"
        f"- New session id: `{new_session_id}` "
        f"(channel: `{channel or 'default'}`)\n"
        "- Current context cleared — ready for a new conversation\n"
        "- Use `/session switch <id>` to continue an earlier session",
    )


async def _do_close(
    ctx: "HookContext",
    workspace: Any,
    mgr: Any,
    session: Any,
    target: str,
) -> Msg:
    """Delete a chat spec, its checkpoints and its persisted state."""
    from ..builtin_commands import _load_agent_state, _save_agent_state

    user_id = _user_id(ctx)
    chat = await _resolve_target(mgr, target, user_id=user_id)
    if chat is None:
        return _make_msg(
            "**Close failed — session not found.**\n\n"
            f"- No session matches `{target}` for the current user\n"
            "- Use `/sessions` to list available sessions\n"
            "- Usage: `/session close <id>` (chat UUID or session id)",
        )

    is_current = chat.session_id == ctx.session_id
    deleted = await mgr.delete_chats([chat.id])
    if not deleted:
        return _make_msg(
            "**Close failed.**\n\n" f"- Could not delete `{chat.id}`",
        )

    try:
        from qwenpaw.checkpoints.runtime import (
            RUNTIME as CHECKPOINT_RUNTIME,
        )

        await CHECKPOINT_RUNTIME.delete_session_checkpoints(
            workspace,
            [(chat.session_id, chat.user_id, chat.channel)],
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "failed to delete checkpoints for session=%s",
            chat.session_id[:30],
            exc_info=True,
        )

    if is_current:
        # Closing the conversation you are in: keep the file (the next
        # save would recreate it anyway) but reset the dialogue and
        # per-mode state.
        state, _payload = await _load_agent_state(ctx)
        state.context.clear()
        if hasattr(state, "summary"):
            state.summary = ""
        ctx.mode_state = {}
        await _save_agent_state(ctx, state, scroll_block=None)
        return _make_msg(
            "**Session closed.**\n\n"
            f"- Deleted: **{chat.name}** (`{chat.id}`)\n"
            "- Current context cleared — ready for a new conversation",
        )

    if session is not None and hasattr(session, "delete_session_state"):
        try:
            await session.delete_session_state(
                session_id=chat.session_id,
                user_id=chat.user_id,
                channel=chat.channel,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "failed to delete session state for session=%s",
                chat.session_id[:30],
                exc_info=True,
            )

    return _make_msg(
        "**Session closed.**\n\n"
        f"- Deleted: **{chat.name}** (`{chat.id}`)\n"
        f"- Channel: `{chat.channel}`",
    )


def _make_session_compound_adapter() -> CommandSpec:
    """Build the ``/session <sub>`` compound command spec."""

    async def _handler(ctx: "HookContext", args: str) -> Msg | None:
        workspace = getattr(ctx, "workspace", None)
        mgr = getattr(workspace, "chat_manager", None) if workspace else None
        session = getattr(workspace, "session", None) if workspace else None
        if mgr is None:
            return _make_msg(
                "**Session commands unavailable.**\n\n"
                "- Chat manager is not initialised for this workspace",
            )

        sub, _, target = args.strip().partition(" ")
        sub = sub.lower()
        if sub == "switch":
            return await _do_switch(ctx, workspace, mgr, session, target.strip())
        if sub == "new":
            return await _do_new(ctx, mgr)
        if sub == "close":
            return await _do_close(ctx, workspace, mgr, session, target.strip())
        return _make_msg(
            "**Usage: /session <subcommand>**\n\n"
            "- `/session switch <id>` — continue another conversation\n"
            "- `/session new` — clear context and start a fresh session\n"
            "- `/session close <id>` — delete a session\n"
            "- `/sessions` — list your sessions",
        )

    return CommandSpec(
        name="session",
        handler=_handler,
        category="session",
        help_text=_HELP_SESSION,
    )


def _collect_session_specs() -> list[CommandSpec]:
    """Return the session management command specs."""
    return [
        _make_session_list_adapter(),
        _make_session_compound_adapter(),
    ]


__all__ = ["_collect_session_specs"]
