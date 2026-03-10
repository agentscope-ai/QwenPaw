# -*- coding: utf-8 -*-
"""Command dispatch: run command path without creating CoPawAgent.

Yields (Msg, last) compatible with query_handler stream.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from agentscope.message import Msg, TextBlock
from reme.memory.file_based.reme_in_memory_memory import ReMeInMemoryMemory

from .daemon_commands import (
    DaemonContext,
    DaemonCommandHandlerMixin,
    parse_daemon_query,
)
from ...agents.command_handler import CommandHandler
from ...agents.utils.token_counting import _get_token_counter
from ...config import load_config

logger = logging.getLogger(__name__)


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
    cmd = query.strip().lstrip("/").split()[0] if query.strip() else ""
    return cmd in CommandHandler.SYSTEM_COMMANDS


def _is_command(query: str | None) -> bool:
    """True if query is any known command (daemon or conversation)."""
    if not query or not query.startswith("/"):
        return False
    if parse_daemon_query(query) is not None:
        return True
    return _is_conversation_command(query)


class _LightweightSessionAgent:
    """Minimal agent-like object for session load/save (memory only)."""

    def __init__(self, memory: ReMeInMemoryMemory) -> None:
        self.memory = memory

    def state_dict(self) -> dict:
        return {"memory": self.memory.state_dict()}

    def load_state_dict(self, state_dict: dict, strict: bool = True) -> None:
        mem = state_dict.get("memory", state_dict)
        self.memory.load_state_dict(mem, strict=strict)


async def run_command_path(
    request,
    msgs,
    runner,
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
        restart_cb = getattr(runner, "_restart_callback", None)
        if parsed[0] == "restart":
            logger.info(
                "run_command_path: daemon restart, callback=%s",
                "set" if restart_cb is not None else "None",
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
                            "- The service may be unresponsive for a while. "
                            "Please wait."
                        ),
                    ),
                ],
            )
            yield hint, True
        context = DaemonContext(
            load_config_fn=load_config,
            memory_manager=runner.memory_manager,
            restart_callback=restart_cb,
        )
        msg = await handler.handle_daemon_command(query, context)
        yield msg, True
        logger.info("handle_daemon_command %s completed", query)
        return

    # Conversation path: lightweight memory + CommandHandler
    memory = ReMeInMemoryMemory(token_counter=_get_token_counter())
    light = _LightweightSessionAgent(memory=memory)
    if session_id and user_id:
        try:
            await runner.session.load_session_state(
                session_id=session_id,
                user_id=user_id,
                agent=light,
            )
        except ValueError:
            pass  # No session file yet

    conv_handler = CommandHandler(
        agent_name="Friday",
        memory=light.memory,
        memory_manager=runner.memory_manager,
        enable_memory_manager=runner.memory_manager is not None,
    )
    try:
        response_msg = await conv_handler.handle_conversation_command(query)
    except RuntimeError as e:
        response_msg = Msg(
            name="Friday",
            role="assistant",
            content=[TextBlock(type="text", text=str(e))],
        )
    yield response_msg, True

    if session_id and user_id:
        await runner.session.save_session_state(
            session_id=session_id,
            user_id=user_id,
            agent=light,
        )
