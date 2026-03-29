# -*- coding: utf-8 -*-
"""Agent Scheduler Module - Priority-based message queue and scheduling.

This module provides a priority-based message queue and scheduling system
for agents, supporting:
- Message priority levels (CRITICAL, HIGH, NORMAL, LOW)
- Agent state management (IDLE, WORKING, INTERRUPTED, PAUSED)
- Task interruption and resumption
- Multi-agent scheduling with workload balancing

Example:
    >>> from copaw.agents.scheduler import AgentScheduler, MessagePriority
    >>> scheduler = AgentScheduler()
    >>> await scheduler.dispatch(message, MessagePriority.HIGH)
"""

from .priority import MessagePriority
from .queue import PriorityMessageQueue
from .state import AgentState, AgentStateManager
from .scheduler import AgentScheduler
from .task import Task, PausedTask

__all__ = [
    "MessagePriority",
    "PriorityMessageQueue",
    "AgentState",
    "AgentStateManager",
    "AgentScheduler",
    "Task",
    "PausedTask",
]
