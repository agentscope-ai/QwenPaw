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
from ...config.config import load_agent_config
from ..channels.schema import DEFAULT_CHANNEL
from ...plan.broadcast import plan_sse_scope
from ...plan.session_sync import (
    broadcast_plan_notebook_snapshot,
    clear_plan_notebook_if_session_has_no_snapshot,
    persist_plan_notebook_to_session,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .runner import AgentRunner


async def ensure_plan_mode_enabled(runner: "AgentRunner") -> bool:
    """True when plan mode is enabled in config and a notebook exists.

    Does not flip ``plan.enabled`` on disk; users enable in Agent Settings.
    """
    workspace = getattr(runner, "_workspace", None)
    if workspace is None:
        return False

    agent_id = runner.agent_id
    agent_config = load_agent_config(agent_id)

    if not agent_config.plan.enabled:
        return False

    if runner.plan_notebook is None:
        if not await workspace.activate_plan_notebook():
            return False

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
                        "Plan mode is disabled. Enable it in Agent Settings "
                        "(Planning), then try again."
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

    _raw_channel = getattr(request, "channel", None)
    scope_channel = (
        _raw_channel
        if isinstance(_raw_channel, str) and _raw_channel.strip()
        else DEFAULT_CHANNEL
    )
    with plan_sse_scope(scope_channel, session_id):
        plan_nb = getattr(runner, "plan_notebook", None)
        sess = getattr(runner, "session", None)
        if session_id and sess is not None:
            await clear_plan_notebook_if_session_has_no_snapshot(
                session=sess,
                plan_notebook=plan_nb,
                session_id=session_id,
                user_id=user_id,
                agent_id=runner.agent_id,
            )
            if plan_nb is not None:
                try:
                    await sess.load_session_state(
                        session_id=session_id,
                        user_id=user_id,
                        plan_notebook=plan_nb,
                    )
                except KeyError as e:
                    logger.warning(
                        "run_command_path: load_session_state(plan_notebook) "
                        "skipped (schema mismatch): %s",
                        e,
                    )
                broadcast_plan_notebook_snapshot(plan_nb, runner.agent_id)

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
                chan_err = f"**Error**\n\nChannel not found: {channel_id}"
                error_msg = Msg(
                    name="Friday",
                    role="assistant",
                    content=[
                        TextBlock(
                            type="text",
                            text=chan_err,
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
                    logger.warning(
                        "Control command failed: %s – %s",
                        query,
                        e,
                    )
                else:
                    logger.exception(
                        "Control command unexpected error: %s",
                        query,
                    )
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
            plan_notebook=getattr(runner, "plan_notebook", None),
            agent_id=runner.agent_id,
        )
        try:
            response_msg = await conv_handler.handle_conversation_command(
                query,
            )
        except (RuntimeError, AppBaseException) as e:
            response_msg = Msg(
                name="Friday",
                role="assistant",
                content=[TextBlock(type="text", text=str(e))],
            )
        yield response_msg, True

        # Persist memory + plan when session_id is set (user_id may be empty;
        # must match SafeJSONSession filename rules, same as HTTP plan).
        if session_id:
            await runner.session.update_session_state(
                session_id=session_id,
                key="agent.memory",
                value=memory.state_dict(),
                user_id=user_id,
            )
            try:
                await persist_plan_notebook_to_session(
                    session=runner.session,
                    plan_notebook=getattr(runner, "plan_notebook", None),
                    session_id=session_id,
                    user_id=user_id,
                )
            except Exception:
                logger.warning(
                    "Failed to persist plan_notebook after "
                    "conversation command",
                    exc_info=True,
                )
        else:
            logger.warning(
                "Skipping session_state update for conversation"
                " memory due to missing session_id (user_id=%r)",
                user_id,
            )
