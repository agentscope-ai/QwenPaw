# -*- coding: utf-8 -*-
"""Agent State Management.

Defines agent states and provides state management utilities
for tracking agent availability and workload.
"""

from enum import Enum
from typing import Dict, Optional, Set
import asyncio
import logging

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Agent states for scheduling.

    State transitions:
    IDLE -> WORKING: When agent starts processing a task
    WORKING -> IDLE: When agent completes a task normally
    WORKING -> INTERRUPTED: When agent is interrupted by CRITICAL task
    INTERRUPTED -> WORKING: When agent starts processing interrupting task
    Any -> PAUSED: Manual pause
    PAUSED -> IDLE: Manual resume
    """

    IDLE = "idle"  # Agent is available for new tasks
    WORKING = "working"  # Agent is processing a task
    INTERRUPTED = "interrupted"  # Agent was interrupted, waiting to resume
    PAUSED = "paused"  # Agent is manually paused

    def __str__(self) -> str:
        """Return string representation."""
        return self.value

    def __repr__(self) -> str:
        """Return repr string."""
        return f"AgentState.{self.name}"


class AgentStateManager:
    """Manages agent states across multiple agents.

    Thread-safe state tracking with support for:
    - State queries and transitions
    - Finding idle/working agents
    - Agent registration and deregistration

    Example:
        >>> manager = AgentStateManager()
        >>> manager.register("agent-1")
        >>> manager.set_state("agent-1", AgentState.WORKING)
        >>> idle_agents = manager.find_idle_agents()
    """

    def __init__(self) -> None:
        """Initialize the state manager."""
        self._states: Dict[str, AgentState] = {}
        self._lock = asyncio.Lock()

    async def register(self, agent_id: str) -> None:
        """Register a new agent with IDLE state.

        Args:
            agent_id: Unique identifier for the agent.
        """
        async with self._lock:
            if agent_id in self._states:
                logger.warning(f"Agent {agent_id} already registered")
            self._states[agent_id] = AgentState.IDLE
            logger.debug(f"Registered agent {agent_id}")

    async def deregister(self, agent_id: str) -> None:
        """Remove an agent from tracking.

        Args:
            agent_id: Agent to remove.
        """
        async with self._lock:
            if agent_id in self._states:
                del self._states[agent_id]
                logger.debug(f"Deregistered agent {agent_id}")

    async def get_state(self, agent_id: str) -> Optional[AgentState]:
        """Get the current state of an agent.

        Args:
            agent_id: Agent to query.

        Returns:
            Current state or None if not registered.
        """
        async with self._lock:
            return self._states.get(agent_id)

    async def set_state(self, agent_id: str, state: AgentState) -> bool:
        """Set the state of an agent.

        Args:
            agent_id: Agent to update.
            state: New state to set.

        Returns:
            True if successful, False if agent not registered.
        """
        async with self._lock:
            if agent_id not in self._states:
                logger.warning(f"Cannot set state: agent {agent_id} not registered")
                return False
            old_state = self._states[agent_id]
            self._states[agent_id] = state
            logger.debug(f"Agent {agent_id}: {old_state} -> {state}")
            return True

    async def find_idle_agents(self) -> Set[str]:
        """Find all agents currently in IDLE state.

        Returns:
            Set of agent IDs that are idle.
        """
        async with self._lock:
            return {
                agent_id
                for agent_id, state in self._states.items()
                if state == AgentState.IDLE
            }

    async def find_working_agents(self) -> Set[str]:
        """Find all agents currently in WORKING state.

        Returns:
            Set of agent IDs that are working.
        """
        async with self._lock:
            return {
                agent_id
                for agent_id, state in self._states.items()
                if state == AgentState.WORKING
            }

    async def get_all_states(self) -> Dict[str, AgentState]:
        """Get a snapshot of all agent states.

        Returns:
            Dictionary mapping agent IDs to their states.
        """
        async with self._lock:
            return dict(self._states)

    @property
    def registered_count(self) -> int:
        """Return the number of registered agents."""
        return len(self._states)
