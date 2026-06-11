# -*- coding: utf-8 -*-
"""Unified command dispatch for stream_query.

Provides :func:`dispatch_command` — a single entry point that checks
all command categories (daemon, control, conversation, skill) in
priority order and returns the response text, or ``None`` to fall
through to the model.
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from . import control_commands
from .control_commands.base import ControlContext
from .daemon_commands import (
    DaemonContext,
    DaemonCommandHandlerMixin,
    parse_daemon_query,
)
from ...config.config import load_agent_config

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agentscope.message import Msg


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
