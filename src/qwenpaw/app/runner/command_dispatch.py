# -*- coding: utf-8 -*-
"""Command dispatch: run command path without creating QwenPawAgent.

Yields (Msg, last) compatible with query_handler stream.
"""
from __future__ import annotations

import copy
import logging
from typing import Any, AsyncIterator, TYPE_CHECKING

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
from ...config.config import load_agent_config, save_agent_config

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .runner import AgentRunner


async def ensure_plan_mode_enabled(runner: "AgentRunner") -> bool:
    """Persist ``plan.enabled`` if needed and attach a ``PlanNotebook``.

    Returns ``True`` when ``runner.plan_notebook`` is non-``None``.
    """
    workspace = getattr(runner, "_workspace", None)
    if workspace is None:
        return False

    agent_id = runner.agent_id
    agent_config = load_agent_config(agent_id)

    if not agent_config.plan.enabled:
        agent_config.plan.enabled = True
        save_agent_config(agent_id, agent_config)
        workspace._config = agent_config  # pylint: disable=protected-access
        if not await workspace.activate_plan_notebook():
            return False
    elif runner.plan_notebook is None:
        await workspace.activate_plan_notebook()

    return runner.plan_notebook is not None


async def handle_bare_plan_command(runner: "AgentRunner") -> Msg:
    """Enable plan mode if needed and return plan status for bare ``/plan``."""
    workspace = getattr(runner, "_workspace", None)
    if workspace is None:
        return Msg(
            name="Friday",
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "**Plan**\n\n"
                        "Plan command is unavailable "
                        "(workspace not initialized)."
                    ),
                ),
            ],
        )

    if not await ensure_plan_mode_enabled(runner):
        return Msg(
            name="Friday",
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "**Plan**\n\n"
                        "Could not enable plan mode "
                        "(check AgentScope plan support and logs)."
                    ),
                ),
            ],
        )

    nb = runner.plan_notebook
    if nb is None:
        return Msg(
            name="Friday",
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "**Plan**\n\n"
                        "Plan mode is enabled but no plan notebook is "
                        "available on this runner."
                    ),
                ),
            ],
        )

    if nb.current_plan is None:
        body = (
            "**Plan mode is on.**\n\n"
            "- No active plan yet.\n"
            "- Use `/plan <description>` to have the agent create a plan, "
            "or use the Plan panel in the console.\n"
        )
    else:
        from ...plan.schemas import plan_to_response

        p = plan_to_response(nb.current_plan)
        lines = [
            "**Current plan**",
            f"- **{p.name}** (state: `{p.state}`)",
        ]
        if p.description:
            desc = p.description
            if len(desc) > 280:
                desc = desc[:277] + "..."
            lines.append(f"- {desc}")
        lines.append("")
        lines.append("**Subtasks:**")
        for st in p.subtasks:
            lines.append(f"  - [{st.state}] {st.name}")
        body = "\n".join(lines)

    return Msg(
        name="Friday",
        role="assistant",
        content=[TextBlock(type="text", text=body)],
    )


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


def is_bare_plan_command(query: str | None) -> bool:
    """True for exactly ``/plan`` (optional surrounding whitespace)."""
    if not query or not isinstance(query, str):
        return False
    return query.strip().lower() == "/plan"


def is_plan_with_inline_description(query: str | None) -> bool:
    """True when the message is the ``/plan`` command word plus description.

    Requires whitespace after ``/plan`` so paths like ``/planning`` are not
    mistaken for ``/plan <desc>``.
    """
    if not query or not isinstance(query, str):
        return False
    parts = query.strip().split(None, 1)
    if len(parts) < 2:
        return False
    if parts[0].lower() != "/plan":
        return False
    return bool(parts[1].strip())


def plan_inline_description(query: str) -> str:
    """Return text after ``/plan`` (caller must ensure inline form)."""
    parts = query.strip().split(None, 1)
    if len(parts) < 2 or parts[0].lower() != "/plan":
        return ""
    return parts[1].strip()


PLAN_REQUEST_USER_PREFIX = (
    "[Plan request] Using the plan tools, create a structured plan for "
    "the following task, then present it to the user and wait for ONE "
    "confirmation. Once the user confirms, start executing immediately "
    "without asking again:\n\n"
)


def wrap_plan_request_user_text(description: str) -> str:
    """Turn raw task text into an explicit plan-creation user message."""
    return f"{PLAN_REQUEST_USER_PREFIX}{description.strip()}"


def _set_message_text_content(last: Any, new_text: str) -> Any:
    """Clone *last* message with plain text content replaced by *new_text*."""
    if hasattr(last, "to_dict"):
        payload = last.to_dict()
        payload["content"] = [{"type": "text", "text": new_text}]
        return Msg.from_dict(payload)
    if isinstance(last, dict):
        d = copy.deepcopy(last)
        content = d.get("content")
        if isinstance(content, list):
            replaced = False
            new_blocks = []
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and not replaced
                ):
                    new_blocks.append({**block, "text": new_text})
                    replaced = True
                else:
                    new_blocks.append(copy.deepcopy(block))
            d["content"] = (
                new_blocks
                if replaced
                else [
                    {"type": "text", "text": new_text},
                ]
            )
        elif isinstance(content, str):
            d["content"] = new_text
        else:
            d["content"] = [{"type": "text", "text": new_text}]
        return d
    return last


def rewrite_msgs_strip_plan_prefix(msgs: list[Any]) -> list[Any]:
    """Replace ``/plan <desc>`` on the last user turn with wrapped *desc*."""
    if not msgs:
        return msgs
    query = _get_last_user_text(msgs)
    if not query or not is_plan_with_inline_description(query):
        return msgs
    inner = plan_inline_description(query)
    new_text = wrap_plan_request_user_text(inner)
    out = list(msgs)
    out[-1] = _set_message_text_content(out[-1], new_text)
    return out


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

    Priority order: daemon > control > bare /plan > conversation

    ``/plan <text>`` is **not** a command: it is rewritten to a normal
    user message and handled by the agent (see ``query_handler``).
    """
    if not query or not query.startswith("/"):
        return False
    if parse_daemon_query(query) is not None:
        return True
    if _is_control_command(query):
        return True
    if is_plan_with_inline_description(query):
        return False
    if is_bare_plan_command(query):
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
            manager=manager,
            agent_id=agent_id,
            session_id=session_id,
        )
        msg = await handler.handle_daemon_command(query, daemon_ctx)
        yield msg, True
        logger.info("handle_daemon_command %s completed", query)
        return

    # Control command path (e.g. /stop)
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

    if is_bare_plan_command(query):
        plan_msg = await handle_bare_plan_command(runner)
        yield plan_msg, True
        return

    # Conversation path: lightweight memory + CommandHandler
    memory = runner.memory_manager.get_in_memory_memory()
    session_state = await runner.session.get_session_state_dict(
        session_id=session_id,
        user_id=user_id,
    )
    memory_state = session_state.get("agent", {}).get("memory", {})
    memory.load_state_dict(memory_state, strict=False)

    conv_handler = CommandHandler(
        agent_name="Friday",
        memory=memory,
        memory_manager=runner.memory_manager,
        enable_memory_manager=runner.memory_manager is not None,
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
