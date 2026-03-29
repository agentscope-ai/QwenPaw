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
        >>> scheduler.register_agent("agent-1", execute_func)
        >>> await scheduler.dispatch(message, MessagePriority.HIGH)
    """

    def __init__(self, max_queue_size: int = 1000) -> None:
        """Initialize the scheduler.

        Args:
            max_queue_size: Maximum pending tasks in queue.
        """
        self._queue = PriorityMessageQueue(maxsize=max_queue_size)
        self._state_manager = AgentStateManager()
        self._agent_executors: Dict[str, Callable] = {}
        self._paused_tasks: Dict[str, PausedTask] = {}  # agent_id -> paused task
        self._current_tasks: Dict[str, Task] = {}  # agent_id -> current task
        self._lock = asyncio.Lock()
        self._running = False
        self._dispatch_task: Optional[asyncio.Task] = None

    @property
    def queue_stats(self) -> Dict[str, int]:
        """Get current queue statistics."""
        stats = self._queue.get_stats()
        return {
            "critical": stats.critical,
            "high": stats.high,
            "normal": stats.normal,
            "low": stats.low,
            "total": stats.total,
        }

    @property
    def agent_states(self) -> Dict[str, str]:
        """Get all agent states."""
        return {
            aid: state.value
            for aid, state in asyncio.get_event_loop().run_until_complete(
                self._state_manager.get_all_states()
            )
        }

    async def register_agent(
        self,
        agent_id: str,
        execute_func: Callable[[Msg, Optional[Dict]], Any],
    ) -> None:
        """Register an agent with the scheduler.

        Args:
            agent_id: Unique identifier for the agent.
            execute_func: Async function to execute messages.
                         Signature: async def execute(msg: Msg, context: Optional[Dict]) -> Any
        """
        await self._state_manager.register(agent_id)
        self._agent_executors[agent_id] = execute_func
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
        task = await self._queue.put(message, priority)
        logger.info(
            f"Dispatched task {task.task_id} with priority {priority.name}"
        )

        # CRITICAL: Try immediate dispatch
        if priority == MessagePriority.CRITICAL:
            await self._handle_critical_task(task)
        else:
            # Try to find idle agent
            idle_agents = await self._state_manager.find_idle_agents()
            if idle_agents:
                agent_id = self._select_agent(idle_agents)
                await self._assign_task(agent_id, task)

        return task.task_id

    async def _handle_critical_task(self, task: Task) -> None:
        """Handle a CRITICAL priority task.

        Tries to find an idle agent first, then interrupts
        a working agent if necessary.

        Args:
            task: The CRITICAL task to handle.
        """
        # Try idle agents first
        idle_agents = await self._state_manager.find_idle_agents()
        if idle_agents:
            agent_id = self._select_agent(idle_agents)
            await self._assign_task(agent_id, task)
            return

        # No idle agents - must interrupt
        working_agents = await self._state_manager.find_working_agents()
        if working_agents:
            agent_id = self._select_agent(working_agents)
            await self._interrupt_agent(agent_id, task)
            return

        # No agents at all - queue
        logger.warning("No agents available for CRITICAL task, queuing")

    async def _interrupt_agent(self, agent_id: str, new_task: Task) -> None:
        """Interrupt an agent's current task for a CRITICAL task.

        Args:
            agent_id: Agent to interrupt.
            new_task: The interrupting CRITICAL task.
        """
        async with self._lock:
            current_task = self._current_tasks.get(agent_id)
            if not current_task:
                logger.warning(f"Agent {agent_id} has no task to interrupt")
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
        """Execute a task on an agent.

        Args:
            agent_id: Agent executing the task.
            task: Task to execute.
        """
        executor = self._agent_executors.get(agent_id)
        if not executor:
            logger.error(f"No executor for agent {agent_id}")
            await self._state_manager.set_state(agent_id, AgentState.IDLE)
            return

        try:
            logger.info(f"Agent {agent_id} executing task {task.task_id}")
            
            # Check for resume context
            context = None
            if task.metadata.get("resumed_from"):
                context = task.context

            result = await executor(task.message, context)
            logger.info(f"Agent {agent_id} completed task {task.task_id}")

        except Exception as e:
            logger.error(
                f"Agent {agent_id} failed task {task.task_id}: {e}",
                exc_info=True,
            )
        finally:
            async with self._lock:
                self._current_tasks.pop(agent_id, None)
            
            # Check for paused task to resume
            paused = self._paused_tasks.pop(agent_id, None)
            if paused and paused.can_resume:
                logger.info(
                    f"Resuming paused task for agent {agent_id}"
                )
                resume_task = paused.create_resume_task()
                await self._assign_task(agent_id, resume_task)
            else:
                # Check queue for more tasks
                try:
                    next_task = self._queue.get_nowait()
                    await self._assign_task(agent_id, next_task)
                except QueueEmpty:
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
            True if successful.
        """
        state = await self._state_manager.get_state(agent_id)
        if state == AgentState.WORKING:
            # Pause current task
            current = self._current_tasks.get(agent_id)
            if current:
                paused = PausedTask(original_task=current)
                paused.pause_reason = "manual_pause"
                self._paused_tasks[agent_id] = paused

        return await self._state_manager.set_state(agent_id, AgentState.PAUSED)

    async def resume_agent(self, agent_id: str) -> bool:
        """Resume a paused agent.

        Args:
            agent_id: Agent to resume.

        Returns:
            True if successful.
        """
        state = await self._state_manager.get_state(agent_id)
        if state != AgentState.PAUSED:
            return False

        # Check for paused task
        paused = self._paused_tasks.pop(agent_id, None)
        if paused and paused.can_resume:
            resume_task = paused.create_resume_task()
            await self._assign_task(agent_id, resume_task)
        else:
            await self._state_manager.set_state(agent_id, AgentState.IDLE)

        return True

    async def start(self) -> None:
        """Start the scheduler's background processing."""
        if self._running:
            return

        self._running = True
        self._dispatch_task = asyncio.create_task(self._process_queue())
        logger.info("AgentScheduler started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        logger.info("AgentScheduler stopped")

    async def _process_queue(self) -> None:
        """Background task to process queued messages."""
        while self._running:
            try:
                # Wait for message
                task = await self._queue.get(timeout=1.0)

                # Find idle agent
                idle_agents = await self._state_manager.find_idle_agents()
                if idle_agents:
                    agent_id = self._select_agent(idle_agents)
                    await self._assign_task(agent_id, task)
                else:
                    # Put back in queue - no idle agents
                    # This creates a busy-wait pattern, but queue ordering
                    # is preserved for same-priority items
                    self._queue.put_nowait(task.message, MessagePriority(task.priority))

            except QueueEmpty:
                # No messages, continue polling
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing queue: {e}", exc_info=True)
                await asyncio.sleep(0.1)
