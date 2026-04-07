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

from .base import BaseControlCommandHandler, ControlContext
from .stop_handler import StopCommandHandler
from .undo_handler import UndoCommandHandler
from .redo_handler import RedoCommandHandler

logger = logging.getLogger(__name__)

# Global command registry: command_name → handler instance
_COMMAND_REGISTRY: Dict[str, BaseControlCommandHandler] = {}


def _register_defaults() -> None:
    """Register default control command handlers."""
    register_command(StopCommandHandler())
    register_command(UndoCommandHandler())
    register_command(RedoCommandHandler())


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
    logger.info(
        f"Registered control command: {command} "
        f"→ {handler.__class__.__name__}",
    )


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
    if not query or not isinstance(query, str):
        return False

    query_lower = query.strip().lower()

    # Check each registered command prefix
    for command_prefix in _COMMAND_REGISTRY:
        if query_lower.startswith(command_prefix):
            return True

    return False


def parse_args(query: str, command_prefix: str) -> Dict[str, Any]:
    """Parse command arguments from query.

    Args:
        query: Full query text (e.g. "/stop session=123")
        command_prefix: Command prefix (e.g. "/stop")

    Returns:
        Dict of parsed arguments

    Example:
        parse_args("/stop session=console:user1", "/stop")
        → {"session": "console:user1"}

        parse_args("/stop user=123 force=true", "/stop")
        → {"user": "123", "force": "true"}
    """
    args: Dict[str, Any] = {}

    # Remove command prefix
    args_str = query[len(command_prefix) :].strip()

    if not args_str:
        return args

    # Parse key=value pairs
    parts = args_str.split()
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            args[key.strip()] = value.strip()
        else:
            # Positional argument (future extension)
            pass

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
    query_lower = query.strip().lower()

    # Find matching handler
    for command_prefix, handler in _COMMAND_REGISTRY.items():
        if query_lower.startswith(command_prefix):
            # Parse arguments
            args = parse_args(query, command_prefix)
            context.args = args

            logger.info(
                f"Handling control command: {command_prefix} " f"args={args}",
            )

            # Execute handler
            try:
                response = await handler.handle(context)
                return response
            except Exception as e:
                logger.exception(
                    f"Control command failed: {command_prefix}",
                )
                return f"**Command Failed**\n\n{str(e)}"

    # Should not reach here if is_control_command() was checked
    raise ValueError(f"Unknown control command: {query}")


# Register default handlers on module import
_register_defaults()


# Export public API
__all__ = [
    "BaseControlCommandHandler",
    "ControlContext",
    "StopCommandHandler",
    "UndoCommandHandler",
    "RedoCommandHandler",
    "is_control_command",
    "handle_control_command",
    "register_command",
]
