# -*- coding: utf-8 -*-
"""Agent Scheduler - Priority-based task scheduling for agents.

Implements a scheduler that:
- Dispatches tasks to available agents
- Manages agent states
- Supports task interruption for CRITICAL priority
- Supports task resumption after interruption
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Set

from agentscope.message import Msg

from .priority import MessagePriority
from .queue import PriorityMessageQueue, QueueEmpty
from .state import AgentState, AgentStateManager
from .task import PausedTask, Task

logger = logging.getLogger(__name__)


class AgentScheduler:
    """Priority-based agent scheduler.

    Manages task dispatch to agents with priority support:
    - CRITICAL tasks interrupt running tasks
    - HIGH tasks queue at front
    - NORMAL tasks use standard FIFO
    - LOW tasks run only when system is idle

    Example:
        >>> scheduler = AgentScheduler()
        >>> await scheduler.register_agent("agent_1", agent_executor)
        >>> task_id = await scheduler.dispatch(msg, MessagePriority.HIGH)
    """

    def __init__(self) -> None:
        """Initialize the scheduler."""
        self._state_manager = AgentStateManager()
        self._queue = PriorityMessageQueue()
        self._agent_executors: Dict[str, Callable] = {}
        self._current_tasks: Dict[str, Task] = {}
        self._paused_tasks: Dict[str, PausedTask] = {}
        self._lock = asyncio.Lock()
        self._running = True

    def get_queue_stats(self) -> Dict[str, int]:
        """Get current queue statistics.

        Returns:
            Dictionary with counts per priority level.
        """
        stats = self._queue.get_stats()
        return {
            "critical": stats.critical,
            "high": stats.high,
            "normal": stats.normal,
            "low": stats.low,
            "total": stats.total,
        }

    async def get_agent_states(self) -> Dict[str, str]:
        """Get all agent states (async version).

        Returns:
            Dictionary mapping agent IDs to their state values.
        """
        all_states = await self._state_manager.get_all_states()
        return {
            aid: state.value
            for aid, state in all_states.items()
        }

    async def register_agent(
        self,
        agent_id: str,
        executor: Callable[[Msg], Any],
    ) -> None:
        """Register an agent with the scheduler.

        Args:
            agent_id: Unique identifier for the agent.
            executor: Async function to execute messages.
        """
        await self._state_manager.register(agent_id)
        self._agent_executors[agent_id] = executor
        logger.info(f"Registered agent: {agent_id}")

    async def deregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the scheduler.

        Args:
            agent_id: Agent to remove.
        """
        await self._state_manager.deregister(agent_id)
        self._agent_executors.pop(agent_id, None)
        self._paused_tasks.pop(agent_id, None)
        self._current_tasks.pop(agent_id, None)
        logger.info(f"Deregistered agent: {agent_id}")

    async def dispatch(
        self,
        message: Msg,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> str:
        """Dispatch a message to an agent.

        For CRITICAL priority:
        1. If idle agent exists, execute immediately
        2. Otherwise, interrupt a working agent

        For other priorities:
        1. If idle agent exists, execute immediately
        2. Otherwise, queue the message

        Args:
            message: Message to dispatch.
            priority: Message priority level.

        Returns:
            Task ID for tracking.
        """
        task = Task(message=message, priority=int(priority))
        logger.info(
            f"Dispatching task {task.task_id} with priority {priority.name}"
        )

        # CRITICAL: Try immediate dispatch or interrupt
        if priority == MessagePriority.CRITICAL:
            idle_agents = await self._state_manager.find_idle_agents()
            if idle_agents:
                agent_id = self._select_agent(idle_agents)
                await self._assign_task(agent_id, task)
                return task.task_id

            # No idle agents - try to interrupt a working agent
            working_agents = await self._state_manager.find_working_agents()
            if working_agents:
                agent_id = self._select_agent(working_agents)
                await self._interrupt_agent(agent_id, task)
                return task.task_id

            # No agents available at all - queue for later (don't drop critical task)
            await self._queue.put_task(task)
            logger.warning(
                f"No agents available for CRITICAL task {task.task_id}, queued"
            )
            return task.task_id

        # Non-CRITICAL: Try idle agents first, then queue
        idle_agents = await self._state_manager.find_idle_agents()
        if idle_agents:
            agent_id = self._select_agent(idle_agents)
            await self._assign_task(agent_id, task)
            return task.task_id

        # No idle agents - queue for later (do NOT assign directly)
        await self._queue.put_task(task)
        logger.info(f"Queued task {task.task_id}, no idle agents")
        return task.task_id

    async def _interrupt_agent(
        self, agent_id: str, new_task: Task
    ) -> None:
        """Interrupt a running agent with a CRITICAL task.

        Args:
            agent_id: Agent to interrupt.
            new_task: CRITICAL task to assign.
        """
        async with self._lock:
            current_task = self._current_tasks.get(agent_id)
            if not current_task:
                # Task finished, just assign new one
                await self._assign_task(agent_id, new_task)
                return

            # Create paused task
            paused = PausedTask(original_task=current_task)
            self._paused_tasks[agent_id] = paused

            # Update states
            await self._state_manager.set_state(agent_id, AgentState.INTERRUPTED)

            logger.info(
                f"Interrupting agent {agent_id} task {current_task.task_id} "
                f"for CRITICAL task {new_task.task_id}"
            )

            # Assign new task
            await self._assign_task(agent_id, new_task)

    async def _assign_task(self, agent_id: str, task: Task) -> None:
        """Assign a task to an agent.

        Args:
            agent_id: Agent to receive the task.
            task: Task to assign.
        """
        async with self._lock:
            self._current_tasks[agent_id] = task
            await self._state_manager.set_state(agent_id, AgentState.WORKING)

        # Execute asynchronously
        asyncio.create_task(self._execute_task(agent_id, task))

    async def _execute_task(self, agent_id: str, task: Task) -> None:
        """Execute a task and handle completion.

        Args:
            agent_id: Agent executing the task.
            task: Task to execute.
        """
        executor = self._agent_executors.get(agent_id)
        if not executor:
            logger.error(f"No executor for agent {agent_id}")
            return

        try:
            await executor(task.message)
            logger.info(f"Task {task.task_id} completed by {agent_id}")
        except Exception as e:
            logger.error(
                f"Task {task.task_id} failed on {agent_id}: {e}"
            )
        finally:
            await self._task_completed(agent_id)

    async def _task_completed(self, agent_id: str) -> None:
        """Handle task completion, potentially resume paused task.

        Args:
            agent_id: Agent that completed a task.
        """
        async with self._lock:
            # Clear current task
            self._current_tasks.pop(agent_id, None)

            # Check for paused task to resume
            paused = self._paused_tasks.pop(agent_id, None)

            # Check for queued tasks first (respect priority)
            try:
                next_task = await self._queue.get_nowait_async()
                await self._assign_task(agent_id, next_task)
            except QueueEmpty:
                # No queued tasks
                if paused:
                    # Resume paused task
                    await self._assign_task(agent_id, paused.original_task)
                else:
                    # No more work
                    await self._state_manager.set_state(agent_id, AgentState.IDLE)

    def _select_agent(self, agent_ids: Set[str]) -> str:
        """Select an agent from a set of candidates.

        Uses simple round-robin selection. Override for smarter policies.

        Args:
            agent_ids: Set of candidate agent IDs.

        Returns:
            Selected agent ID.
        """
        # Simple selection - could implement load balancing here
        return next(iter(agent_ids))

    async def get_agent_state(self, agent_id: str) -> Optional[AgentState]:
        """Get the current state of an agent.

        Args:
            agent_id: Agent to query.

        Returns:
            Current state or None if not registered.
        """
        return await self._state_manager.get_state(agent_id)

    async def pause_agent(self, agent_id: str) -> bool:
        """Manually pause an agent.

        Args:
            agent_id: Agent to pause.

        Returns:
            True if paused, False if already paused or not found.
        """
        return await self._state_manager.set_state(
            agent_id, AgentState.PAUSED
        )

    async def resume_agent(self, agent_id: str) -> bool:
        """Resume a paused agent.

        Args:
            agent_id: Agent to resume.

        Returns:
            True if resumed, False if not paused.
        """
        state = await self._state_manager.get_state(agent_id)
        if state != AgentState.PAUSED:
            return False

        await self._state_manager.set_state(agent_id, AgentState.IDLE)

        # Try to assign queued work
        try:
            task = await self._queue.get_nowait_async()
            await self._assign_task(agent_id, task)
        except QueueEmpty:
            pass

        return True

    async def get_paused_task(self, agent_id: str) -> Optional[PausedTask]:
        """Get the paused task for an agent.

        Args:
            agent_id: Agent to query.

        Returns:
            PausedTask if exists, None otherwise.
        """
        return self._paused_tasks.get(agent_id)

    async def get_current_task(self, agent_id: str) -> Optional[Task]:
        """Get the current task for an agent.

        Args:
            agent_id: Agent to query.

        Returns:
            Current Task if exists, None otherwise.
        """
        return self._current_tasks.get(agent_id)

    async def shutdown(self) -> None:
        """Gracefully shutdown the scheduler."""
        self._running = False
        logger.info("Scheduler shutdown initiated")

    async def process_queued_tasks(self) -> None:
        """Process any queued tasks if idle agents available.

        This method can be called periodically to ensure
        queued tasks get dispatched when agents become idle.
        """
        idle_agents = await self._state_manager.find_idle_agents()
        if not idle_agents:
            return

        for agent_id in idle_agents:
            try:
                task = await self._queue.get_nowait_async()
                await self._assign_task(agent_id, task)
                logger.info(
                    f"Dispatched queued task {task.task_id} to idle agent {agent_id}"
                )
            except QueueEmpty:
                break

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running
