# -*- coding: utf-8 -*-
"""MultiAgentManager: Manages multiple agent workspaces with lazy loading.

Provides centralized management for multiple Workspace objects,
including lazy loading, lifecycle management, and hot reloading.
"""

import asyncio
import logging
import time
from contextlib import AsyncExitStack, asynccontextmanager, nullcontext
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
from ..utils.io_utils import run_async_to_completion
from ..utils.logging import sanitize_log_value
from ..utils.startup_display import AgentStartupDisplay

logger = logging.getLogger(__name__)

_OLD_WORKSPACE_TASK_WAIT_SECONDS = 60.0
_OLD_WORKSPACE_TASK_MAX_WAIT_ROUNDS = 24 * 60
_OLD_WORKSPACE_CLEANUP_RETRY_SECONDS = 5.0


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
        self._cleanup_tasks: Dict[asyncio.Task, Workspace] = {}
        self._retired_instances: Dict[int, Workspace] = {}
        self._retired_stop_tasks: Dict[int, asyncio.Task] = {}
        self._uninstalling_agents: Set[str] = set()
        self._agent_stop_tasks: Dict[int, asyncio.Task] = {}
        self._unloaded_stop_tasks: Dict[str, asyncio.Task] = {}
        self._reloading_agents: Dict[str, int] = {}
        self._config_generations: Dict[str, int] = {}
        self._operation_locks: dict[str, asyncio.Lock] = {}
        self._channel_delivery_locks: dict[str, asyncio.Lock] = {}
        self._operations: set[asyncio.Task] = set()
        self._closing = False
        self.channel_qrcode_sessions = None
        logger.debug("MultiAgentManager initialized")

    def note_agent_config_changed(self, agent_id: str) -> int:
        """Record that the agent's persisted configuration just changed.

        ``reload_agent`` captures this counter when it starts and aborts
        its swap when the counter moved while the replacement workspace
        was being built.  Without the guard, a zero-downtime rebuild
        that began before a config write could finish after it and
        re-install the pre-write snapshot -- readers would see a fresh
        PUT revert until the next reload landed.  Every config-writer
        path must bump: API writers via ``schedule_agent_reload``, disk
        writers via ``AgentConfigWatcher``.
        """
        value = self._config_generations.get(agent_id, 0) + 1
        self._config_generations[agent_id] = value
        return value

    def _create_workspace(
        self,
        agent_id: str,
        workspace_dir: str,
    ) -> Workspace:
        """Factory method for workspace creation.

        Overridden by WorkspaceRegistry.
        """
        return Workspace(agent_id=agent_id, workspace_dir=workspace_dir)

    @staticmethod
    async def _cleanup_failed_reload_candidate(
        candidate: Workspace,
        agent_id: str,
        original_error: BaseException,
    ) -> None:
        """Stop an uncommitted candidate before propagating its failure."""
        try:
            await run_async_to_completion(
                candidate.stop(final=True, preserve_reused=True),
            )
        except asyncio.CancelledError:
            # A later cancellation was delayed until stop() completed. Keep
            # the cancellation that originally aborted candidate startup.
            if not isinstance(original_error, asyncio.CancelledError):
                raise
        except BaseException:
            logger.warning(
                "Failed to clean up uncommitted workspace candidate "
                f"for {sanitize_log_value(agent_id)}",
                exc_info=True,
            )

    # Workspace preparation and recovery own the manager service internals.
    # pylint: disable=protected-access
    async def _prepare_reload_candidate(
        self,
        candidate: Workspace,
        agent_id: str,
        workspace_dir: str,
    ) -> dict:
        """Attach reusable state and fully start a reload candidate."""
        async with self._lock:
            old_instance = self.agents.get(agent_id)

        reusable = {}
        if old_instance:
            # TaskTracker is agent-scoped rather than workspace-scoped.
            candidate.set_task_tracker(old_instance.task_tracker)

            # pylint: disable=protected-access
            reusable = old_instance._service_manager.get_reusable_services()
            # pylint: enable=protected-access
            if reusable:
                await candidate.set_reusable_components(reusable)
                logger.info(
                    "Set reusable components for "
                    f"{sanitize_log_value(agent_id)}: "
                    f"{list(reusable.keys())}",
                )

        candidate._defer_channel_start = True
        candidate.cron_start_paused = True
        candidate.set_manager(self)
        await candidate.start()
        await self._setup_workspace_plugins(candidate, str(workspace_dir))
        logger.info(
            f"New workspace instance started: {sanitize_log_value(agent_id)}",
        )
        return reusable

    @staticmethod
    async def _discard_reload_candidate(
        candidate: Workspace,
        agent_id: str,
        reason: str,
    ) -> None:
        """Log and stop a candidate rejected before the atomic swap."""
        if reason == "removed":
            logger.warning(
                f"Agent {sanitize_log_value(agent_id)} "
                "was removed during reload, "
                "stopping new instance",
            )
        else:
            logger.info(
                f"Discarding stale reload for {sanitize_log_value(agent_id)}: "
                "configuration changed during rebuild",
            )
        await run_async_to_completion(
            candidate.stop(final=True, preserve_reused=True),
        )

    def get_loaded_agent(self, agent_id: str) -> Workspace | None:
        """Return an already loaded workspace without starting it."""
        return self.agents.get(agent_id)

    @asynccontextmanager
    async def channel_delivery(self, agent_id: str):
        """Keep one delivery on the current owner across reload handoffs."""
        lock = self._channel_delivery_locks.setdefault(
            agent_id,
            asyncio.Lock(),
        )
        async with lock:
            self.assert_agent_available(agent_id)
            workspace = self.agents.get(agent_id)
            if (
                self._closing
                or workspace is None
                or workspace.channel_manager is None
            ):
                raise RuntimeError("Agent channel delivery is unavailable")
            yield workspace.channel_manager

    def _has_failed_owner(self, agent_id):
        return (
            agent_id in self.agents
            and self._agent_startup_statuses.get(agent_id)
            is AgentStartupStatus.FAILED
        )

    def _check_startup_status(self, agent_id):
        if self._has_failed_owner(agent_id):
            raise ConfigurationException(
                config_key="agent",
                message=(
                    f"Agent {agent_id!r} startup cleanup is incomplete; "
                    "stop it before retrying"
                ),
            )

    async def get_agent(self, agent_id: str) -> Workspace:
        self.assert_agent_available(agent_id)
        self._check_startup_status(agent_id)
        if self._closing:
            raise RuntimeError("Workspace manager is stopping")
        if agent_id in self.agents:
            return self.agents[agent_id]
        await self._wait_for_scheduled_startup(agent_id)
        return await self._run_agent_operation(agent_id, self._get_agent)

    async def _run_agent_operation(self, agent_id, operation):
        lock = self._operation_locks.setdefault(agent_id, asyncio.Lock())
        task = asyncio.current_task()
        self._operations.add(task)
        try:
            async with lock:
                if self._closing:
                    raise RuntimeError("Workspace manager is stopping")
                return await operation(agent_id)
        finally:
            self._operations.discard(task)

    async def _get_agent(self, agent_id: str) -> Workspace:
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
        self.assert_agent_available(agent_id)
        self._check_startup_status(agent_id)

        # Fast path: already loaded (no lock)
        if agent_id in self.agents:
            self._agent_startup_statuses[agent_id] = AgentStartupStatus.RUNNING
            logger.debug(
                f"Returning cached agent: {sanitize_log_value(agent_id)}",
            )
            return self.agents[agent_id]

        should_start = False
        event = None
        agent_ref = None

        async with self._lock:
            # Re-check under lock
            self.assert_agent_available(agent_id)
            if agent_id in self.agents:
                logger.debug(
                    f"Returning cached agent: {sanitize_log_value(agent_id)}",
                )
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
                logger.debug(
                    f"Returning cached agent: {sanitize_log_value(agent_id)}",
                )
                return self.agents[agent_id]
            raise ConfigurationException(
                config_key="agent",
                message=f"Agent '{agent_id}' failed to initialize",
            )

        # We are the starter — create outside the lock for parallelism
        t0 = time.perf_counter()
        instance = None
        try:
            logger.debug(
                f"Creating new workspace: {sanitize_log_value(agent_id)}",
            )
            instance = self._create_workspace(
                agent_id=agent_id,
                workspace_dir=agent_ref.workspace_dir,
            )
            instance.set_manager(self)
            await instance.start()

            async with self._lock:
                self.agents[agent_id] = instance

            elapsed = time.perf_counter() - t0
            logger.debug(
                "Workspace created and started: "
                f"{sanitize_log_value(agent_id)} "
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
        except BaseException as e:
            if (
                instance is not None
                and self.agents.get(agent_id) is not instance
            ):
                await run_async_to_completion(
                    self._cleanup_unpublished_workspace(agent_id, instance),
                )
            logger.error(
                f"Failed to start workspace {sanitize_log_value(agent_id)}: "
                f"{sanitize_log_value(e)}",
            )
            raise
        finally:
            await run_async_to_completion(
                self._finish_agent_startup(agent_id, event),
            )

    async def _finish_agent_startup(self, agent_id, event):
        async with self._lock:
            self._pending_starts.pop(agent_id, None)
            if agent_id in self.agents:
                if (
                    self._agent_startup_statuses.get(agent_id)
                    is not AgentStartupStatus.FAILED
                ):
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

    async def _cleanup_unpublished_workspace(self, agent_id, instance):
        try:
            await instance.stop()
        except BaseException:
            async with self._lock:
                self.agents[agent_id] = instance
                self._agent_startup_statuses[
                    agent_id
                ] = AgentStartupStatus.FAILED
            logger.warning(
                "Workspace startup cleanup retained owner for %s",
                sanitize_log_value(agent_id),
                exc_info=True,
            )

    @staticmethod
    async def _run_workspace_hooks(
        hooks: list,
        workspace_info: dict,
        hook_type: str,
    ) -> None:
        """Run sync or async workspace hooks with error isolation."""
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
                    f"Error in {hook_type} hook "
                    f"'{hook.hook_name}' for plugin "
                    f"'{hook.plugin_id}': {sanitize_log_value(exc)}",
                    exc_info=True,
                )

    @classmethod
    async def _fire_workspace_created_hooks(cls, workspace_info: dict) -> None:
        """Invoke hooks registered for newly created workspaces."""
        try:
            from ..plugins.registry import PluginRegistry

            hooks = PluginRegistry().get_workspace_created_hooks()
        except Exception:
            # Plugin system not initialised yet — nothing to do.
            return

        await cls._run_workspace_hooks(
            hooks,
            workspace_info,
            "workspace_created",
        )

    @classmethod
    async def _setup_workspace_plugins(
        cls,
        workspace: Workspace,
        workspace_dir: str,
    ) -> None:
        """Install plugin-contributed in-memory state into a workspace."""
        try:
            from ..plugins.registry import PluginRegistry

            hooks = PluginRegistry().get_workspace_setup_hooks()
        except Exception:
            return

        workspace_info = {
            "agent_id": workspace.agent_id,
            "workspace_dir": workspace_dir,
            "workspace": workspace,
        }
        await cls._run_workspace_hooks(
            hooks,
            workspace_info,
            "workspace setup",
        )

    async def _stop_retired_instance(
        self,
        instance: Workspace,
        agent_id: str,
    ) -> bool:
        """Attempt cleanup without stopping services transferred on reload."""
        key = id(instance)
        task = self._retired_stop_tasks.get(key)
        if task is None or task.done():
            task = asyncio.create_task(
                self._stop_retired_instance_body(instance, agent_id),
            )
            self._retired_stop_tasks[key] = task

            def discard(completed):
                if self._retired_stop_tasks.get(key) is completed:
                    self._retired_stop_tasks.pop(key, None)
                if not completed.cancelled():
                    completed.exception()

            task.add_done_callback(discard)
        return await asyncio.shield(task)

    async def _stop_retired_instance_body(
        self,
        instance: Workspace,
        agent_id: str,
    ) -> bool:
        try:
            if await instance.stop(final=False) is False:
                raise RuntimeError(f"Agent '{agent_id}' did not stop")
        except Exception as exc:
            logger.warning(
                "Old workspace cleanup failed for %s: %s",
                sanitize_log_value(agent_id),
                sanitize_log_value(exc),
            )
            return False
        self._retired_instances.pop(id(instance), None)
        return True

    async def _retry_retired_instance(
        self,
        instance: Workspace,
        agent_id: str,
    ) -> None:
        """Keep the cleanup handle until retry succeeds or shutdown begins."""
        while id(instance) in self._retired_instances:
            await asyncio.sleep(_OLD_WORKSPACE_CLEANUP_RETRY_SECONDS)
            if await self._stop_retired_instance(instance, agent_id):
                return

    async def _graceful_stop_old_instance(
        self,
        old_instance: Workspace,
        agent_id: str,
        active_tasks: dict[str, asyncio.Future] | None = None,
    ) -> None:
        """Gracefully stop old instance after checking for active tasks.

        If active tasks exist, schedule delayed cleanup in background.
        Otherwise, stop immediately.

        Args:
            old_instance: The old workspace instance to stop
            agent_id: Agent ID for logging
            active_tasks: Fixed snapshot of tasks owned by the old workspace.
                When omitted, the method captures the snapshot itself.
        """
        if active_tasks is None:
            active_tasks = (
                await old_instance.task_tracker.snapshot_active_tasks(
                    owner=old_instance,
                )
            )

        cron_manager = getattr(old_instance, "cron_manager", None)
        if cron_manager is not None:
            active_tasks.update(cron_manager.snapshot_active_tasks())

        self._retired_instances[id(old_instance)] = old_instance
        if active_tasks:
            # Active tasks - schedule delayed cleanup in background
            logger.info(
                f"Old workspace instance has {len(active_tasks)} active "
                f"task(s): {list(active_tasks)}. "
                f"Scheduling delayed cleanup for "
                f"{sanitize_log_value(agent_id)}.",
            )

            async def delayed_cleanup():
                """Wait for tasks to complete, then stop old instance."""
                try:
                    completed = False
                    for _ in range(_OLD_WORKSPACE_TASK_MAX_WAIT_ROUNDS):
                        completed = (
                            await old_instance.task_tracker.wait_tasks_done(
                                list(active_tasks.values()),
                                timeout=_OLD_WORKSPACE_TASK_WAIT_SECONDS,
                            )
                        )
                        if completed:
                            break
                        logger.warning(
                            f"Tasks are still active for old instance "
                            f"{sanitize_log_value(agent_id)}. "
                            "Keeping it alive until they finish.",
                        )

                    if completed:
                        logger.info(
                            f"All tasks completed for old instance "
                            f"{sanitize_log_value(agent_id)}. Stopping now.",
                        )
                    else:
                        logger.error(
                            f"Tasks did not finish within 24 hours for old "
                            f"instance {sanitize_log_value(agent_id)}. "
                            "Forcing cleanup to prevent "
                            f"a resource leak.",
                        )
                    if not await self._stop_retired_instance(
                        old_instance,
                        agent_id,
                    ):
                        await self._retry_retired_instance(
                            old_instance,
                            agent_id,
                        )
                    logger.info(
                        "Old workspace instance stopped: "
                        f"{sanitize_log_value(agent_id)}. "
                        f"Delayed cleanup completed.",
                    )
                except Exception as e:
                    logger.warning(
                        "Error during delayed cleanup for "
                        f"{sanitize_log_value(agent_id)}: "
                        f"{sanitize_log_value(e)}. "
                        f"New instance is serving requests.",
                    )
                    await self._retry_retired_instance(old_instance, agent_id)

            cleanup = delayed_cleanup()
        else:
            if await self._stop_retired_instance(old_instance, agent_id):
                logger.info(
                    "Old workspace instance stopped: %s",
                    sanitize_log_value(agent_id),
                )
                return
            cleanup = self._retry_retired_instance(old_instance, agent_id)

        cleanup_task = asyncio.create_task(cleanup)
        self._cleanup_tasks[cleanup_task] = old_instance

        def _on_cleanup_done(task: asyncio.Task) -> None:
            """Remove task from tracking set and log errors."""
            self._cleanup_tasks.pop(task, None)
            if task.cancelled():
                logger.info(
                    "Delayed cleanup task for "
                    f"{sanitize_log_value(agent_id)} was cancelled.",
                )
                return
            exc = task.exception()
            if exc is not None:
                logger.warning(
                    "Error in delayed cleanup task for "
                    f"{sanitize_log_value(agent_id)}: "
                    f"{sanitize_log_value(exc)}.",
                )

        cleanup_task.add_done_callback(_on_cleanup_done)
        logger.info(
            f"Zero-downtime reload completed: {sanitize_log_value(agent_id)}. "
            f"Old instance cleanup scheduled in background.",
        )

    def assert_agent_available(self, agent_id: str) -> None:
        if agent_id in self._uninstalling_agents:
            raise RuntimeError(f"Agent '{agent_id}' is being uninstalled")
        if agent_id in self._unloaded_stop_tasks:
            raise RuntimeError(f"Agent '{agent_id}' is stopping")
        instance = self.agents.get(agent_id)
        if instance is not None and id(instance) in self._agent_stop_tasks:
            raise RuntimeError(f"Agent '{agent_id}' is stopping")

    def reserve_agent_uninstall(self, agent_ids) -> None:
        """Block new requests while plugin-owned agents are removed."""
        self._uninstalling_agents.update(agent_ids)

    def release_agent_uninstall(self, agent_ids) -> None:
        self._uninstalling_agents.difference_update(agent_ids)

    async def stop_agent(self, agent_id: str) -> bool:
        instance = self.agents.get(agent_id)
        task = self._unloaded_stop_tasks.get(
            agent_id,
        ) or self._agent_stop_tasks.get(id(instance))
        if task is not None and not task.done():
            return await asyncio.shield(task)

        async def stop_current(key):
            # A queued request must not stop a replacement owner.
            if instance is not None and self.agents.get(key) is not instance:
                return False
            task = self._unloaded_stop_tasks.get(key)
            if task is not None and not task.done():
                return await asyncio.shield(task)
            sessions = self.channel_qrcode_sessions
            if key not in self.agents and sessions is not None:

                async def revoke_unloaded():
                    async with sessions.operation_guard(key):
                        return await self._stop_agent(key)

                task = asyncio.create_task(revoke_unloaded())
                self._unloaded_stop_tasks[key] = task

                def discard(completed):
                    if self._unloaded_stop_tasks.get(key) is completed:
                        self._unloaded_stop_tasks.pop(key, None)
                    if not completed.cancelled():
                        completed.exception()

                task.add_done_callback(discard)
                return await asyncio.shield(task)
            return await self._stop_agent(key)

        return await self._run_agent_operation(agent_id, stop_current)

    async def _stop_agent(self, agent_id: str) -> bool:
        """Stop a specific agent instance.

        Args:
            agent_id: Agent ID to stop

        Returns:
            bool: True if agent was stopped, False if not running
        """
        async with self._lock:
            if agent_id not in self.agents:
                logger.warning(
                    f"Agent not running: {sanitize_log_value(agent_id)}",
                )
                return False

            instance = self.agents[agent_id]
            key = id(instance)
            task = self._agent_stop_tasks.get(key)
            if task is None or task.done():
                task = asyncio.create_task(
                    self._stop_agent_instance(agent_id, instance),
                )
                self._agent_stop_tasks[key] = task
                # A cancelled caller must not lose the worker's exception.
                task.add_done_callback(
                    lambda done: (
                        None if done.cancelled() else done.exception()
                    ),
                )
        return await asyncio.shield(task)

    async def _stop_agent_instance(
        self,
        agent_id: str,
        instance: Workspace,
    ) -> bool:
        sessions = self.channel_qrcode_sessions
        guard = (
            sessions.operation_guard(agent_id) if sessions else nullcontext()
        )
        async with guard:
            return await self._stop_agent_instance_body(agent_id, instance)

    async def _stop_agent_instance_body(
        self,
        agent_id: str,
        instance: Workspace,
    ) -> bool:
        await self._cancel_cleanup_tasks(agent_id)
        if any(
            retired.agent_id == agent_id
            for retired in self._retired_instances.values()
        ):
            raise RuntimeError(f"Agent '{agent_id}' cleanup is incomplete")
        if await instance.stop() is False:
            raise RuntimeError(f"Agent '{agent_id}' did not stop")
        async with self._lock:
            if self.agents.get(agent_id) is instance:
                self.agents.pop(agent_id)
                self._agent_startup_statuses[
                    agent_id
                ] = AgentStartupStatus.DISABLED
            self._agent_stop_tasks.pop(id(instance), None)
        logger.info(
            f"Agent stopped and removed: {sanitize_log_value(agent_id)}",
        )
        return True

    @staticmethod
    def _mark_rejected_reusable_services_for_cleanup(
        old_instance: Workspace,
        new_instance: Workspace,
        reusable: dict,
    ) -> None:
        """Ensure services rejected by the new workspace are later closed."""
        if not reusable:
            return

        # pylint: disable=protected-access
        accepted_reusable = new_instance._service_manager.reused_services
        rejected_reusable = set(reusable) - accepted_reusable
        for service_name in rejected_reusable:
            descriptor = old_instance._service_manager.descriptors.get(
                service_name,
            )
            if descriptor is not None:
                descriptor.reusable = False
            old_instance._service_manager.reused_services.discard(
                service_name,
            )
        # pylint: enable=protected-access

    async def _stop_old_config_watcher(
        self,
        old_instance: Workspace,
        agent_id: str,
    ) -> None:
        """Stop the outgoing instance's config watcher, best effort."""
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
                f"{sanitize_log_value(agent_id)}: "
                f"{sanitize_log_value(stop_err)}.",
            )

    async def reload_agent(self, agent_id: str) -> bool:
        """Track replacements while serializing each agent's ownership."""
        self.assert_agent_available(agent_id)
        self._reloading_agents[agent_id] = (
            self._reloading_agents.get(agent_id, 0) + 1
        )
        try:
            return await self._run_agent_operation(
                agent_id,
                self._reload_agent,
            )
        finally:
            self._reloading_agents[agent_id] -= 1
            if not self._reloading_agents[agent_id]:
                self._reloading_agents.pop(agent_id)

    # One transaction keeps the candidate/old ownership rollback explicit.
    # pylint: disable=too-many-branches,too-many-statements,protected-access
    async def _reload_agent(self, agent_id: str) -> bool:
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
        # Capture the config generation first: any write bumping it
        # after this point invalidates the snapshot this rebuild will
        # be based on, and the swap below aborts in favour of the
        # newer writer's own scheduled reload.
        self.assert_agent_available(agent_id)
        generation = self._config_generations.get(agent_id, 0)
        async with self._lock:
            if agent_id not in self.agents:
                logger.debug(
                    f"Agent not running, will be loaded on next "
                    f"request: {sanitize_log_value(agent_id)}",
                )
                return False
            old_instance = self.agents[agent_id]

        logger.info(
            f"Reloading agent (zero-downtime): {sanitize_log_value(agent_id)}",
        )

        # Step 1.5: Stop old config watcher (no-op if it triggered
        # this reload, since it already disabled itself).
        # Stop the old watcher only once channel handoff has succeeded.

        # Step 2: Load configuration (outside lock)
        config = load_config()
        if agent_id not in config.agents.profiles:
            logger.error(
                f"Agent '{sanitize_log_value(agent_id)}' "
                "not found in configuration "
                f"during reload",
            )
            return False

        agent_ref = config.agents.profiles[agent_id]

        # Step 3: Create and start new workspace instance (outside lock)
        # This is the slow part, but doesn't block other agents
        logger.info(
            f"Creating new workspace instance: {sanitize_log_value(agent_id)}",
        )
        new_instance = self._create_workspace(
            agent_id=agent_id,
            workspace_dir=agent_ref.workspace_dir,
        )

        # Until the atomic swap commits, this manager exclusively owns the
        # candidate and must stop it on every exit path.
        candidate_committed = False
        old_channels_stopped = False
        old_manager = getattr(old_instance, "channel_manager", None)
        old_keys = (
            [ch.channel for ch in old_manager.channels] if old_manager else []
        )
        handoff = AsyncExitStack()
        try:
            reusable = await self._prepare_reload_candidate(
                new_instance,
                agent_id,
                agent_ref.workspace_dir,
            )

            from ..plugins.registry import PluginRegistry
            from ..plugins.lifecycle import QuiescenceError

            if (
                self.agents.get(agent_id) is not old_instance
                or self._config_generations.get(agent_id, 0) != generation
            ):
                await self._discard_reload_candidate(
                    new_instance,
                    agent_id,
                    "stale",
                )
                return False
            delivery_lock = self._channel_delivery_locks.setdefault(
                agent_id,
                asyncio.Lock(),
            )
            await handoff.enter_async_context(delivery_lock)
            if old_manager is not None:
                if not await old_manager.quiesce():
                    raise QuiescenceError("CHANNEL_DRAIN_TIMEOUT")
                # Rollback must also recover a partially stopped set.
                old_channels_stopped = True
                await old_manager.stop_all()
            new_instance._defer_channel_start = False
            new_manager = getattr(new_instance, "channel_manager", None)
            if new_manager is not None:
                new_manager._defer_channel_start = False
                await new_manager.start_all()
            await PluginRegistry().projector.project_workspace(
                new_instance,
                kinds={"channel"},
            )
            if self._config_generations.get(agent_id, 0) != generation:
                raise RuntimeError(
                    "Workspace config changed during channel handoff",
                )
            await self._stop_old_config_watcher(old_instance, agent_id)

            # Step 4: Atomic swap (minimal lock time). Do not await candidate
            # cleanup while holding this lock.
            discard_reason = None
            async with self._lock:
                if (
                    agent_id in self._uninstalling_agents
                    or id(self.agents.get(agent_id)) in self._agent_stop_tasks
                ):
                    discard_reason = "stopping"
                elif agent_id not in self.agents:
                    discard_reason = "removed"
                elif self._config_generations.get(agent_id, 0) != generation:
                    discard_reason = "stale"
                else:
                    old_instance = self.agents[agent_id]
                    cron_manager = getattr(new_instance, "cron_manager", None)
                    if cron_manager is not None:
                        cron_manager.handoff_from(
                            getattr(old_instance, "cron_manager", None),
                        )
                    self.agents[agent_id] = new_instance
                    self._retired_instances[id(old_instance)] = old_instance
                    candidate_committed = True
        except BaseException as error:
            if candidate_committed:
                raise

            if isinstance(error, Exception):
                logger.exception(
                    "Failed to start new workspace instance for "
                    f"{sanitize_log_value(agent_id)}: "
                    f"{sanitize_log_value(error)}",
                )

            await self._cleanup_failed_reload_candidate(
                new_instance,
                agent_id,
                error,
            )

            if old_channels_stopped and old_manager is not None:
                await run_async_to_completion(
                    self._restore_channels(old_instance, old_keys),
                )
            if isinstance(error, asyncio.CancelledError):
                raise
            if isinstance(error, Exception):
                # Old instance is still running and serving requests.
                return False
            raise

        else:
            if not candidate_committed:
                assert discard_reason is not None
                await self._discard_reload_candidate(
                    new_instance,
                    agent_id,
                    discard_reason,
                )
                if old_channels_stopped:
                    await run_async_to_completion(
                        self._restore_channels(old_instance, old_keys),
                    )
                return False
        finally:
            await handoff.aclose()

        logger.info(
            f"Workspace instance replaced: {sanitize_log_value(agent_id)}",
        )

        # A reusable service can be rejected during startup when its class no
        # longer matches the newly loaded configuration (for example, after a
        # memory backend switch).  The old workspace must retain it for any
        # in-flight requests, but it must not treat it as transferred forever
        # or its eventual non-final shutdown would leak the old service.
        self._mark_rejected_reusable_services_for_cleanup(
            old_instance,
            new_instance,
            reusable,
        )

        # Once committed, cleanup must take ownership even if the reload
        # request is cancelled while capturing outgoing tasks.
        await run_async_to_completion(
            self._graceful_stop_old_instance(old_instance, agent_id),
        )

        return True

    # pylint: enable=too-many-branches,too-many-statements

    # pylint: disable=protected-access
    async def _restore_channels(self, workspace, keys):
        from ..plugins.registry import PluginRegistry

        manager = workspace.channel_manager
        await manager.start_all()
        for key in keys:
            if manager._find_channel(key) is None:
                try:
                    await manager.start_one(key, manager._workspace_config)
                except Exception:
                    logger.exception(
                        "Unable to restore channel '%s'; retaining owner",
                        key,
                    )
        manager.resume_ingress()
        await PluginRegistry().projector.project_workspace(
            workspace,
            kinds={"channel"},
        )

    async def cancel_all_cleanup_tasks(self) -> None:
        """Cancel and await all pending delayed cleanup tasks.

        This ensures that any in-progress background cleanups are either
        completed or cleanly cancelled before the manager is torn down.
        Called by stop_all() during shutdown.
        """
        await self._cancel_cleanup_tasks()

    async def _cancel_cleanup_tasks(
        self,
        agent_id: str | None = None,
        *,
        stop_retired: bool = True,
    ) -> None:
        """Release outgoing instances, optionally for just one agent."""
        if not self._cleanup_tasks and not self._retired_instances:
            return

        logger.info(
            f"Cancelling {len(self._cleanup_tasks)} pending cleanup "
            f"task(s)...",
        )
        tasks = [
            task
            for task, instance in self._cleanup_tasks.items()
            if agent_id is None or instance.agent_id == agent_id
        ]
        for task in tasks:
            self._cleanup_tasks.pop(task, None)

        for task in tasks:
            if not task.done():
                task.cancel()

        # Await completion of all tasks, collecting exceptions
        await asyncio.gather(*tasks, return_exceptions=True)
        if not stop_retired:
            return
        retired = [
            instance
            for instance in self._retired_instances.values()
            if agent_id is None or instance.agent_id == agent_id
        ]
        await asyncio.gather(
            *(
                self._stop_retired_instance(instance, instance.agent_id)
                for instance in retired
            ),
        )
        logger.info("All cleanup tasks cancelled/completed")

    async def stop_all(self):
        """Retain failed live and preparing workspaces for cleanup retries."""
        from ..plugins.registry import PluginRegistry
        from ..plugins.lifecycle import QuiescenceError

        self._closing = True
        if self.channel_qrcode_sessions is not None:
            await self.channel_qrcode_sessions.aclose()
        operations = [
            task
            for task in self._operations
            if task is not asyncio.current_task()
        ]
        for task in operations:
            task.cancel()
        if operations:
            _, pending = await asyncio.wait(operations, timeout=5.0)
            if pending:
                raise QuiescenceError("Workspace preparation is still pending")
        await self.cancel_all_startup_tasks()
        await self._cancel_cleanup_tasks(stop_retired=False)
        workspaces = dict(self._retired_instances)
        workspaces.update((id(ws), ws) for ws in self.agents.values())
        for ws in PluginRegistry().projector.workspaces():
            if getattr(ws, "_manager", None) is self:
                workspaces[id(ws)] = ws
        failures = []
        current_agent_ids = set(self.agents)

        async def stop_workspace(workspace):
            try:
                if self.agents.get(workspace.agent_id) is workspace:
                    await self._stop_agent(workspace.agent_id)
                elif id(workspace) in self._retired_instances:
                    if workspace.agent_id in current_agent_ids:
                        return
                    if not await self._stop_retired_instance(
                        workspace,
                        workspace.agent_id,
                    ):
                        failures.append(
                            f"Retired workspace {workspace.agent_id}",
                        )
                else:
                    await workspace.stop()
            except Exception as exc:
                failures.append(str(exc))

        async def wait_unloaded_stop(task):
            try:
                await asyncio.shield(task)
            except Exception as exc:
                failures.append(str(exc))

        await asyncio.gather(
            *(stop_workspace(ws) for ws in workspaces.values()),
            *(
                wait_unloaded_stop(task)
                for task in tuple(self._unloaded_stop_tasks.values())
            ),
        )
        if failures:
            raise QuiescenceError(
                "Workspace cleanup failed: " + "; ".join(failures),
            )

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
            logger.info(
                "Successfully preloaded agent: "
                f"{sanitize_log_value(agent_id)}",
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to preload agent {sanitize_log_value(agent_id)}: "
                f"{sanitize_log_value(e)}",
            )
            return False

    async def _wait_for_scheduled_startup(self, agent_id: str) -> None:
        """Join an existing queued startup instead of bypassing its limit."""
        self.assert_agent_available(agent_id)
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

        self.assert_agent_available(agent_id)

    def schedule_agent_startup(self, agent_id: str) -> asyncio.Task[bool]:
        """Queue one custom agent through the shared startup limit."""
        existing_task = self._agent_startup_tasks.get(agent_id)
        if existing_task is not None and not existing_task.done():
            return existing_task

        if not self._has_failed_owner(agent_id):
            self._agent_startup_statuses[agent_id] = (
                AgentStartupStatus.RUNNING
                if agent_id in self.agents
                else AgentStartupStatus.PENDING
            )

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
            return not self._has_failed_owner(agent_id)
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
                if self._has_failed_owner(agent_id):
                    continue
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

        disabled_count = len(config.agents.profiles) - len(agent_ids)
        logger.debug(
            f"Starting {len(agent_ids)} enabled agent(s) "
            f"({disabled_count} disabled)",
        )

        async def start_single_agent(agent_id: str) -> tuple[str, bool]:
            """Start a single agent with error handling."""
            try:
                logger.debug(f"Starting agent: {sanitize_log_value(agent_id)}")
                await self.get_agent(agent_id)
                logger.debug(
                    "Agent started successfully: "
                    f"{sanitize_log_value(agent_id)}",
                )
                return (agent_id, True)
            except Exception as e:
                logger.error(
                    "Failed to start agent "
                    f"{sanitize_log_value(agent_id)}: "
                    f"{sanitize_log_value(e)}. "
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

        if core_result_map.get("default") is False:
            custom_result_map = {
                agent_id: agent_id in self.agents
                and not self._has_failed_owner(agent_id)
                for agent_id in custom_agent_ids
            }
            logger.error(
                "Default agent failed to start; skipping %d custom agent(s)",
                len(custom_agent_ids),
            )
            return {**core_result_map, **custom_result_map}

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
