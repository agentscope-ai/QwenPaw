# -*- coding: utf-8 -*-
"""Command dispatch: run command path without creating CoPawAgent.

Yields (Msg, last) compatible with query_handler stream.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import AsyncIterator
from typing import TYPE_CHECKING

from agentscope.message import Msg, TextBlock

from . import control_commands
from .daemon_commands import (
    DaemonContext,
    DaemonCommandHandlerMixin,
    parse_daemon_query,
)
from ...agents.command_handler import CommandHandler
from ...agents.knowledge.service import KnowledgeImportService
from ...config.config import load_agent_config
from ...constant import WORKING_DIR
from ..channels.utils import file_url_to_local_path

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .runner import AgentRunner


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


def _is_kb_command(query: str | None) -> bool:
    """True if query starts with /kb command namespace."""
    if not query or not query.startswith("/"):
        return False
    token = query.strip().split()[0].lower() if query.strip() else ""
    return token == "/kb"


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
    if _is_kb_command(query):
        return True
    return _is_conversation_command(query)


def _extract_kb_command_action(query: str) -> str:
    """Parse /kb command action.

    Returns:
        "import" for supported actions.
        "invalid" for unsupported subcommands.
    """
    parts = [p.strip().lower() for p in query.strip().split() if p.strip()]
    if len(parts) == 1:
        return "import"
    if len(parts) == 2 and parts[1] == "import":
        return "import"
    return "invalid"


def _extract_local_files_for_kb(
    request,
    *,
    media_root: Path,
) -> list[Path]:
    """Extract local attachment paths from request input content."""
    safe_media_root = media_root.expanduser().resolve()
    attachments: list[Path] = []
    seen_paths: set[str] = set()
    inputs = getattr(request, "input", None) or []
    if not inputs:
        return attachments

    message = inputs[-1]
    contents = getattr(message, "content", None) or []
    for part in contents:
        if isinstance(part, dict):
            ptype = str(part.get("type") or "").lower()
            file_url = part.get("file_url")
        else:
            ptype = str(getattr(part, "type", "")).lower()
            file_url = getattr(part, "file_url", None)
        if ptype != "file" or not isinstance(file_url, str):
            continue

        local_path = file_url_to_local_path(file_url)
        if not local_path:
            continue
        path = Path(local_path).expanduser().resolve()
        try:
            path.relative_to(safe_media_root)
        except ValueError:
            logger.warning(
                "skip non-media attachment in /kb import: %s (media_root=%s)",
                path,
                safe_media_root,
            )
            continue

        path_key = str(path)
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        attachments.append(path)
    return attachments


def _format_kb_import_summary(response) -> str:
    """Build markdown summary text for KB import command result."""
    header = "**Knowledge Import Complete**"
    lines = [
        header,
        "",
        f"- Requested: {response.requested}",
        f"- Imported: {response.imported_count}",
        f"- Skipped: {response.skipped_count}",
        f"- Failed: {response.failed_count}",
    ]
    if response.failed_count > 0 and response.failed:
        first_failed = response.failed[0]
        lines.extend(
            [
                "",
                f"- First failure: `{first_failed.file_name}`",
                f"  `{first_failed.code}`: {first_failed.message}",
            ],
        )
    return "\n".join(lines)


async def _handle_kb_command(
    query: str,
    request,
    runner: AgentRunner,
) -> Msg | None:
    """Handle `/kb` command namespace and return a response message."""
    if not _is_kb_command(query):
        return None

    action = _extract_kb_command_action(query)
    if action == "invalid":
        return Msg(
            name="Friday",
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text=("**Usage**\n\n" "- `/kb`\n" "- `/kb import`"),
                ),
            ],
        )

    del action  # reserved for future subcommands
    workspace_dir = Path(runner.workspace_dir or WORKING_DIR).expanduser()
    media_root = workspace_dir / "media"
    workspace = getattr(runner, "_workspace", None)
    if workspace is not None:
        channel_manager = getattr(workspace, "channel_manager", None)
        channel_id = getattr(request, "channel", None) or "console"
        if channel_manager is not None:
            channel = await channel_manager.get_channel(channel_id)
            if channel is not None:
                channel_media_dir = getattr(channel, "media_dir", None)
                if channel_media_dir is not None:
                    media_root = Path(channel_media_dir).expanduser()

    local_files = _extract_local_files_for_kb(
        request,
        media_root=media_root,
    )
    if not local_files:
        return Msg(
            name="Friday",
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "**Knowledge Import**\n\n"
                        "- No importable file attachments found in "
                        "this message (media directory only)."
                    ),
                ),
            ],
        )

    service = KnowledgeImportService(workspace_dir)
    response = await service.import_local_files(local_files)
    logger.info(
        "kb import completed: requested=%s imported=%s failed=%s",
        response.requested,
        response.imported_count,
        response.failed_count,
    )
    return Msg(
        name="Friday",
        role="assistant",
        content=[
            TextBlock(
                type="text",
                text=_format_kb_import_summary(response),
            ),
        ],
    )


async def _handle_control_command(
    query: str,
    request,
    runner: AgentRunner,
    session_id: str,
    user_id: str,
) -> Msg | None:
    """Handle control command path (/stop, etc.).

    Return the generated response message when matched.
    """
    if not _is_control_command(query):
        return None

    workspace = runner._workspace  # pylint: disable=protected-access
    if workspace is None:
        logger.error(
            "run_command_path: control command but workspace not set",
        )
        return Msg(
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

    channel_id = getattr(request, "channel", "")
    channel = None
    channel_manager = workspace.channel_manager
    if channel_manager is not None:
        channel = await channel_manager.get_channel(channel_id)

    if channel is None:
        logger.error(
            "run_command_path: channel not found: %s",
            channel_id,
        )
        return Msg(
            name="Friday",
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text=f"**Error**\n\nChannel not found: {channel_id}",
                ),
            ],
        )

    control_ctx = control_commands.ControlContext(
        workspace=workspace,
        payload=request,
        channel=channel,
        session_id=session_id,
        user_id=user_id,
        args={},
    )

    try:
        response_text = await control_commands.handle_control_command(
            query,
            control_ctx,
        )
        logger.info("handle_control_command %s completed", query)
        return Msg(
            name="Friday",
            role="assistant",
            content=[TextBlock(type="text", text=response_text)],
        )
    except Exception as e:
        logger.exception(
            "Control command failed: %s",
            query,
        )
        return Msg(
            name="Friday",
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text=f"**Command Failed**\n\n{str(e)}",
                ),
            ],
        )


async def run_command_path(  # pylint: disable=too-many-statements
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

    kb_msg = await _handle_kb_command(query, request, runner)
    if kb_msg is not None:
        yield kb_msg, True
        return

    control_msg = await _handle_control_command(
        query=query,
        request=request,
        runner=runner,
        session_id=session_id,
        user_id=user_id,
    )
    if control_msg is not None:
        yield control_msg, True
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
    except RuntimeError as e:
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
