# -*- coding: utf-8 -*-
"""Workspace: Encapsulates a complete independent agent runtime.

Each Workspace represents a standalone agent workspace with its own:
- Runner (request processing)
- ChannelManager (communication channels)
- MemoryManager (conversation memory)
- MCPClientManager (MCP tool clients)
- CronManager (scheduled tasks)

All existing single-agent components are reused without modification.
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from .runner import AgentRunner
from .channels.utils import make_process_from_runner
from .mcp import MCPClientManager
from .crons.manager import CronManager
from .crons.repo.json_repo import JsonJobRepository
from ..agents.memory import MemoryManager
from ..config.config import load_agent_config, AgentsRunningConfig

if TYPE_CHECKING:
    from .channels.base import BaseChannel

logger = logging.getLogger(__name__)


class Workspace:
    """Single agent workspace with complete runtime components.

    Each Workspace is an independent agent instance with its own:
    - Runner: Processes agent requests
    - ChannelManager: Manages communication channels
    - MemoryManager: Manages conversation memory
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

        # All components are None until start() is called (lazy loading)
        self._runner: Optional[AgentRunner] = None
        self._channel_manager: Optional["BaseChannel"] = None
        self._memory_manager: Optional[MemoryManager] = None
        self._mcp_manager: Optional[MCPClientManager] = None
        self._cron_manager: Optional["CronManager"] = None
        self._chat_manager = None
        self._config = None
        self._config_watcher = None
        self._mcp_config_watcher = None
        self._started = False

        logger.debug(
            f"Created Workspace: {agent_id} at {self.workspace_dir}",
        )

    @property
    def runner(self) -> Optional[AgentRunner]:
        """Get runner instance."""
        return self._runner

    @property
    def channel_manager(self) -> Optional["BaseChannel"]:
        """Get channel manager instance."""
        return self._channel_manager

    @property
    def memory_manager(self) -> Optional[MemoryManager]:
        """Get memory manager instance."""
        return self._memory_manager

    @property
    def mcp_manager(self) -> Optional[MCPClientManager]:
        """Get MCP client manager instance."""
        return self._mcp_manager

    @property
    def cron_manager(self) -> Optional["CronManager"]:
        """Get cron manager instance."""
        return self._cron_manager

    @property
    def chat_manager(self):
        """Get chat manager instance."""
        return self._chat_manager

    @property
    def config(self):
        """Get agent configuration."""
        if self._config is None:
            self._config = load_agent_config(self.agent_id)
        return self._config

    async def start(self):  # pylint: disable=too-many-statements
        """Start workspace and initialize all components concurrently."""
        if self._started:
            logger.debug(f"Workspace already started: {self.agent_id}")
            return

        logger.info(f"Starting workspace: {self.agent_id}")

        try:
            # 1. Load agent configuration from workspace/agent.json
            self._config = load_agent_config(self.agent_id)
            agent_config = self._config
            logger.debug(f"Loaded config for agent: {self.agent_id}")

            # 2. Create Runner
            self._runner = AgentRunner(
                agent_id=self.agent_id,
                workspace_dir=self.workspace_dir,
            )

            # 3. Concurrently initialize MemoryManager and MCPManager
            # IMPORTANT: Create MemoryManager BEFORE runner.start() to prevent
            # init_handler from creating a duplicate MemoryManager
            async def init_memory():
                # Get running config for memory manager
                running_config = agent_config.running

                if running_config is None:
                    running_config = AgentsRunningConfig()

                self._memory_manager = MemoryManager(
                    working_dir=str(self.workspace_dir),
                    max_input_length=running_config.max_input_length,
                    memory_compact_ratio=running_config.memory_compact_ratio,
                    memory_reserve_ratio=running_config.memory_reserve_ratio,
                    language=agent_config.language,
                )
                # Assign to runner BEFORE starting runner
                self._runner.memory_manager = self._memory_manager
                await self._memory_manager.start()
                logger.debug(
                    f"MemoryManager started for agent: {self.agent_id}",
                )

            async def init_mcp():
                self._mcp_manager = MCPClientManager()
                if agent_config.mcp:
                    try:
                        await self._mcp_manager.init_from_config(
                            agent_config.mcp,
                        )
                        logger.debug(
                            f"MCP clients initialized for agent: "
                            f"{self.agent_id}",
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to initialize MCP for agent "
                            f"{self.agent_id}: {e}",
                        )
                self._runner.set_mcp_manager(self._mcp_manager)

            async def init_chat():
                from .runner.manager import ChatManager
                from .runner.repo.json_repo import JsonChatRepository

                chats_path = str(self.workspace_dir / "chats.json")
                chat_repo = JsonChatRepository(chats_path)
                self._chat_manager = ChatManager(repo=chat_repo)
                self._runner.set_chat_manager(self._chat_manager)
                logger.info(
                    f"ChatManager started for agent {self.agent_id}: "
                    f"chats.json={chats_path}",
                )

            # Run Memory, MCP, and Chat initialization concurrently
            await asyncio.gather(init_memory(), init_mcp(), init_chat())

            # Now start the runner (after MemoryManager is set)
            await self._runner.start()
            logger.debug(f"Runner started for agent: {self.agent_id}")

            # Set up restart callback for /daemon restart command
            from .workspace_restart import create_restart_callback

            setattr(
                self._runner,
                "_restart_callback",
                create_restart_callback(self),
            )

            # 4. Start ChannelManager (depends on Runner)
            if agent_config.channels:
                from ..config import Config, update_last_dispatch
                from .channels.manager import ChannelManager

                temp_config = Config(channels=agent_config.channels)

                self._channel_manager = ChannelManager.from_config(
                    process=make_process_from_runner(self._runner),
                    config=temp_config,
                    on_last_dispatch=update_last_dispatch,
                    workspace_dir=self.workspace_dir,
                )
                await self._channel_manager.start_all()
                logger.debug(
                    f"ChannelManager started for agent: {self.agent_id}",
                )

            # 5. Start CronManager (always create for API access)
            job_repo = JsonJobRepository(
                str(self.workspace_dir / "jobs.json"),
            )
            self._cron_manager = CronManager(
                repo=job_repo,
                runner=self._runner,
                channel_manager=self._channel_manager,
                timezone="UTC",
            )
            # Only start background tasks if heartbeat is enabled
            if agent_config.heartbeat and agent_config.heartbeat.enabled:
                await self._cron_manager.start()
                logger.debug(
                    f"CronManager started with heartbeat: {self.agent_id}",
                )
            else:
                logger.debug(
                    f"CronManager created (heartbeat disabled): "
                    f"{self.agent_id}",
                )

            # 6. Start config watchers for hot-reload (non-blocking)
            await self._start_config_watchers()

            self._started = True
            logger.info(
                f"Workspace started successfully: {self.agent_id}",
            )

        except Exception as e:
            logger.error(
                f"Failed to start agent instance {self.agent_id}: {e}",
            )
            # Clean up partially started components
            await self.stop()
            raise

    async def stop(self):
        """Stop agent instance and clean up all resources."""
        if not self._started:
            logger.debug(f"Workspace not started: {self.agent_id}")
            return

        logger.info(f"Stopping agent instance: {self.agent_id}")

        # Stop components in reverse order

        # 0. Stop config watchers first
        await self._stop_config_watchers()

        # 1. Stop CronManager
        if self._cron_manager:
            try:
                await self._cron_manager.stop()
                logger.debug(
                    f"CronManager stopped for agent: {self.agent_id}",
                )
            except Exception as e:
                logger.warning(
                    f"Error stopping CronManager for agent "
                    f"{self.agent_id}: {e}",
                )

        # 2. Stop ChannelManager
        if self._channel_manager:
            try:
                await self._channel_manager.stop_all()
                logger.debug(
                    f"ChannelManager stopped for agent: {self.agent_id}",
                )
            except Exception as e:
                logger.warning(
                    f"Error stopping ChannelManager for agent "
                    f"{self.agent_id}: {e}",
                )

        # 3. Stop MCPClientManager
        if self._mcp_manager:
            try:
                await self._mcp_manager.close_all()
                logger.debug(
                    f"MCPClientManager stopped for agent: " f"{self.agent_id}",
                )
            except Exception as e:
                logger.warning(
                    f"Error stopping MCPClientManager for agent "
                    f"{self.agent_id}: {e}",
                )

        # 4. Stop MemoryManager
        if self._memory_manager:
            try:
                await self._memory_manager.close()
                logger.debug(
                    f"MemoryManager stopped for agent: " f"{self.agent_id}",
                )
            except Exception as e:
                logger.warning(
                    f"Error stopping MemoryManager for agent "
                    f"{self.agent_id}: {e}",
                )

        # 5. Clear ChatManager reference (no stop method)
        if self._chat_manager:
            self._chat_manager = None
            logger.debug(
                f"ChatManager cleared for agent: {self.agent_id}",
            )

        # 6. Stop Runner
        if self._runner:
            try:
                await self._runner.stop()
                logger.debug(f"Runner stopped for agent: {self.agent_id}")
            except Exception as e:
                logger.warning(
                    f"Error stopping Runner for agent {self.agent_id}: {e}",
                )

        self._started = False
        logger.info(f"Workspace stopped: {self.agent_id}")

    async def reload(self):
        """Reload agent instance (stop and start with fresh configuration)."""
        logger.info(f"Reloading agent instance: {self.agent_id}")
        self._config = None  # Clear cached config
        await self.stop()
        await self.start()
        logger.info(f"Agent instance reloaded: {self.agent_id}")

    async def _start_config_watchers(self):
        """Start config watchers for hot-reload of agent.json changes."""
        try:
            # Start AgentConfigWatcher for channels and heartbeat
            if self._channel_manager or self._cron_manager:
                from .agent_config_watcher import AgentConfigWatcher

                self._config_watcher = AgentConfigWatcher(
                    agent_id=self.agent_id,
                    workspace_dir=self.workspace_dir,
                    channel_manager=self._channel_manager,
                    cron_manager=self._cron_manager,
                )
                await self._config_watcher.start()

            # Start MCPConfigWatcher for MCP client hot-reload
            if self._mcp_manager:
                from .mcp.watcher import MCPConfigWatcher

                def mcp_config_loader():
                    """Load MCP config from agent.json."""
                    agent_config = load_agent_config(self.agent_id)
                    return agent_config.mcp

                self._mcp_config_watcher = MCPConfigWatcher(
                    mcp_manager=self._mcp_manager,
                    config_loader=mcp_config_loader,
                    config_path=self.workspace_dir / "agent.json",
                )
                await self._mcp_config_watcher.start()

        except Exception as e:
            logger.warning(
                f"Failed to start config watchers for agent "
                f"{self.agent_id}: {e}",
            )

    async def _stop_config_watchers(self):
        """Stop config watchers."""
        if self._config_watcher:
            try:
                await self._config_watcher.stop()
            except Exception as e:
                logger.warning(
                    f"Error stopping AgentConfigWatcher for agent "
                    f"{self.agent_id}: {e}",
                )
            self._config_watcher = None

        if self._mcp_config_watcher:
            try:
                await self._mcp_config_watcher.stop()
            except Exception as e:
                logger.warning(
                    f"Error stopping MCPConfigWatcher for agent "
                    f"{self.agent_id}: {e}",
                )
            self._mcp_config_watcher = None

    def __repr__(self) -> str:
        """String representation of workspace."""
        status = "started" if self._started else "stopped"
        return (
            f"Workspace(id={self.agent_id}, "
            f"workspace={self.workspace_dir}, "
            f"status={status})"
        )
