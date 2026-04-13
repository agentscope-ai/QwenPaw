# -*- coding: utf-8 -*-
"""Workspace: Encapsulates a complete independent agent runtime.

Each Workspace represents a standalone agent workspace with its own:
- Runner (request processing)
- ChannelManager (communication channels)
- BaseMemoryManager (conversation memory)
- MCPClientManager (MCP tool clients)
- CronManager (scheduled tasks)

All existing single-agent components are reused without modification.
"""
import logging
from pathlib import Path
from typing import Optional
from agentscope_runtime.engine.schemas.exception import ConfigurationException

from .service_manager import ServiceDescriptor, ServiceManager
from .service_factories import (
    create_mcp_service,
    create_chat_service,
    create_channel_service,
    create_agent_config_watcher,
    create_mcp_config_watcher,
    create_backup_service,
)
from ..runner import AgentRunner
from ..runner.task_tracker import TaskTracker
from ..mcp import MCPClientManager
from ..crons.manager import CronManager
from ..crons.repo.json_repo import JsonJobRepository
from ...config.config import load_agent_config

logger = logging.getLogger(__name__)


def _resolve_memory_class(backend: str) -> type:
    """Return the memory manager class for the given backend name."""
    from ...agents.memory import ReMeLightMemoryManager

    if backend == "remelight":
        return ReMeLightMemoryManager
    raise ConfigurationException(
        message=f"Unsupported memory manager backend: '{backend}'",
    )


class Workspace:
    """Single agent workspace with complete runtime components.

    Each Workspace is an independent agent instance with its own:
    - Runner: Processes agent requests
    - ChannelManager: Manages communication channels
    - BaseMemoryManager: Manages conversation memory
    - MCPClientManager: Manages MCP tool clients
    - CronManager: Manages scheduled tasks

    All components use existing single-agent code without modification.
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

        # Service manager (unified component management)
        self._service_manager = ServiceManager(self)

        # Non-service state
        self._config = None  # Loaded before start()
        self._started = False
        self._manager = None  # Reference to MultiAgentManager
        self._task_tracker = TaskTracker()

        # Register all services
        self._register_services()

        logger.debug(
            f"Created Workspace: {agent_id} at {self.workspace_dir}",
        )

    # Service access via properties (delegates to ServiceManager)
    @property
    def runner(self) -> Optional[AgentRunner]:
        """Get runner instance from ServiceManager."""
        return self._service_manager.services.get("runner")

    @property
    def memory_manager(self):
        """Get memory manager instance from ServiceManager."""
        return self._service_manager.services.get("memory_manager")

    @property
    def mcp_manager(self):
        """Get MCP manager instance from ServiceManager."""
        return self._service_manager.services.get("mcp_manager")

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

    # Non-service state
    @property
    def task_tracker(self) -> TaskTracker:
        """Get task tracker for background chat and reconnect."""
        return self._task_tracker

    @property
    def config(self):
        """Get agent configuration."""
        if self._config is None:
            self._config = load_agent_config(self.agent_id)
        return self._config

    def set_manager(self, manager) -> None:
        """Set reference to MultiAgentManager for /daemon restart.

        Args:
            manager: MultiAgentManager instance
        """
        self._manager = manager
        # Pass to runner for /daemon restart command
        if self.runner is not None:
            self.runner._manager = manager  # pylint: disable=protected-access

    def _register_services(  # pylint: disable=too-many-statements
        self,
    ) -> None:
        """Register all workspace services with ServiceManager.

        Uses declarative ServiceDescriptor configuration to replace
        hardcoded initialization logic.
        """
        # pylint: disable=protected-access
        sm = self._service_manager

        # Priority 10: Runner
        sm.register(
            ServiceDescriptor(
                name="runner",
                service_class=AgentRunner,
                init_args=lambda ws: {
                    "agent_id": ws.agent_id,
                    "workspace_dir": ws.workspace_dir,
                    "task_tracker": ws._task_tracker,
                },
                stop_method="stop",
                priority=10,
                concurrent_init=False,
            ),
        )

        # Priority 20: Core services (concurrent)
        sm.register(
            ServiceDescriptor(
                name="memory_manager",
                service_class=lambda ws: _resolve_memory_class(
                    ws._config.running.memory_manager_backend,
                ),
                init_args=lambda ws: {
                    "working_dir": str(ws.workspace_dir),
                    "agent_id": ws.agent_id,
                },
                post_init=lambda ws, mm: setattr(
                    ws._service_manager.services["runner"],
                    "memory_manager",
                    mm,
                ),
                start_method="start",
                stop_method="close",
                reusable=True,
                priority=20,
                concurrent_init=True,
            ),
        )

        sm.register(
            ServiceDescriptor(
                name="mcp_manager",
                service_class=MCPClientManager,
                post_init=create_mcp_service,
                stop_method="close_all",
                priority=20,
                concurrent_init=True,
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

        # Priority 25: Runner start
        sm.register(
            ServiceDescriptor(
                name="runner_start",
                service_class=None,
                post_init=lambda ws, _: ws._service_manager.services[
                    "runner"
                ].start(),
                priority=25,
                concurrent_init=False,
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
                init_args=lambda ws: {  # pylint: disable=protected-access
                    "repo": JsonJobRepository(
                        str(ws.workspace_dir / "jobs.json"),
                    ),
                    "runner": ws._service_manager.services["runner"],
                    "channel_manager": ws._service_manager.services.get(
                        "channel_manager",
                    ),
                    "timezone": "UTC",
                    "agent_id": ws.agent_id,
                },
                start_method="start",
                stop_method="stop",
                priority=40,
                concurrent_init=False,
            ),
        )

        # Priority 45: Backup services
        sm.register(
            ServiceDescriptor(
                name="backup_services",
                service_class=None,
                post_init=create_backup_service,
                priority=45,
                concurrent_init=False,
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

        # Priority 51: MCP Config Watcher (conditional)
        sm.register(
            ServiceDescriptor(
                name="mcp_config_watcher",
                service_class=None,
                post_init=create_mcp_config_watcher,
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
            logger.debug(f"Workspace already started: {self.agent_id}")
            return

        logger.info(f"Starting workspace: {self.agent_id}")

        from ...agents.skills_manager import (
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
            logger.debug(f"Loaded config for agent: {self.agent_id}")

            # 2. Start all services via ServiceManager
            await self._service_manager.start_all()

            self._started = True
            logger.info(f"Workspace started successfully: {self.agent_id}")

        except Exception as e:
            logger.error(
                f"Failed to start agent instance {self.agent_id}: {e}",
            )
            # Clean up partially started components
            await self.stop()
            raise

    async def stop(self, final: bool = True):
        """Stop agent instance and clean up all resources.

        Args:
            final: If True (default), stop ALL services including reusable.
                   If False, skip reusable services (for reload scenario).
        """
        if not self._started:
            logger.debug(f"Workspace not started: {self.agent_id}")
            return

        logger.info(
            f"Stopping agent instance: {self.agent_id} (final={final})",
        )

        # Stop all services via ServiceManager (handles reuse automatically)
        await self._service_manager.stop_all(final=final)

        self._started = False
        logger.info(f"Workspace stopped: {self.agent_id}")

    def __repr__(self) -> str:
        """String representation of workspace."""
        status = "started" if self._started else "stopped"
        return (
            f"Workspace(id={self.agent_id}, "
            f"workspace={self.workspace_dir}, "
            f"status={status})"
        )
