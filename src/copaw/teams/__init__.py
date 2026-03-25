# -*- coding: utf-8 -*-
"""Agent Teams package for CoPaw.

Provides multi-agent collaboration through shared task boards,
mailbox communication, and team lifecycle management.
"""

from .task_board import TaskBoard, TeamTask
from .mailbox import Mailbox, AgentMessage
from .team_manager import TeamManager
from .relationships import RelationshipStore

__all__ = [
    "TaskBoard",
    "TeamTask",
    "Mailbox",
    "AgentMessage",
    "TeamManager",
    "RelationshipStore",
]
