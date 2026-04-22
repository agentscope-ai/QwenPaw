# -*- coding: utf-8 -*-
"""Command dispatch: run command path without creating QwenPawAgent.

Yields (Msg, last) compatible with query_handler stream.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator
from typing import TYPE_CHECKING

from agentscope.message import Msg, TextBlock

from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
)

from . import control_commands
from .daemon_commands import (
    DaemonContext,
    DaemonCommandHandlerMixin,
    parse_daemon_query,
)
from ...agents.command_handler import CommandHandler
from ...config.config import load_agent_config

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .runner import AgentRunner
    from ...agents.context import AgentContext


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
    """True if query is a conversation command (/compact, /new, etc.)."""
    if not query or not query.startswith("/"):
        return False
    stripped = query.strip().lstrip("/")
    cmd = stripped.split(" ", 1)[0] if stripped else ""
    return cmd in CommandHandler.SYSTEM_COMMANDS


def _is_control_command(query: str | None) -> bool:
    """True if query is a control command (/stop, etc.)."""
    return control_commands.is_control_command(query)


def _is_command(query: str | None) -> bool:
    """True if query is any known command.

    Priority order: daemon > control > conversation
    """
    if not query or not query.startswith("/"):
        return False
    if parse_daemon_query(query) is not None:
        return True
    if _is_control_command(query):
        return True
    return _is_conversation_command(query)


async def run_command_path(  # pylint: disable=too-many-statements,too-many-branches  # noqa: E501
    request,
    msgs,
    runner: AgentRunner,
) -> AsyncIterator[tuple]:
    """Run command path and yield (msg, last) for each response.

    Args:
        request: AgentRequest (session_id, user_id, etc.)
        msgs: List of messages from runtime (last is user input)
        runner: AgentRunner (session, memory_manager, etc.)

    Yields:
        (Msg, bool) compatible with query_handler stream
    """
    query = _get_last_user_text(msgs)
    if not query:
        return

    session_id = getattr(request, "session_id", "") or ""
    user_id = getattr(request, "user_id", "") or ""

    # Daemon path
    parsed = parse_daemon_query(query)
    if parsed is not None:
        handler = DaemonCommandHandlerMixin()
        manager = getattr(runner, "_manager", None)
        if parsed[0] == "restart":
            logger.info(
                "run_command_path: daemon restart, manager=%s",
                "set" if manager is not None else "None",
            )
            # Yield hint first so user sees it before restart runs.
            hint = Msg(
                name="Friday",
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
            )
            yield hint, True

        agent_id = runner.agent_id
        daemon_ctx = DaemonContext(
            load_config_fn=lambda: load_agent_config(agent_id),
            memory_manager=runner.memory_manager,
            context_manager=runner.context_manager,
            manager=manager,
            agent_id=agent_id,
            session_id=session_id,
        )
        msg = await handler.handle_daemon_command(query, daemon_ctx)
        yield msg, True
        logger.info("handle_daemon_command %s completed", query)
        return

    # Control command path (e.g. /stop, /approval)
    if _is_control_command(query):
        workspace = runner._workspace  # pylint: disable=protected-access
        if workspace is None:
            logger.error(
                "run_command_path: control command but workspace not set",
            )
            error_msg = Msg(
                name="Friday",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "**Error**\n\n"
                            "Control command unavailable "
                            "(workspace not initialized)"
                        ),
                    ),
                ],
            )
            yield error_msg, True
            return

        # Get channel instance from request
        channel_id = getattr(request, "channel", "")
        channel = None

        # Get channel_manager from workspace
        channel_manager = workspace.channel_manager
        if channel_manager is not None:
            channel = await channel_manager.get_channel(channel_id)

        if channel is None:
            logger.error(
                f"run_command_path: channel not found: {channel_id}",
            )
            error_msg = Msg(
                name="Friday",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=f"**Error**\n\nChannel not found: {channel_id}",
                    ),
                ],
            )
            yield error_msg, True
            return

        # Extract user_id from request
        user_id = getattr(request, "user_id", "")

        # Build control context
        control_ctx = control_commands.ControlContext(
            workspace=workspace,
            payload=request,
            channel=channel,
            session_id=session_id,
            user_id=user_id,
            args={},
        )

        # Handle control command
        try:
            response_text = await control_commands.handle_control_command(
                query,
                control_ctx,
            )
            response_msg = Msg(
                name="Friday",
                role="assistant",
                content=[TextBlock(type="text", text=response_text)],
            )
            yield response_msg, True
            logger.info("handle_control_command %s completed", query)
        except Exception as e:
            if isinstance(e, (ValueError, AppBaseException)):
                logger.warning("Control command failed: %s – %s", query, e)
            else:
                logger.exception("Control command unexpected error: %s", query)
            error_msg = Msg(
                name="Friday",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=f"**Command Failed**\n\n{str(e)}",
                    ),
                ],
            )
            yield error_msg, True
        return

    # Conversation path: lightweight memory + CommandHandler
    context_manager = runner.context_manager
    memory: "AgentContext" = context_manager.get_agent_context()
    session_state = await runner.session.get_session_state_dict(
        session_id=session_id,
        user_id=user_id,
    )
    memory_state = session_state.get("agent", {}).get("memory", {})
    if memory is not None:
        memory.load_state_dict(memory_state, strict=False)

    conv_handler = CommandHandler(
        agent_name="Friday",
        memory=memory,
        memory_manager=runner.memory_manager,
        context_manager=context_manager,
    )
    try:
        response_msg = await conv_handler.handle_conversation_command(query)
    except (RuntimeError, AppBaseException) as e:
        response_msg = Msg(
            name="Friday",
            role="assistant",
            content=[TextBlock(type="text", text=str(e))],
        )
    yield response_msg, True

    # Update memory key with session_id & user_id to session,
    # but only if identifiers are present
    if session_id and user_id:
        await runner.session.update_session_state(
            session_id=session_id,
            key="agent.memory",
            value=memory.state_dict(),
            user_id=user_id,
        )
    else:
        logger.warning(
            "Skipping session_state update for conversation"
            " memory due to missing session_id or user_id (session_id=%r, "
            "user_id=%r)",
            session_id,
            user_id,
        )
