# -*- coding: utf-8 -*-
"""MultiAgentManager: Manages multiple agent workspaces with lazy loading.

Provides centralized management for multiple Workspace objects,
including lazy loading, lifecycle management, and hot reloading.
"""

import asyncio
import logging
import time
from typing import Callable, Dict, Set

from qwenpaw.exceptions import (
    ConfigurationException,
)

from .agent_startup import (
    AgentStartupStatus,
)
from .workspace import Workspace
from ..constant import (
    BUILTIN_QA_AGENT_ID,
    CUSTOM_AGENT_STARTUP_CONCURRENCY,
)
from ..config.utils import load_config
from ..utils.startup_display import AgentStartupDisplay

logger = logging.getLogger(__name__)


class MultiAgentManager:
    """Manages multiple agent workspaces.

    Features:
    - Lazy loading: Workspaces are created only when first requested
    - Lifecycle management: Start, stop, reload workspaces
    - Thread-safe: Uses async lock for concurrent access
    - Hot reload: Reload individual workspaces without affecting others
    - Parallel startup: Multiple agents start concurrently via
      fine-grained locking (lock released during slow workspace init)
    """

    def __init__(self):
        """Initialize multi-agent manager."""
        self.agents: Dict[str, Workspace] = {}
        self._lock = asyncio.Lock()
        self._pending_starts: Dict[str, asyncio.Event] = {}
        self._agent_startup_statuses: Dict[str, AgentStartupStatus] = {}
        self._agent_startup_tasks: Dict[str, asyncio.Task[bool]] = {}
        self._custom_startup_semaphore = asyncio.Semaphore(
            CUSTOM_AGENT_STARTUP_CONCURRENCY,
        )
        self._cleanup_tasks: Set[asyncio.Task] = set()
        logger.debug("MultiAgentManager initialized")

    def _create_workspace(
        self,
        agent_id: str,
        workspace_dir: str,
    ) -> Workspace:
        """Factory method for workspace creation.

        Overridden by WorkspaceRegistry.
        """
        return Workspace(agent_id=agent_id, workspace_dir=workspace_dir)

    async def get_agent(self, agent_id: str) -> Workspace:
        """Get agent workspace by ID (lazy loading with dedup).

        If workspace doesn't exist in memory, it will be created and started.
        Multiple concurrent callers for the same agent_id are coordinated:
        the first caller creates the workspace while others wait.

        The lock is only held briefly for dict checks/mutations, not during
        the slow workspace startup, allowing parallel agent initialization.

        Args:
            agent_id: Agent ID to retrieve

        Returns:
            Workspace: The requested workspace instance

        Raises:
            ConfigurationException: If agent ID not found in configuration
        """
        await self._wait_for_scheduled_startup(agent_id)

        # Fast path: already loaded (no lock)
        if agent_id in self.agents:
            self._agent_startup_statuses[agent_id] = AgentStartupStatus.RUNNING
            logger.debug(f"Returning cached agent: {agent_id}")
            return self.agents[agent_id]

        should_start = False
        event = None
        agent_ref = None

        async with self._lock:
            # Re-check under lock
            if agent_id in self.agents:
                logger.debug(f"Returning cached agent: {agent_id}")
                return self.agents[agent_id]

            if agent_id in self._pending_starts:
                # Another task is already starting this agent; wait for it
                event = self._pending_starts[agent_id]
            else:
                # We are the first caller — validate config and claim startup
                config = load_config()
                if agent_id not in config.agents.profiles:
                    raise ConfigurationException(
                        config_key="agent",
                        message=(
                            f"Agent '{agent_id}' not found in configuration. "
                            f"Available agents: "
                            f"{list(config.agents.profiles.keys())}"
                        ),
                    )
                agent_ref = config.agents.profiles[agent_id]
                event = asyncio.Event()
                self._pending_starts[agent_id] = event
                self._agent_startup_statuses[
                    agent_id
                ] = AgentStartupStatus.STARTING
                should_start = True

        if not should_start:
            # Wait for the in-progress startup to finish
            await event.wait()
            if agent_id in self.agents:
                logger.debug(f"Returning cached agent: {agent_id}")
                return self.agents[agent_id]
            raise ConfigurationException(
                config_key="agent",
                message=f"Agent '{agent_id}' failed to initialize",
            )

        # We are the starter — create outside the lock for parallelism
        t0 = time.perf_counter()
        try:
            logger.debug(f"Creating new workspace: {agent_id}")
            instance = self._create_workspace(
                agent_id=agent_id,
                workspace_dir=agent_ref.workspace_dir,
            )
            await instance.start()
            instance.set_manager(self)

            async with self._lock:
                self.agents[agent_id] = instance

            elapsed = time.perf_counter() - t0
            logger.debug(
                f"Workspace created and started: {agent_id} "
                f"({elapsed:.3f}s)",
            )

            # Fire workspace_created hooks so plugins can provision
            # skills / config into the newly created workspace.
            await self._fire_workspace_created_hooks(
                {
                    "agent_id": agent_id,
                    "workspace_dir": str(agent_ref.workspace_dir),
                },
            )

            return instance
        except Exception as e:
            logger.error(f"Failed to start workspace {agent_id}: {e}")
            raise
        finally:
            # Always clean up pending state and signal waiters
            # This handles cancellation (CancelledError) and all other cases
            async with self._lock:
                self._pending_starts.pop(agent_id, None)
                if agent_id in self.agents:
                    self._agent_startup_statuses[
                        agent_id
                    ] = AgentStartupStatus.RUNNING
                elif self._agent_startup_statuses.get(agent_id) == (
                    AgentStartupStatus.STARTING
                ):
                    self._agent_startup_statuses[
                        agent_id
                    ] = AgentStartupStatus.FAILED
            event.set()

    @staticmethod
    async def _fire_workspace_created_hooks(workspace_info: dict) -> None:
        """Invoke all registered workspace_created hooks.

        Supports both sync and async callbacks:
        - Async callbacks are awaited directly.
        - Sync callbacks are offloaded to a thread via
          ``asyncio.to_thread`` so they never block the event loop.

        Errors in individual hooks are logged but do not prevent
        subsequent hooks from running.

        Args:
            workspace_info: Dict with at least ``agent_id`` and
                ``workspace_dir`` keys.
        """
        try:
            from ..plugins.registry import PluginRegistry

            hooks = PluginRegistry().get_workspace_created_hooks()
        except Exception:
            # Plugin system not initialised yet — nothing to do.
            return

        for hook in hooks:
            try:
                callback = hook.callback
                if asyncio.iscoroutinefunction(callback):
                    await callback(workspace_info)
                else:
                    result = await asyncio.to_thread(callback, workspace_info)
                    if asyncio.iscoroutine(result) or hasattr(
                        result,
                        "__await__",
                    ):
                        await result
            except Exception as exc:
                logger.error(
                    f"Error in workspace_created hook "
                    f"'{hook.hook_name}' for plugin "
                    f"'{hook.plugin_id}': {exc}",
                    exc_info=True,
                )

    async def _graceful_stop_old_instance(
        self,
        old_instance: Workspace,
        agent_id: str,
    ) -> None:
        """Gracefully stop old instance after checking for active tasks.

        If active tasks exist, schedule delayed cleanup in background.
        Otherwise, stop immediately.

        Args:
            old_instance: The old workspace instance to stop
            agent_id: Agent ID for logging
        """
        has_active = await old_instance.task_tracker.has_active_tasks()

        if has_active:
            # Active tasks - schedule delayed cleanup in background
            active_tasks = await old_instance.task_tracker.list_active_tasks()
            logger.info(
                f"Old workspace instance has {len(active_tasks)} active "
                f"task(s): {active_tasks}. Scheduling delayed cleanup for "
                f"{agent_id}.",
            )

            async def delayed_cleanup():
                """Wait for tasks to complete, then stop old instance."""
                try:
                    # Wait up to 1 minutes for tasks to complete
                    completed = await old_instance.task_tracker.wait_all_done(
                        timeout=60.0,
                    )
                    if completed:
                        logger.info(
                            f"All tasks completed for old instance "
                            f"{agent_id}. Stopping now.",
                        )
                    else:
                        logger.warning(
                            f"Timeout waiting for tasks to complete for "
                            f"{agent_id}. Forcing stop after 5 minutes.",
                        )

                    await old_instance.stop(final=False)
                    logger.info(
                        f"Old workspace instance stopped: {agent_id}. "
                        f"Delayed cleanup completed.",
                    )
                except Exception as e:
                    logger.warning(
                        f"Error during delayed cleanup for {agent_id}: {e}. "
                        f"New instance is serving requests.",
                    )

            # Create background task for delayed cleanup and track it
            cleanup_task = asyncio.create_task(delayed_cleanup())
            self._cleanup_tasks.add(cleanup_task)

            def _on_cleanup_done(task: asyncio.Task) -> None:
                """Remove task from tracking set and log errors."""
                self._cleanup_tasks.discard(task)
                if task.cancelled():
                    logger.info(
                        f"Delayed cleanup task for {agent_id} was cancelled.",
                    )
                    return
                exc = task.exception()
                if exc is not None:
                    logger.warning(
                        f"Error in delayed cleanup task for {agent_id}: "
                        f"{exc}.",
                    )

            cleanup_task.add_done_callback(_on_cleanup_done)
            logger.info(
                f"Zero-downtime reload completed: {agent_id}. "
                f"Old instance cleanup scheduled in background.",
            )
        else:
            # No active tasks - stop immediately
            logger.debug(
                f"No active tasks in old instance {agent_id}. "
                f"Stopping immediately.",
            )
            try:
                await old_instance.stop(final=False)
                logger.info(
                    f"Old workspace instance stopped: {agent_id}. "
                    f"Zero-downtime reload completed.",
                )
            except Exception as e:
                logger.warning(
                    f"Failed to stop old workspace instance for "
                    f"{agent_id}: {e}. "
                    f"New instance is active and serving requests.",
                )

    async def stop_agent(self, agent_id: str) -> bool:
        """Stop a specific agent instance.

        Args:
            agent_id: Agent ID to stop

        Returns:
            bool: True if agent was stopped, False if not running
        """
        async with self._lock:
            if agent_id not in self.agents:
                logger.warning(f"Agent not running: {agent_id}")
                return False

            instance = self.agents[agent_id]
            await instance.stop()
            del self.agents[agent_id]
            self._agent_startup_statuses[
                agent_id
            ] = AgentStartupStatus.DISABLED
            logger.info(f"Agent stopped and removed: {agent_id}")
            return True

    async def reload_agent(self, agent_id: str) -> bool:
        """Reload a specific agent instance with zero-downtime.

        This method performs a seamless reload by:
        1. Creating and fully starting a new workspace instance (no lock)
        2. Atomically replacing the old instance with the new one (with lock)
        3. Gracefully stopping the old instance (no lock):
           - If active tasks exist: schedule delayed cleanup in background
           - If no active tasks: stop immediately

        The lock is only held during the atomic swap to minimize blocking
        time for other agent operations.

        This ensures that:
        - New requests are immediately handled by the new instance
        - Ongoing SSE/streaming tasks continue uninterrupted
        - Other agents remain accessible during reload
        - The manager returns quickly without waiting for old tasks
        - Old instance is automatically cleaned up after tasks complete

        Args:
            agent_id: Agent ID to reload

        Returns:
            bool: True if agent was reloaded, False if not running
        """
        # Step 1: Check if agent exists (quick check with lock)
        async with self._lock:
            if agent_id not in self.agents:
                logger.debug(
                    f"Agent not running, will be loaded on next "
                    f"request: {agent_id}",
                )
                return False
            old_instance = self.agents[agent_id]

        logger.info(f"Reloading agent (zero-downtime): {agent_id}")

        # Step 1.5: Stop old config watcher (no-op if it triggered
        # this reload, since it already disabled itself).
        try:
            # pylint: disable=protected-access
            old_watcher = old_instance._service_manager.services.get(
                "agent_config_watcher",
            )
            # pylint: enable=protected-access
            if old_watcher is not None:
                await old_watcher.stop()
        except Exception as stop_err:
            logger.warning(
                f"Failed to stop old AgentConfigWatcher for "
                f"{agent_id}: {stop_err}.",
            )

        # Step 2: Load configuration (outside lock)
        config = load_config()
        if agent_id not in config.agents.profiles:
            logger.error(
                f"Agent '{agent_id}' not found in configuration "
                f"during reload",
            )
            return False

        agent_ref = config.agents.profiles[agent_id]

        # Step 3: Create and start new workspace instance (outside lock)
        # This is the slow part, but doesn't block other agents
        logger.info(f"Creating new workspace instance: {agent_id}")
        new_instance = self._create_workspace(
            agent_id=agent_id,
            workspace_dir=agent_ref.workspace_dir,
        )

        # Step 3.5: Set reusable components from old instance (if any)
        async with self._lock:
            old_instance = self.agents.get(agent_id)

        if old_instance:
            # Get all reusable services from old instance's ServiceManager
            # pylint: disable=protected-access
            reusable = old_instance._service_manager.get_reusable_services()
            # pylint: enable=protected-access

            if reusable:
                await new_instance.set_reusable_components(reusable)
                logger.info(
                    f"Set reusable components for {agent_id}: "
                    f"{list(reusable.keys())}",
                )

        try:
            await new_instance.start()
            new_instance.set_manager(self)  # Set manager reference
            logger.info(f"New workspace instance started: {agent_id}")
        except Exception as e:
            logger.exception(
                f"Failed to start new workspace instance for {agent_id}: {e}",
            )
            # Try to clean up the failed new instance
            try:
                await new_instance.stop()
            except Exception:
                pass  # Best effort cleanup
            # Old instance is still running and serving requests
            return False

        # Step 4: Atomic swap (minimal lock time)
        # From this point, reload is considered successful
        async with self._lock:
            # Double-check agent still exists
            if agent_id not in self.agents:
                logger.warning(
                    f"Agent {agent_id} was removed during reload, "
                    f"stopping new instance",
                )
                await new_instance.stop()
                return False

            # Swap instances atomically
            old_instance = self.agents[agent_id]
            self.agents[agent_id] = new_instance
            logger.info(f"Workspace instance replaced: {agent_id}")

        # Step 5: Gracefully stop old instance (outside lock)
        # Delegates to helper method to avoid too-many-statements
        await self._graceful_stop_old_instance(old_instance, agent_id)

        return True

    async def cancel_all_cleanup_tasks(self) -> None:
        """Cancel and await all pending delayed cleanup tasks.

        This ensures that any in-progress background cleanups are either
        completed or cleanly cancelled before the manager is torn down.
        Called by stop_all() during shutdown.
        """
        if not self._cleanup_tasks:
            return

        logger.info(
            f"Cancelling {len(self._cleanup_tasks)} pending cleanup "
            f"task(s)...",
        )
        tasks = list(self._cleanup_tasks)
        self._cleanup_tasks.clear()

        for task in tasks:
            if not task.done():
                task.cancel()

        # Await completion of all tasks, collecting exceptions
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("All cleanup tasks cancelled/completed")

    async def stop_all(self):
        """Stop all agent instances concurrently.

        Called during application shutdown to clean up resources.
        Cancels any pending delayed cleanup tasks and stops all
        agents in parallel via asyncio.gather.
        """
        logger.info(
            f"Stopping all agents ({len(self.agents)} running)...",
        )

        await self.cancel_all_startup_tasks()
        await self.cancel_all_cleanup_tasks()

        async def _stop_one(agent_id: str, instance: Workspace):
            try:
                await instance.stop()
                logger.debug(f"Agent stopped: {agent_id}")
            except Exception as e:
                logger.error(
                    f"Error stopping agent {agent_id}: {e}",
                )

        await asyncio.gather(
            *(_stop_one(aid, inst) for aid, inst in self.agents.items()),
        )

        self.agents.clear()
        logger.info("All agents stopped")

    def list_loaded_agents(self) -> list[str]:
        """List currently loaded agent IDs.

        Returns:
            list[str]: List of loaded agent IDs
        """
        return list(self.agents.keys())

    def is_agent_loaded(self, agent_id: str) -> bool:
        """Check if agent is currently loaded.

        Args:
            agent_id: Agent ID to check

        Returns:
            bool: True if agent is loaded and running
        """
        return agent_id in self.agents

    def get_agent_startup_status(
        self,
        agent_id: str,
        *,
        enabled: bool = True,
    ) -> AgentStartupStatus:
        """Return the current process-local startup status for an agent."""
        if not enabled:
            return AgentStartupStatus.DISABLED
        status = self._agent_startup_statuses.get(agent_id)
        if status is not None:
            return status
        if agent_id in self.agents:
            return AgentStartupStatus.RUNNING
        return AgentStartupStatus.PENDING

    def is_agent_startup_in_progress(self, agent_id: str) -> bool:
        """Return whether an agent is queued or actively starting."""
        return self._agent_startup_statuses.get(agent_id) in {
            AgentStartupStatus.PENDING,
            AgentStartupStatus.STARTING,
        }

    async def preload_agent(self, agent_id: str) -> bool:
        """Preload an agent instance during startup.

        Args:
            agent_id: Agent ID to preload

        Returns:
            bool: True if successfully preloaded, False if failed
        """
        try:
            await self.get_agent(agent_id)
            logger.info(f"Successfully preloaded agent: {agent_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to preload agent {agent_id}: {e}")
            return False

    async def _wait_for_scheduled_startup(self, agent_id: str) -> None:
        """Join an existing queued startup instead of bypassing its limit."""
        startup_task = self._agent_startup_tasks.get(agent_id)
        if (
            startup_task is None
            or startup_task is asyncio.current_task()
            or startup_task.done()
        ):
            return
        if not await startup_task:
            raise ConfigurationException(
                config_key="agent",
                message=f"Agent '{agent_id}' failed to initialize",
            )

    def schedule_agent_startup(self, agent_id: str) -> asyncio.Task[bool]:
        """Queue one custom agent through the shared startup limit."""
        existing_task = self._agent_startup_tasks.get(agent_id)
        if existing_task is not None and not existing_task.done():
            return existing_task

        if agent_id in self.agents:
            self._agent_startup_statuses[agent_id] = AgentStartupStatus.RUNNING
        else:
            self._agent_startup_statuses[agent_id] = AgentStartupStatus.PENDING

        task = asyncio.create_task(
            self._start_agent_with_limit(agent_id),
            name=f"agent-startup:{agent_id}",
        )
        self._agent_startup_tasks[agent_id] = task

        def discard(completed_task: asyncio.Task[bool]) -> None:
            if self._agent_startup_tasks.get(agent_id) is completed_task:
                self._agent_startup_tasks.pop(agent_id, None)

        task.add_done_callback(discard)
        return task

    async def _start_agent_with_limit(self, agent_id: str) -> bool:
        """Start one custom agent inside the process-wide startup bound."""
        if agent_id in self.agents:
            return True
        async with self._custom_startup_semaphore:
            return await self.preload_agent(agent_id)

    async def cancel_all_startup_tasks(self) -> None:
        """Cancel and await queued custom-agent startup tasks."""
        tasks = list(self._agent_startup_tasks.values())
        self._agent_startup_tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def start_all_configured_agents(
        self,
        on_core_ready: Callable[[dict[str, bool]], None] | None = None,
        startup_display: AgentStartupDisplay | None = None,
    ) -> dict[str, bool]:
        """Start core agents, then custom agents with bounded concurrency.

        Only agents with enabled=True will be started.
        Disabled agents are skipped to save resources.

        The default and built-in QA agents form the concurrent core phase.
        Remaining custom agents start only after that phase and are bounded
        by ``QWENPAW_CUSTOM_AGENT_STARTUP_CONCURRENCY``.

        Returns:
            dict[str, bool]: Mapping of agent_id to success status
        """
        config = load_config()
        # Filter only enabled agents
        enabled_agents = {
            agent_id: ref
            for agent_id, ref in config.agents.profiles.items()
            if getattr(ref, "enabled", True)
        }
        agent_ids = list(enabled_agents.keys())

        async with self._lock:
            for agent_id, ref in config.agents.profiles.items():
                enabled = getattr(ref, "enabled", True)
                if not enabled:
                    status = AgentStartupStatus.DISABLED
                elif agent_id in self.agents:
                    status = AgentStartupStatus.RUNNING
                elif agent_id in self._pending_starts:
                    status = AgentStartupStatus.STARTING
                else:
                    status = AgentStartupStatus.PENDING
                self._agent_startup_statuses[agent_id] = status

        if not agent_ids:
            logger.warning("No enabled agents configured in config")
            return {}

        total_agents = len(config.agents.profiles)
        disabled_count = total_agents - len(agent_ids)
        logger.debug(
            f"Starting {len(agent_ids)} enabled agent(s) "
            f"({disabled_count} disabled)",
        )

        async def start_single_agent(agent_id: str) -> tuple[str, bool]:
            """Start a single agent with error handling."""
            try:
                logger.debug(f"Starting agent: {agent_id}")
                await self.get_agent(agent_id)
                logger.debug(f"Agent started successfully: {agent_id}")
                return (agent_id, True)
            except Exception as e:
                logger.error(
                    f"Failed to start agent {agent_id}: {e}. "
                    f"Continuing with other agents...",
                )
                return (agent_id, False)

        core_agent_ids = [
            agent_id
            for agent_id in ("default", BUILTIN_QA_AGENT_ID)
            if agent_id in enabled_agents
        ]
        custom_agent_ids = [
            agent_id
            for agent_id in agent_ids
            if agent_id not in core_agent_ids
        ]

        core_results = await asyncio.gather(
            *(start_single_agent(agent_id) for agent_id in core_agent_ids),
            return_exceptions=False,
        )
        core_result_map = dict(core_results)

        if core_result_map.get("default") and on_core_ready is not None:
            try:
                on_core_ready(core_result_map)
            except Exception:
                logger.warning(
                    "Core-agent ready callback failed",
                    exc_info=True,
                )

        if startup_display is not None and custom_agent_ids:
            startup_display.start_custom_agents(len(custom_agent_ids))

        async def start_custom_agent(
            agent_id: str,
        ) -> tuple[str, bool]:
            """Start one custom agent inside the concurrency bound."""
            try:
                success = await self.schedule_agent_startup(agent_id)
                return (agent_id, success)
            finally:
                if startup_display is not None:
                    startup_display.advance(agent_id)

        custom_results = await asyncio.gather(
            *(start_custom_agent(agent_id) for agent_id in custom_agent_ids),
            return_exceptions=False,
        )

        results = [*core_results, *custom_results]

        # Build result mapping
        result_map = dict(results)
        success_count = sum(1 for success in result_map.values() if success)
        logger.info(
            f"Agent startup complete: {success_count}/{len(agent_ids)} "
            f"agents started successfully, {disabled_count} disabled",
        )

        return result_map

    def __repr__(self) -> str:
        """String representation of manager."""
        loaded = list(self.agents.keys())
        return f"MultiAgentManager(loaded_agents={loaded})"
