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

from copaw.exceptions import SystemCommandException
from .base import BaseControlCommandHandler, ControlContext
from .model_handler import ModelCommandHandler
from .stop_handler import StopCommandHandler

logger = logging.getLogger(__name__)

# Global command registry: command_name → handler instance
_COMMAND_REGISTRY: Dict[str, BaseControlCommandHandler] = {}


def _register_defaults() -> None:
    """Register default control command handlers."""
    register_command(StopCommandHandler())
    register_command(ModelCommandHandler())


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
        Dict of parsed arguments with "_raw_args" key for raw arguments

    Example:
        parse_args("/stop session=console:user1", "/stop")
        → {"session": "console:user1", "_raw_args": "session=console:user1"}

        parse_args("/model openai:gpt-4o", "/model")
        → {"_raw_args": "openai:gpt-4o"}
    """
    args: Dict[str, Any] = {}

    # Remove command prefix
    args_str = query[len(command_prefix) :].strip()

    # Store raw arguments for handlers that need full text
    args["_raw_args"] = args_str

    if not args_str:
        return args

    # Parse key=value pairs
    parts = args_str.split()
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
    raise SystemCommandException(
        message=f"Unknown control command: {query}",
    )


# Register default handlers on module import
_register_defaults()


# Export public API
__all__ = [
    "BaseControlCommandHandler",
    "ControlContext",
    "ModelCommandHandler",
    "StopCommandHandler",
    "is_control_command",
    "handle_control_command",
    "register_command",
]
