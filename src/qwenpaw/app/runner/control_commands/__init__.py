# -*- coding: utf-8 -*-
"""Control commands module.

Provides centralized command registration and dispatch for control commands
like /stop that require immediate response and special handling.

Usage:
    # Check if a query is a control command
    if is_control_command(query):
        response = await handle_control_command(query, context)

    # Register new control command
    register_command(MyCustomHandler())
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from qwenpaw.exceptions import SystemCommandException
from .base import BaseControlCommandHandler, ControlContext
from .approval_handler import (
    ApprovalCommandHandler,
    ApproveCommandHandler,
    DenyCommandHandler,
)
from .model_handler import ModelCommandHandler
from .skills_handler import SkillsCommandHandler
from .stop_handler import StopCommandHandler

logger = logging.getLogger(__name__)

# Global command registry: command_name → handler instance
_COMMAND_REGISTRY: Dict[str, BaseControlCommandHandler] = {}


def _register_defaults() -> None:
    """Register default control command handlers."""
    register_command(ApprovalCommandHandler())
    register_command(ApproveCommandHandler())
    register_command(DenyCommandHandler())
    register_command(StopCommandHandler())
    register_command(ModelCommandHandler())
    register_command(SkillsCommandHandler())


def register_command(handler: BaseControlCommandHandler) -> None:
    """Register a control command handler.

    Args:
        handler: Command handler instance

    Raises:
        ValueError: If command_name is empty or already registered
    """
    if not handler.command_name:
        raise ValueError(
            f"Handler {handler.__class__.__name__} has empty command_name",
        )

    command = handler.command_name.lower()

    if command in _COMMAND_REGISTRY:
        logger.warning(
            f"Overriding existing handler for command: {command}",
        )

    _COMMAND_REGISTRY[command] = handler
    logger.debug(
        f"Registered control command: {command} "
        f"→ {handler.__class__.__name__}",
    )


def _extract_command_token(query: str | None) -> str | None:
    """Extract the command token from a query string.

    Returns the first word (e.g. ``"/stop"`` from ``"/stop session=123"``),
    or ``None`` if query is empty or not a slash command.
    """
    if not query or not isinstance(query, str):
        return None
    parts = query.strip().lower().split(None, 1)
    return parts[0] if parts else None


def is_control_command(query: str | None) -> bool:
    """Check if query is a registered control command.

    Args:
        query: User query text

    Returns:
        True if query matches a registered control command

    Example:
        is_control_command("/stop") → True
        is_control_command("/stop session=123") → True
        is_control_command("hello") → False
    """
    return _extract_command_token(query) in _COMMAND_REGISTRY


def parse_args(query: str, command_prefix: str) -> Dict[str, Any]:
    """Parse command arguments from query.

    Args:
        query: Full query text (e.g. "/stop session=123")
        command_prefix: Command prefix (e.g. "/stop")

    Returns:
        Dict of parsed arguments with "_raw_args" key for raw arguments

    Example:
        parse_args("/stop session=console:user1", "/stop")
        → {"session": "console:user1", "_raw_args": "session=console:user1"}

        parse_args("/model openai:gpt-4o", "/model")
        → {"_raw_args": "openai:gpt-4o"}

        parse_args("/approval approve abc123", "/approval")
        → {"action": "approve", "request_id": "abc123",
           "_raw_args": "approve abc123"}

        parse_args("/approval deny abc123 wrong params", "/approval")
        → {"action": "deny", "request_id": "abc123",
           "reason": "wrong params", "_raw_args": "deny abc123 wrong params"}
    """
    args: Dict[str, Any] = {}

    # Remove command prefix
    args_str = query[len(command_prefix) :].strip()

    # Store raw arguments for handlers that need full text
    args["_raw_args"] = args_str

    if not args_str:
        return args

    # Split args into parts
    parts = args_str.split()

    # Special parsing for /approval command
    if command_prefix.lower() == "/approval" and parts:
        # First part is action (approve/deny/list/cancel)
        args["action"] = parts[0].lower()

        # Parse flags for list command (--all / -a)
        if args["action"] == "list" and len(parts) > 1:
            for part in parts[1:]:
                if part in ("--all", "-a"):
                    args["all"] = True

        # Second part (if exists) is request_id
        if len(parts) > 1 and not parts[1].startswith("-"):
            args["request_id"] = parts[1]

        # Remaining parts (for deny) are reason
        if len(parts) > 2 and args["action"] == "deny":
            args["reason"] = " ".join(parts[2:])

        return args

    # Default parsing: key=value pairs
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            args[key.strip()] = value.strip()

    return args


async def handle_control_command(
    query: str,
    context: ControlContext,
) -> str:
    """Dispatch control command to appropriate handler.

    Args:
        query: User query (e.g. "/stop session=123")
        context: Control command context

    Returns:
        Response text from handler

    Raises:
        ValueError: If command not found (should not happen
                    if is_control_command() was checked first)
    """
    token = _extract_command_token(query)
    if token is None:
        raise ValueError(f"Unknown control command: {query}")
    handler = _COMMAND_REGISTRY.get(token)
    if handler is None:
        raise ValueError(f"Unknown control command: {query}")

    args = parse_args(query, token)
    context.args = args

    logger.info(
        f"Handling control command: {token} args={args}",
    )

    try:
        return await handler.handle(context)
    except Exception as e:
        logger.exception(
            f"Control command failed: {token}",
        )
        return f"**Command Failed**\n\n{str(e)}"


# Register default handlers on module import
_register_defaults()


# Export public API
__all__ = [
    "ApprovalCommandHandler",
    "ApproveCommandHandler",
    "BaseControlCommandHandler",
    "ControlContext",
    "DenyCommandHandler",
    "ModelCommandHandler",
    "SkillsCommandHandler",
    "StopCommandHandler",
    "is_control_command",
    "handle_control_command",
    "register_command",
]
