# -*- coding: utf-8 -*-
"""Base classes for control command handlers.

Control commands are high-priority commands like /stop that require
immediate response and special handling outside the normal agent flow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from ...channels.base import BaseChannel
    from ...workspace import Workspace


@dataclass
class ControlContext:
    """Context for control command execution.

    Attributes:
        workspace: Current workspace instance (for task_tracker, etc.)
        payload: Original message payload (native dict or AgentRequest)
        channel: Channel instance
        session_id: Normalized session ID (e.g. "console:user1")
        user_id: User ID from request
        args: Parsed command arguments (command-specific)
    """

    workspace: "Workspace"
    payload: Any
    channel: "BaseChannel"
    session_id: str
    user_id: str
    args: Dict[str, Any]


class BaseControlCommandHandler(ABC):
    """Abstract base class for control command handlers.

    Subclasses implement specific commands (e.g. /stop, /pause).

    Example:
        class StopCommandHandler(BaseControlCommandHandler):
            command_name = "/stop"

            async def handle(self, context: ControlContext) -> str:
                # Implementation
                return "Task stopped"
    """

    command_name: str = ""

    @abstractmethod
    async def handle(self, context: ControlContext) -> str:
        """Handle the control command.

        Args:
            context: Control command context

        Returns:
            Response text to send to user

        Raises:
            Exception: If command execution fails
        """
        raise NotImplementedError
