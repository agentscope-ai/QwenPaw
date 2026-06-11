# -*- coding: utf-8 -*-
"""Unified command dispatch for stream_query.

Provides :func:`dispatch_command` — a single entry point that checks
all command categories (daemon, control, conversation, skill) in
priority order and returns the response text, or ``None`` to fall
through to the model.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, TYPE_CHECKING

from . import control_commands
from .control_commands.base import ControlContext
from .daemon_commands import (
    DaemonContext,
    DaemonCommandHandlerMixin,
    parse_daemon_query,
)
from ...agents.command_handler import CommandHandler
from ...config.config import load_agent_config

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agentscope.message import Msg
    from .runner import AgentRunner


async def dispatch_command(
    query: str | None,
    *,
    agent: Any,
    runner: Any,
    request: Any,
    msgs: list,
) -> "Msg | None":
    """Dispatch a slash command and return a response Msg, or None.

    Priority order: conversation > daemon > control > skill.
    If None is returned, the caller should proceed to reply_stream.
    If a Msg is returned, it should be yielded as a short-circuit response.

    For skill invocation with input (``/skill_name input``), the function
    rewrites ``msgs`` in-place and returns None so the model sees the
    skill-augmented prompt.
    """
    if not query or not query.startswith("/"):
        return None

    from agentscope.message import Msg, TextBlock

    # 1. Conversation commands (/compact, /new, /clear, etc.)
    cmd_handler = getattr(agent, "command_handler", None)
    if cmd_handler is not None and cmd_handler.is_command(query):
        return await cmd_handler.handle_command(query)

    # 2. Daemon commands (/restart, /status, /version, /logs)
    parsed = parse_daemon_query(query)
    if parsed is not None:
        msg = await _handle_daemon(runner, query, parsed)
        return msg

    # 3. Control commands (/skills, /stop, /model, /approval)
    if control_commands.is_control_command(query):
        text = await _handle_control(runner, query, request)
        if text is not None:
            return Msg(
                name=getattr(runner, "agent_name", "assistant"),
                role="assistant",
                content=[TextBlock(type="text", text=text)],
            )

    # 4. Skill dispatch (/skill_name [input])
    skill_text = _handle_skill(agent, query, msgs)
    if skill_text is not None:
        return Msg(
            name=getattr(agent, "name", "assistant"),
            role="assistant",
            content=[TextBlock(type="text", text=skill_text)],
        )

    # Not a command — fall through to model
    return None


async def _handle_daemon(
    runner: Any,
    query: str,
    parsed: tuple,
) -> "Msg":
    """Handle daemon commands."""

    handler = DaemonCommandHandlerMixin()
    agent_id = getattr(runner, "agent_id", None) or "default"
    daemon_ctx = DaemonContext(
        load_config_fn=lambda: load_agent_config(agent_id),
        memory_manager=getattr(runner, "memory_manager", None),
        context_manager=getattr(runner, "context_manager", None),
        manager=getattr(runner, "_manager", None),
        agent_id=agent_id,
        session_id="",
        agent_name=getattr(runner, "agent_name", "QwenPaw"),
    )
    msg = await handler.handle_daemon_command(query, daemon_ctx)
    if parsed[0] in ("reload-config", "restart"):
        invalidate = getattr(runner, "invalidate_agent_name_cache", None)
        if callable(invalidate):
            invalidate()
    return msg


async def _handle_control(
    runner: Any,
    query: str,
    request: Any,
) -> str | None:
    """Handle control commands. Returns response text or None."""
    workspace = getattr(runner, "_workspace", None)
    if workspace is None:
        logger.error(
            "control command but workspace not set: %s",
            query[:50],
        )
        return (
            "**Error**\n\n"
            "Control command unavailable (workspace not initialized)"
        )

    channel_mgr = getattr(workspace, "channel_manager", None)
    channel = None
    if channel_mgr is not None:
        channel_id = getattr(request, "channel", None) or "console"
        try:
            channel = await channel_mgr.get_channel(channel_id)
        except Exception:
            pass

    ctx = ControlContext(
        workspace=workspace,
        payload=request,
        channel=channel,
        session_id=getattr(request, "session_id", "") or "",
        user_id=getattr(request, "user_id", "") or "",
        agent_id=getattr(runner, "agent_id", "") or "",
        args={},
    )
    try:
        return await control_commands.handle_control_command(query, ctx)
    except Exception as e:
        logger.exception("Control command failed: %s", query)
        return f"**Command Failed**\n\n{e}"


# pylint: disable=too-many-return-statements
def _handle_skill(
    agent: Any,
    query: str,
    msgs: list,
) -> str | None:
    """Handle skill dispatch. Returns info text or None (rewrites msgs for
    invocation)."""
    from pathlib import Path

    import frontmatter as fm

    from ...agents.utils.file_handling import (
        read_text_file_with_encoding_fallback,
    )

    toolkit = getattr(agent, "toolkit", None)
    skills = getattr(toolkit, "_qp_skills", None) if toolkit else None
    if not skills:
        return None

    parsed = _parse_skill_query(query)
    if not parsed:
        return None
    name, user_input = parsed

    skill = next(
        (s for s in skills.values() if Path(s["dir"]).name.lower() == name),
        None,
    )
    if not skill:
        return None

    skill_dir = Path(skill["dir"])
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    raw = read_text_file_with_encoding_fallback(skill_md)
    post = fm.loads(raw)
    display_name = post.get("name") or name

    if not user_input:
        desc = post.get("description") or "No description."
        return (
            f"**{name}**\n\n"
            f"- **command**: `/{name} <input>` to invoke\n"
            f"- **name**: {display_name}\n"
            f"- **description**: {desc}\n"
            f"- **path**: `{skill_dir}`"
        )

    # Rewrite last message with skill body
    from agentscope.message import TextBlock as _TB

    merged = (
        f"Use the [{display_name}] skill in "
        f"`{skill_dir}` to fulfill "
        f"user's task: {user_input}\n\n"
        f"{post.content}"
    )
    if msgs:
        last = msgs[-1]
        content = getattr(last, "content", None)
        if isinstance(content, list):
            for i, block in enumerate(content):
                btype = (
                    block.get("type")
                    if isinstance(block, dict)
                    else getattr(block, "type", None)
                )
                if btype == "text":
                    content[i] = _TB(type="text", text=merged)
                    return None
            content.insert(0, _TB(type="text", text=merged))
        elif isinstance(content, str):
            last.content = merged
    return None


def _parse_skill_query(query: str) -> tuple[str, str] | None:
    """Parse ``/name [input]`` or ``/[name with spaces] [input]``."""
    stripped = query.strip()
    if not stripped.startswith("/"):
        return None
    rest = stripped[1:]
    if rest.startswith("["):
        close = rest.find("]")
        if close < 0:
            return None
        name = rest[1:close].strip().lower()
        user_input = rest[close + 1 :].strip()
        return (name, user_input) if name else None
    parts = rest.split(None, 1)
    if not parts:
        return None
    name = parts[0].lower()
    user_input = parts[1] if len(parts) > 1 else ""
    return (name, user_input) if name else None


# ---------------------------------------------------------------------------
# query_handler bridge (AgentRunner.query_handler in runner.py).
#
# The command path in ``AgentRunner.query_handler`` runs *before* the agent
# object is constructed, so it cannot hand an agent to ``dispatch_command``
# directly. ``run_command_path`` builds the agent the same way the live
# stream_query path does (via ``runtime.agent_factory.build_agent``) and
# bridges ``dispatch_command``'s ``Msg | None`` onto the ``(Msg, last)``
# async-iterator that ``query_handler`` expects.
# ---------------------------------------------------------------------------


def _get_last_user_text(msgs) -> str | None:
    """Extract last user message text from msgs (runtime message list)."""
    if not msgs or len(msgs) == 0:
        return None
    last = msgs[-1]
    if hasattr(last, "get_text_content"):
        return last.get_text_content()
    if isinstance(last, dict):
        content = last.get("content") or last.get("text")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text")
    return None


def _is_conversation_command(query: str | None) -> bool:
    """True if query is a conversation command (/compact, /new, etc.).

    ``/plan <description>`` (with arguments) is NOT a command — it passes
    through the runner to activate plan mode.
    """
    if not query or not query.startswith("/"):
        return False
    stripped = query.strip().lstrip("/")
    parts = stripped.split(" ", 1)
    cmd = parts[0] if parts else ""
    if cmd == "plan" and len(parts) > 1 and parts[1].strip():
        return False
    return cmd in CommandHandler.SYSTEM_COMMANDS


def _is_control_command(query: str | None) -> bool:
    """True if query is a control command (/stop, /approval, etc.)."""
    return control_commands.is_control_command(query)


def _is_command(query: str | None) -> bool:
    """True if query is any known command.

    Priority order: daemon > control > conversation. ``/plan <description>``
    (with arguments) is NOT a command — it passes through to the runner to
    activate plan mode.
    """
    if not query or not query.startswith("/"):
        return False
    if parse_daemon_query(query) is not None:
        return True
    if _is_control_command(query):
        return True
    return _is_conversation_command(query)


async def run_command_path(
    request,
    msgs,
    runner: "AgentRunner",
) -> AsyncIterator[tuple]:
    """Run command path and yield ``(msg, last)`` for each response.

    Thin adapter over :func:`dispatch_command`. It obtains an agent the same
    way the live stream_query path does (builds via
    ``runtime.agent_factory.build_agent`` and loads persisted session state),
    then bridges ``dispatch_command``'s ``Msg | None`` onto the ``(Msg, bool)``
    stream that ``AgentRunner.query_handler`` consumes.

    Args:
        request: AgentRequest (session_id, user_id, channel, etc.)
        msgs: List of messages from runtime (last is user input)
        runner: AgentRunner (session, memory_manager, context_manager, etc.)

    Yields:
        ``(Msg, bool)`` compatible with ``query_handler`` stream.
    """
    query = _get_last_user_text(msgs)
    if not query:
        return

    from agentscope.message import Msg, TextBlock

    session_id = getattr(request, "session_id", "") or ""
    user_id = getattr(request, "user_id", "") or ""
    channel = getattr(request, "channel", "") or ""

    # Daemon-restart hint: yield first so the user sees it before the
    # restart actually runs (parity with the 1.x command path).
    parsed = parse_daemon_query(query)
    if parsed is not None and parsed[0] == "restart":
        yield (
            Msg(
                name=runner.agent_name,
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "**Restart in progress**\n\n"
                            "- Reloading agent with zero-downtime. "
                            "Please wait."
                        ),
                    ),
                ],
            ),
            True,
        )

    # Build the agent the same way the live query path does: with MCP
    # clients (so /skill and control commands see the same tools) and the
    # request_context payload.
    from ...runtime.agent_factory import build_agent

    mcp_clients = None
    mcp_mgr = getattr(runner, "_mcp_manager", None)
    if mcp_mgr is not None:
        try:
            mcp_clients = await mcp_mgr.get_clients()
        except Exception:
            logger.debug(
                "run_command_path: failed to get MCP clients",
                exc_info=True,
            )

    request_context: dict[str, str] = {
        "session_id": session_id,
        "user_id": user_id,
        "channel": channel,
        "agent_id": runner.agent_id,
    }
    payload_context = getattr(request, "request_context", None)
    if isinstance(payload_context, dict):
        request_context.update(payload_context)

    agent = build_agent(
        session_id,
        agent_id=runner.agent_id,
        workspace_dir=runner.workspace_dir,
        mcp_clients=mcp_clients or None,
        request_context=request_context,
        memory_manager=runner.memory_manager,
        context_manager=runner.context_manager,
    )

    # Load persisted session state (needed by conversation commands that
    # touch memory, e.g. /compact, /new, /clear).
    session = getattr(runner, "session", None)
    if session is not None:
        try:
            await session.load_session_state(
                session_id=session_id,
                user_id=user_id or session_id,
                channel=channel,
                agent=agent,
            )
        except KeyError as e:
            logger.debug(
                "run_command_path: session load skipped "
                "(schema mismatch): %s",
                e,
            )
        except Exception:
            logger.debug(
                "run_command_path: session load failed",
                exc_info=True,
            )

    msg = await dispatch_command(
        query,
        agent=agent,
        runner=runner,
        request=request,
        msgs=msgs,
    )
    if msg is not None:
        yield msg, True
