# -*- coding: utf-8 -*-
"""MultiAgentManager: Manages multiple agent workspaces with lazy loading.

Provides centralized management for multiple Workspace objects,
including lazy loading, lifecycle management, and hot reloading.
"""
import asyncio
import logging
import time
from typing import Callable, Dict, Set

from agentscope_runtime.engine.schemas.exception import (
    ConfigurationException,
)

from .workspace import Workspace
from ..config.utils import load_config

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
        self._cleanup_tasks: Set[asyncio.Task] = set()
        logger.debug("MultiAgentManager initialized")

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
        # Fast path: already loaded (no lock)
        if agent_id in self.agents:
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
        logger.debug(f"Creating new workspace: {agent_id}")
        instance = Workspace(
            agent_id=agent_id,
            workspace_dir=agent_ref.workspace_dir,
        )

        try:
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
                    await asyncio.to_thread(callback, workspace_info)
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
        new_instance = Workspace(
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
        """Stop all agent instances.

        Called during application shutdown to clean up resources.
        Cancels any pending delayed cleanup tasks and stops all agents.
        """
        logger.info(f"Stopping all agents ({len(self.agents)} running)...")

        # First, cancel pending cleanup tasks to avoid orphaned instances
        await self.cancel_all_cleanup_tasks()

        # Create list of agent IDs to avoid modifying dict during iteration
        agent_ids = list(self.agents.keys())

        for agent_id in agent_ids:
            try:
                instance = self.agents[agent_id]
                await instance.stop()
                logger.debug(f"Agent stopped: {agent_id}")
            except Exception as e:
                logger.error(f"Error stopping agent {agent_id}: {e}")

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

    async def start_all_configured_agents(
        self,
        *,
        preferred_agent_id: str | None = None,
        max_concurrency: int | None = None,
        batch_delay_seconds: float = 0.0,
        post_preferred_delay_seconds: float = 0.0,
        agent_started_callback: Callable[[str, bool], None] | None = None,
    ) -> dict[str, bool]:
        """Start all enabled agents defined in configuration concurrently.

        Only agents with enabled=True will be started.
        Disabled agents are skipped to save resources.

        By default agents are started truly in parallel: get_agent() only holds
        the manager lock briefly for dict checks, releasing it during the slow
        workspace initialization. Callers can provide preferred_agent_id and a
        concurrency limit to make desktop startup less bursty without changing
        the lazy-loading contract. post_preferred_delay_seconds gives the
        active/preferred agent a quiet window before non-preferred agents
        start.

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

        if not agent_ids:
            logger.warning("No enabled agents configured in config")
            return {}

        ordered_agent_ids = list(agent_ids)
        if preferred_agent_id in enabled_agents:
            ordered_agent_ids.remove(preferred_agent_id)
            ordered_agent_ids.insert(0, preferred_agent_id)

        total_agents = len(config.agents.profiles)
        disabled_count = total_agents - len(agent_ids)
        logger.debug(
            f"Starting {len(agent_ids)} enabled agent(s) "
            f"({disabled_count} disabled); preferred={preferred_agent_id!r}, "
            f"max_concurrency={max_concurrency}, "
            f"batch_delay={batch_delay_seconds:.2f}s, "
            f"post_preferred_delay={post_preferred_delay_seconds:.2f}s",
        )

        async def start_single_agent(agent_id: str) -> tuple[str, bool]:
            """Start a single agent with error handling."""

            def notify_agent_started(success: bool) -> None:
                if agent_started_callback is None:
                    return
                try:
                    agent_started_callback(agent_id, success)
                except Exception:
                    logger.debug(
                        "Agent startup callback failed for %s",
                        agent_id,
                        exc_info=True,
                    )

            try:
                logger.debug(f"Starting agent: {agent_id}")
                await self.get_agent(agent_id)
                logger.debug(f"Agent started successfully: {agent_id}")
                notify_agent_started(True)
                return (agent_id, True)
            except Exception as e:
                logger.error(
                    f"Failed to start agent {agent_id}: {e}. "
                    f"Continuing with other agents...",
                )
                notify_agent_started(False)
                return (agent_id, False)

        if (
            preferred_agent_id is None
            and max_concurrency is None
            and batch_delay_seconds <= 0
            and post_preferred_delay_seconds <= 0
        ):
            # Existing behavior: fully parallel background startup.
            results = await asyncio.gather(
                *[start_single_agent(agent_id) for agent_id in agent_ids],
                return_exceptions=False,
            )
        else:
            results = []

            remaining_agent_ids = ordered_agent_ids
            if (
                ordered_agent_ids
                and preferred_agent_id
                and ordered_agent_ids[0] == preferred_agent_id
            ):
                results.append(await start_single_agent(preferred_agent_id))
                remaining_agent_ids = ordered_agent_ids[1:]
                if remaining_agent_ids:
                    delay_seconds = (
                        post_preferred_delay_seconds
                        if post_preferred_delay_seconds > 0
                        else batch_delay_seconds
                    )
                    if delay_seconds > 0:
                        await asyncio.sleep(delay_seconds)

            if remaining_agent_ids:
                batch_size = max_concurrency or len(remaining_agent_ids)
                batch_size = max(1, batch_size)

                for index in range(0, len(remaining_agent_ids), batch_size):
                    if index > 0 and batch_delay_seconds > 0:
                        await asyncio.sleep(batch_delay_seconds)

                    batch = remaining_agent_ids[index : index + batch_size]
                    results.extend(
                        await asyncio.gather(
                            *[
                                start_single_agent(agent_id)
                                for agent_id in batch
                            ],
                            return_exceptions=False,
                        ),
                    )

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
