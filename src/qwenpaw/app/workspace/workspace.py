# -*- coding: utf-8 -*-
"""Workspace: Encapsulates a complete independent agent runtime.

Each Workspace represents a standalone agent workspace with its own:
- ChannelManager (communication channels)
- BaseMemoryManager (conversation memory)
- DriverManager (external capability runtime, currently MCP)
- CronManager (scheduled tasks)
- WorkspacePlugins (tool/hook/command/prompt registries)

Request processing is handled by ``Runtime`` (see ``stream_query``).
"""
import asyncio
import logging
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Iterable, Optional

from ...config.timezone import normalize_tz
from ...config.utils import load_config
from ...utils.io_utils import run_async_to_completion

from .service_manager import ServiceDescriptor, ServiceManager
from .workspace_plugins import WorkspacePlugins
from .service_factories import (
    create_driver_service,
    create_driver_config_watcher,
    create_chat_service,
    create_channel_service,
    create_agent_config_watcher,
    create_mail_monitor_service,
)
from .local_workspace import QwenPawLocalWorkspace
from ..task_tracker import TaskTracker
from ..chats.session import SafeJSONSession
from ..crons.manager import CronManager
from ..crons.repo.json_repo import JsonJobRepository
from ...config.config import load_agent_config
from ...utils.logging import sanitize_log_value

logger = logging.getLogger(__name__)


class Workspace:
    """Single agent workspace with complete runtime components.

    Each Workspace is an independent agent instance with its own:
    - ChannelManager: Manages communication channels
    - BaseMemoryManager: Manages conversation memory
    - DriverManager: Manages external capabilities exposed through Drivers
    - CronManager: Manages scheduled tasks
    - WorkspacePlugins: Per-workspace pluggable registries

    Request processing goes through ``stream_query`` which delegates
    to ``Runtime.run()``.
    """

    def __init__(self, agent_id: str, workspace_dir: str):
        """Initialize agent instance.

        Args:
            agent_id: Unique agent identifier
            workspace_dir: Path to agent's workspace directory
        """
        self.agent_id = agent_id
        self.workspace_dir = Path(workspace_dir).expanduser()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        # Per-workspace pluggable registries (tools, hooks, commands, prompts)
        self.plugins = WorkspacePlugins()
        self._local_workspace = QwenPawLocalWorkspace(
            tool_registry=self.plugins.tool_registry,
            workdir=str(self.workspace_dir),
            workspace_id=agent_id,
            default_mcps=[],
            skill_paths=[],
        )

        # Service manager (unified component management)
        self._service_manager = ServiceManager(self)

        # Non-service state
        self._config = None  # Loaded before start()
        self._config_mtime: float | None = None
        self._started = False
        self._start_attempted = False
        self._manager = None  # Reference to MultiAgentManager
        self._task_tracker = TaskTracker()
        self._app_services: Any = None
        self._harness_runtime = None

        # Register all services
        self._register_services()

        logger.debug(
            f"Created Workspace: {sanitize_log_value(agent_id)} "
            f"at {self.workspace_dir}",
        )

    # Service access via properties (delegates to ServiceManager)
    @property
    def session(self) -> Optional[SafeJSONSession]:
        """Get session instance from ServiceManager."""
        return self._service_manager.services.get("session")

    @property
    def memory_manager(self):
        """Get memory manager instance from ServiceManager."""
        return self._service_manager.services.get("memory_manager")

    @property
    def driver_manager(self):
        """Get DriverManager instance from ServiceManager."""
        return self._service_manager.services.get("driver_manager")

    @property
    def chat_manager(self):
        """Get chat manager instance from ServiceManager."""
        return self._service_manager.services.get("chat_manager")

    @property
    def channel_manager(self):
        """Get channel manager instance from ServiceManager."""
        return self._service_manager.services.get("channel_manager")

    @property
    def cron_manager(self):
        """Get cron manager instance from ServiceManager."""
        return self._service_manager.services.get("cron_manager")

    @property
    def mail_monitor(self):
        """Get mail push monitor instance from ServiceManager."""
        return self._service_manager.services.get("mail_monitor")

    # Non-service state
    @property
    def task_tracker(self) -> TaskTracker:
        """Get task tracker for background chat and reconnect."""
        return self._task_tracker

    def set_task_tracker(self, task_tracker: TaskTracker) -> None:
        """Reuse an agent task tracker before this workspace starts."""
        if self._started:
            raise RuntimeError(
                f"Cannot replace task tracker for started workspace "
                f"'{self.agent_id}'",
            )
        self._task_tracker = task_tracker

    @property
    def config(self):
        """Agent configuration pinned to this workspace instance.

        ``load_agent_config`` hands out detached copies to protect its
        cache, but the ubiquitous write idiom -- mutate
        ``workspace.config`` in place, then
        ``save_agent_config(workspace.config)`` -- needs BOTH property
        accesses to observe the same object, or the save silently
        persists an unpatched fresh copy and the write is lost.  The
        snapshot is therefore pinned per workspace and refreshed only
        when agent.json's mtime moves (any save or external edit).
        """
        current_mtime = self._agent_config_file_mtime()
        if self._config is None or current_mtime != self._config_mtime:
            self._config = load_agent_config(self.agent_id)
            self._config_mtime = current_mtime
        return self._config

    def _agent_config_file_mtime(self) -> float | None:
        try:
            return (self.workspace_dir / "agent.json").stat().st_mtime
        except OSError:
            return None

    @property
    def local_workspace(self) -> QwenPawLocalWorkspace:
        """AgentScope LocalWorkspace routing tools to ToolRegistry."""
        return self._local_workspace

    @property
    def harness_runtime(self):
        """Return the lazily-created third-party agent runtime."""
        if self._harness_runtime is None:
            from ...harnesses import HarnessRuntime

            self._harness_runtime = HarnessRuntime(
                self.workspace_dir,
                self.session,
                self.agent_id,
                self,
            )
        return self._harness_runtime

    def bootstrap_plugins(  # pylint: disable=too-many-branches
        self,
        *,
        builtin_tool_funcs: Iterable[Any] | None = None,
        builtin_contributor_clses: Iterable[type] | None = None,
        builtin_mode_clses: Iterable[type] | None = None,
        builtin_hook_clses: Iterable[type] | None = None,
        builtin_command_specs: Iterable[Any] | None = None,
        builtin_fallback_handler: Any | None = None,
    ) -> None:
        """Populate per-workspace registries with built-in classes.

        Called once by ``WorkspaceRegistry`` immediately after creation.
        """
        if builtin_tool_funcs:
            tr = self.plugins.tool_registry
            for func in builtin_tool_funcs:
                try:
                    desc = getattr(func, "_tool_descriptor", None)
                    if desc is not None:
                        tr.register(desc)
                    else:
                        logger.debug(
                            "bootstrap: %s has no _tool_descriptor, skipped",
                            getattr(func, "__name__", func),
                        )
                except Exception:
                    logger.debug(
                        "bootstrap: tool register failed for %s",
                        getattr(func, "__name__", func),
                        exc_info=True,
                    )

        if builtin_contributor_clses:
            for cls in builtin_contributor_clses:
                try:
                    self.plugins.prompt_manager.register(cls())
                except Exception:
                    logger.debug(
                        "bootstrap: contributor register failed for %s",
                        cls,
                        exc_info=True,
                    )

        if builtin_hook_clses:
            for cls in builtin_hook_clses:
                try:
                    self.plugins.hook_registry.register(cls())
                except Exception:
                    logger.debug(
                        "bootstrap: hook register failed for %s",
                        cls,
                        exc_info=True,
                    )

        if builtin_command_specs:
            for spec in builtin_command_specs:
                try:
                    self.plugins.slash_command_registry.register(spec)
                except Exception:
                    logger.debug(
                        "bootstrap: command register failed for %s",
                        getattr(spec, "name", spec),
                        exc_info=True,
                    )

        if builtin_fallback_handler is not None:
            try:
                self.plugins.slash_command_registry.register_fallback(
                    builtin_fallback_handler,
                )
            except Exception:
                logger.debug(
                    "bootstrap: fallback handler register failed",
                    exc_info=True,
                )

        if builtin_mode_clses:
            for cls in builtin_mode_clses:
                try:
                    mode = cls()
                    self.plugins.register_mode(mode, self)
                except Exception:
                    logger.debug(
                        "bootstrap: mode register failed for %s",
                        cls,
                        exc_info=True,
                    )

        try:
            from ...modes.custom_loop import load_custom_loop_modes

            load_custom_loop_modes(self)
        except Exception:
            logger.warning(
                "bootstrap: custom loop modes could not be loaded",
                exc_info=True,
            )

        # pylint: disable=protected-access
        n_hooks = len(self.plugins.hook_registry._by_phase)
        n_cmds = len(
            self.plugins.slash_command_registry._by_name,
        )
        # pylint: enable=protected-access
        logger.info(
            "workspace %s: bootstrap_plugins complete "
            "(hooks=%d commands=%d modes=%d)",
            sanitize_log_value(self.agent_id),
            n_hooks,
            n_cmds,
            len(self.plugins.modes),
        )

    def set_manager(self, manager) -> None:
        """Set reference to MultiAgentManager for /daemon restart.

        Args:
            manager: MultiAgentManager instance
        """
        self._manager = manager

    def set_app_services(self, app_services: Any) -> None:
        """Inject the cross-workspace AppServiceManager reference."""
        self._app_services = app_services

    async def stream_query(
        self,
        request: Any,
    ) -> AsyncGenerator[Any, None]:
        """Process a request through the Runtime pipeline.

        Drop-in replacement for the old ``Runner.stream_query()``.
        """
        config = load_agent_config(self.agent_id)
        backend = config.backend
        if backend != "qwenpaw":
            settings = dict(getattr(config, "backend_settings", {}))
            request_context = dict(
                getattr(request, "request_context", None) or {},
            )
            backend_controls = request_context.pop(
                "backend_controls",
                {},
            )
            if isinstance(backend_controls, dict):
                settings.update(backend_controls)
            settings["_request_context"] = {
                **request_context,
                "agent_id": self.agent_id,
                "session_id": getattr(request, "session_id", None),
                "user_id": getattr(request, "user_id", None),
                "channel": getattr(request, "channel", None) or "console",
            }
            async for item in self.harness_runtime.stream(
                backend=backend,
                request=request,
                cwd=self.workspace_dir.resolve(),
                settings=settings,
            ):
                yield item
            return

        from ...runtime import Runtime

        rt = Runtime(workspace=self, app_services=self._app_services)
        async for item in rt.run(request):
            yield item

    def _register_services(  # pylint: disable=too-many-statements
        self,
    ) -> None:
        """Register all workspace services with ServiceManager.

        Uses declarative ServiceDescriptor configuration to replace
        hardcoded initialization logic.
        """
        # pylint: disable=protected-access
        from ...agents.memory.base_memory_manager import (
            get_memory_manager_backend,
        )

        sm = self._service_manager

        # Priority 5: LocalWorkspace (tool routing)
        def _init_local_workspace(
            ws: "Workspace",
            _service: Any,
            _publish: Callable[[Any], None],
        ) -> "QwenPawLocalWorkspace":
            return ws._local_workspace  # pylint: disable=protected-access

        sm.register(
            ServiceDescriptor(
                name="local_workspace",
                service_class=None,
                post_init=_init_local_workspace,
                start_method="initialize",
                stop_method="close",
                priority=5,
                concurrent_init=False,
            ),
        )

        # Priority 10: Session (replaces old Runner init)
        sm.register(
            ServiceDescriptor(
                name="session",
                service_class=SafeJSONSession,
                init_args=lambda ws: {
                    "save_dir": str(ws.workspace_dir / "sessions"),
                },
                priority=10,
                concurrent_init=False,
            ),
        )

        # Priority 20: Core services (concurrent)
        sm.register(
            ServiceDescriptor(
                name="memory_manager",
                service_class=lambda ws: get_memory_manager_backend(
                    ws._config.running.memory_manager_backend,
                ),
                init_args=lambda ws: {
                    "working_dir": str(ws.workspace_dir),
                    "agent_id": ws.agent_id,
                },
                start_method="start",
                stop_method="close",
                reusable=True,
                priority=20,
                concurrent_init=True,
                # reme depends on `agentscope.token`, which agentscope no
                # longer ships; let the workspace boot without
                # memory_manager when its import fails.
                optional=True,
            ),
        )

        sm.register(
            ServiceDescriptor(
                name="driver_manager",
                service_class=None,
                post_init=create_driver_service,
                stop_method="shutdown_all",
                priority=20,
                concurrent_init=True,
                optional=True,
            ),
        )

        sm.register(
            ServiceDescriptor(
                name="chat_manager",
                service_class=None,
                post_init=create_chat_service,
                reusable=True,
                priority=20,
                concurrent_init=True,
            ),
        )

        # Priority 30: Channel manager
        sm.register(
            ServiceDescriptor(
                name="channel_manager",
                service_class=None,
                post_init=create_channel_service,
                start_method="start_all",
                stop_method="stop_all",
                priority=30,
                concurrent_init=False,
            ),
        )

        # Priority 40: Cron manager
        sm.register(
            ServiceDescriptor(
                name="cron_manager",
                service_class=CronManager,
                init_args=lambda ws: {
                    "repo": JsonJobRepository(
                        str(ws.workspace_dir / "jobs.json"),
                    ),
                    "workspace": ws,
                    "channel_manager": ws._service_manager.services.get(
                        "channel_manager",
                    ),
                    "timezone": normalize_tz(
                        load_config().user_timezone or "UTC",
                    )
                    or "UTC",
                    "agent_id": ws.agent_id,
                },
                start_method="start",
                stop_method="stop",
                priority=40,
                concurrent_init=False,
            ),
        )

        # Priority 45: Mail push monitor (conditional: mail.push enabled)
        sm.register(
            ServiceDescriptor(
                name="mail_monitor",
                service_class=None,
                post_init=create_mail_monitor_service,
                start_method="start",
                stop_method="stop",
                priority=45,
                concurrent_init=False,
                require_clean_stop=True,
            ),
        )

        # Priority 50: Agent Config Watcher (conditional)
        sm.register(
            ServiceDescriptor(
                name="agent_config_watcher",
                service_class=None,
                post_init=create_agent_config_watcher,
                start_method="start",
                stop_method="stop",
                priority=50,
                concurrent_init=False,
            ),
        )

        # Priority 51: Driver Card Watcher (conditional)
        sm.register(
            ServiceDescriptor(
                name="driver_config_watcher",
                service_class=None,
                post_init=create_driver_config_watcher,
                start_method="start",
                stop_method="stop",
                priority=51,
                concurrent_init=False,
            ),
        )

    async def set_reusable_components(self, components: dict) -> None:
        """Set components to reuse from previous instance.

        Must be called BEFORE start(). Allows reusing components that support
        hot-reload without recreating them. If a service has a reload_func,
        it will be called during this process.

        Args:
            components: Dict mapping component name to instance.
                Supported keys:
                - 'memory_manager': BaseMemoryManager instance
                - 'chat_manager': ChatManager instance

        Example:
            new_ws = Workspace("default", workspace_dir)
            await new_ws.set_reusable_components({
                'memory_manager': old_ws.memory_manager,
                'chat_manager': old_ws.chat_manager,
            })
            await new_ws.start()
        """
        if self._started:
            logger.warning(
                f"Cannot set reusable components for already started "
                f"workspace: {self.agent_id}",
            )
            return

        # Delegate to ServiceManager
        for name, component in components.items():
            await self._service_manager.set_reusable(name, component)

    async def start(self):
        """Start workspace and initialize all components."""
        if self._started:
            logger.debug(
                "Workspace already started: "
                f"{sanitize_log_value(self.agent_id)}",
            )
            return

        self._start_attempted = True

        logger.info(
            f"Starting workspace: {sanitize_log_value(self.agent_id)}",
        )

        from ...agents.skill_system import (
            ensure_skill_pool_initialized,
        )

        try:
            ensure_skill_pool_initialized()
        except Exception as e:
            logger.warning(
                f"Skill pool initialization failed (non-fatal): {e}",
            )

        try:
            # 1. Load agent configuration
            self._config = load_agent_config(self.agent_id)
            logger.debug(
                "Loaded config for agent: "
                f"{sanitize_log_value(self.agent_id)}",
            )

            # 2. Run legacy weixin -> wechat data migrations BEFORE services
            # start so ChatManager / Runner see the canonical layout.
            self._migrate_legacy_weixin_data()

            # 3. Start all services via ServiceManager
            await self._service_manager.start_all()

            self._started = True
            logger.info(
                "Workspace started successfully: "
                f"{sanitize_log_value(self.agent_id)}",
            )

        except BaseException as error:
            if not isinstance(error, asyncio.CancelledError):
                logger.error(
                    "Failed to start agent instance "
                    f"{sanitize_log_value(self.agent_id)}: "
                    f"{sanitize_log_value(error)}",
                )
            # Clean up partially started components
            try:
                await run_async_to_completion(
                    self.stop(final=True, preserve_reused=True),
                )
            except asyncio.CancelledError:
                # A later cancellation request was delayed until cleanup
                # completed. Preserve the original startup cancellation.
                if not isinstance(error, asyncio.CancelledError):
                    raise
            except BaseException as cleanup_error:
                logger.warning(
                    "Failed to clean up partially started workspace "
                    f"{sanitize_log_value(self.agent_id)}: "
                    f"{sanitize_log_value(cleanup_error)}",
                )
            raise

    def _migrate_legacy_weixin_data(self) -> None:
        """Eagerly migrate legacy weixin -> wechat data on workspace start.

        Each step is guarded so a failure logs a warning instead of
        blocking startup; affected files stay in their legacy state.
        """
        from ..crons.repo.json_repo import (
            migrate_final_mode_to_stream,
            migrate_legacy_weixin_jobs_file,
        )
        from ..chats.repo.json_repo import migrate_legacy_weixin_chats_file
        from ..chats.session import migrate_legacy_weixin_session_files

        try:
            migrate_legacy_weixin_chats_file(
                self.workspace_dir / "chats.json",
            )
        except Exception as exc:
            logger.warning(
                "weixin->wechat chats.json migration failed for "
                "agent %s: %s",
                sanitize_log_value(self.agent_id),
                sanitize_log_value(exc),
            )

        try:
            migrate_legacy_weixin_jobs_file(
                self.workspace_dir / "jobs.json",
            )
        except Exception as exc:
            logger.warning(
                "weixin->wechat jobs.json migration failed for "
                "agent %s: %s",
                sanitize_log_value(self.agent_id),
                sanitize_log_value(exc),
            )

        try:
            migrate_legacy_weixin_session_files(
                str(self.workspace_dir / "sessions"),
            )
        except Exception as exc:
            logger.warning(
                "weixin->wechat sessions migration failed for agent %s: %s",
                sanitize_log_value(self.agent_id),
                sanitize_log_value(exc),
            )

        try:
            migrate_final_mode_to_stream(
                self.workspace_dir / "jobs.json",
            )
        except Exception as exc:
            logger.warning(
                "final->stream jobs.json migration failed for agent %s: %s",
                sanitize_log_value(self.agent_id),
                sanitize_log_value(exc),
            )

    async def stop(
        self,
        final: bool = True,
        preserve_reused: bool = False,
    ):
        """Stop agent instance and clean up all resources.

        Args:
            final: If True (default), stop ALL services including reusable.
                   If False, skip reusable services (for reload scenario).
            preserve_reused: Keep services borrowed from another workspace
                alive while cleaning up this workspace.
        """
        if not self._started and not self._start_attempted:
            logger.debug(
                f"Workspace not started: {sanitize_log_value(self.agent_id)}",
            )
            return

        logger.info(
            "Stopping agent instance: "
            f"{sanitize_log_value(self.agent_id)} (final={final})",
        )

        # Stop all services via ServiceManager (handles reuse automatically)
        await self._service_manager.stop_all(
            final=final,
            preserve_reused=preserve_reused,
        )

        if self._harness_runtime is not None:
            await self._harness_runtime.stop()
            self._harness_runtime = None

        self._started = False
        self._start_attempted = False
        logger.info(
            f"Workspace stopped: {sanitize_log_value(self.agent_id)}",
        )

    def __repr__(self) -> str:
        """String representation of workspace."""
        status = "started" if self._started else "stopped"
        return (
            f"Workspace(id={self.agent_id}, "
            f"workspace={self.workspace_dir}, "
            f"status={status})"
        )
