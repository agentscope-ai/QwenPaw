# -*- coding: utf-8 -*-
"""MultiAgentManager: Manages multiple agent workspaces with lazy loading.

Provides centralized management for multiple Workspace objects,
including lazy loading, lifecycle management, and hot reloading.
"""
import asyncio
import logging
from typing import Dict

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
    """

    def __init__(self):
        """Initialize multi-agent manager."""
        self.agents: Dict[str, Workspace] = {}
        self._lock = asyncio.Lock()
        logger.debug("MultiAgentManager initialized")

    async def get_agent(self, agent_id: str) -> Workspace:
        """Get agent workspace by ID (lazy loading).

        If workspace doesn't exist in memory, it will be created and started.
        Thread-safe using async lock.

        Args:
            agent_id: Agent ID to retrieve

        Returns:
            Workspace: The requested workspace instance

        Raises:
            ValueError: If agent ID not found in configuration
        """
        async with self._lock:
            # Return existing agent if already loaded
            if agent_id in self.agents:
                logger.debug(f"Returning cached agent: {agent_id}")
                return self.agents[agent_id]

            # Load configuration to get agent reference
            config = load_config()

            if agent_id not in config.agents.profiles:
                raise ValueError(
                    f"Agent '{agent_id}' not found in configuration. "
                    f"Available agents: {list(config.agents.profiles.keys())}",
                )

            agent_ref = config.agents.profiles[agent_id]

            # Create and start new workspace
            logger.info(f"Creating new workspace: {agent_id}")
            instance = Workspace(
                agent_id=agent_id,
                workspace_dir=agent_ref.workspace_dir,
            )

            try:
                await instance.start()
                self.agents[agent_id] = instance
                logger.info(f"Workspace created and started: {agent_id}")
                return instance
            except Exception as e:
                logger.error(f"Failed to start workspace {agent_id}: {e}")
                raise

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
        3. Stopping the old instance after the new one is serving (no lock)

        The lock is only held during the atomic swap to minimize blocking
        time for other agent operations.

        This ensures that:
        - Ongoing chat requests continue using the old instance
        - Other agents remain accessible during reload
        - The manager stays responsive

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

        try:
            await new_instance.start()
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

        # Step 5: Stop old instance (outside lock)
        # If this fails, new instance is already serving, so we still succeed
        try:
            await old_instance.stop()
            logger.info(
                f"Old workspace instance stopped: {agent_id}. "
                f"Zero-downtime reload completed.",
            )
        except Exception as e:
            logger.warning(
                f"Failed to stop old workspace instance for {agent_id}: {e}. "
                f"New instance is active and serving requests.",
            )
            # This is not a fatal error - new instance is already active

        return True

    async def stop_all(self):
        """Stop all agent instances.

        Called during application shutdown to clean up resources.
        """
        logger.info(f"Stopping all agents ({len(self.agents)} running)...")

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

    async def start_all_configured_agents(self) -> dict[str, bool]:
        """Start all agents defined in configuration concurrently.

        This method loads the current configuration and starts all
        configured agents in parallel for optimal performance.

        Returns:
            dict[str, bool]: Mapping of agent_id to success status
        """
        config = load_config()
        agent_ids = list(config.agents.profiles.keys())

        if not agent_ids:
            logger.warning("No agents configured in config")
            return {}

        logger.info(f"Starting {len(agent_ids)} configured agent(s)")

        async def start_single_agent(agent_id: str) -> tuple[str, bool]:
            """Start a single agent with error handling."""
            try:
                logger.info(f"Starting agent: {agent_id}")
                await self.preload_agent(agent_id)
                logger.info(f"Agent started successfully: {agent_id}")
                return (agent_id, True)
            except Exception as e:
                logger.error(
                    f"Failed to start agent {agent_id}: {e}. "
                    f"Continuing with other agents...",
                )
                return (agent_id, False)

        # Start all agents concurrently
        results = await asyncio.gather(
            *[start_single_agent(agent_id) for agent_id in agent_ids],
            return_exceptions=False,
        )

        # Build result mapping
        result_map = dict(results)
        success_count = sum(1 for success in result_map.values() if success)
        logger.info(
            f"Agent startup complete: {success_count}/{len(agent_ids)} "
            f"agents started successfully",
        )

        return result_map

    def __repr__(self) -> str:
        """String representation of manager."""
        loaded = list(self.agents.keys())
        return f"MultiAgentManager(loaded_agents={loaded})"
