# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2024 2019-2024 The MCP OpenCode Agents Authors
# SPDX-License-Identifier: MIT

"""JSON storage layer for SACP agents."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models.sacp_agent import (
    SACPAgentConfig,
    SACPAgentsStorage,
    CreateSACPAgentRequest,
    UpdateSACPAgentRequest,
)

logger = logging.getLogger(__name__)


def _lock_ex(f) -> None:
    """Acquire exclusive file lock (cross-platform)."""
    try:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    except ImportError:
        import msvcrt

        msvcrt.locking(
            f.fileno(),
            msvcrt.LK_NBLCK,
            os.path.getsize(f.name) or 1,
        )


def _lock_sh(f) -> None:
    """Acquire shared file lock (cross-platform)."""
    try:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
    except ImportError:
        # Windows: skip shared lock; reads are safe without it
        pass


def _unlock(f) -> None:
    """Release file lock (cross-platform)."""
    try:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except ImportError:
        try:
            import msvcrt

            msvcrt.locking(
                f.fileno(),
                msvcrt.LK_UNLCK,
                os.path.getsize(f.name) or 1,
            )
        except Exception:
            pass


class SACPAgentsRepository:
    """JSON file-based repository for SACP agents.

    Reads from / writes to ``~/.qwenpaw/sacp_agents.json``.
    """

    def __init__(self) -> None:
        self._storage_path: Path = Path.home() / ".qwenpaw" / "sacp_agents.json"

    # -------------------------------------------------------------------------
    # Core persistence
    # -------------------------------------------------------------------------

    def load(self) -> SACPAgentsStorage:
        """Load agents from the JSON storage file.

        If the file does not exist, creates it with the default structure.

        Returns:
            SACPAgentsStorage: the loaded storage model
        """
        if not self._storage_path.exists():
            storage = SACPAgentsStorage()
            self.save(storage)
            return storage

        with open(self._storage_path, "r", encoding="utf-8") as f:
            _lock_sh(f)
            try:
                data = json.load(f)
            finally:
                _unlock(f)

        return SACPAgentsStorage.model_validate(data)

    def save(self, storage: SACPAgentsStorage) -> None:
        """Write the given storage to the JSON file.

        Args:
            storage: the storage model to persist
        """
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._storage_path, "w", encoding="utf-8") as f:
            _lock_ex(f)
            try:
                json.dump(
                    storage.model_dump(mode="json"),
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            finally:
                _unlock(f)

    # -------------------------------------------------------------------------
    # CRUD operations
    # -------------------------------------------------------------------------

    def create(self, req: CreateSACPAgentRequest) -> SACPAgentConfig:
        """Create a new agent and persist it.

        Args:
            req: the creation request

        Returns:
            SACPAgentConfig: the created agent config
        """
        import uuid

        now = datetime.utcnow()
        agent = SACPAgentConfig(
            id=str(uuid.uuid4()),
            name=req.name,
            description=req.description,
            url=req.url,
            auth_key=req.auth_key,
            is_internal=req.is_internal,
            internal_agent_id=req.internal_agent_id,
            health_check_enabled=req.health_check_enabled,
            health_check_interval=req.health_check_interval,
            created_at=now,
            updated_at=now,
        )
        storage = self.load()
        storage.agents.append(agent)
        self.save(storage)
        return agent

    def update(
        self,
        agent_id: str,
        req: UpdateSACPAgentRequest,
    ) -> Optional[SACPAgentConfig]:
        """Update an existing agent.

        Args:
            agent_id: the ID of the agent to update
            req: the update request

        Returns:
            SACPAgentConfig | None: the updated agent, or None if not found
        """
        storage = self.load()
        for agent in storage.agents:
            if agent.id == agent_id:
                update_data = req.model_dump(exclude_unset=True)
                for field, value in update_data.items():
                    if value is not None:
                        setattr(agent, field, value)
                agent.updated_at = datetime.utcnow()
                self.save(storage)
                return agent
        return None

    def delete(self, agent_id: str) -> bool:
        """Delete an agent by ID.

        Args:
            agent_id: the ID of the agent to delete

        Returns:
            bool: True if the agent was deleted, False if not found
        """
        storage = self.load()
        original_len = len(storage.agents)
        storage.agents = [a for a in storage.agents if a.id != agent_id]
        if len(storage.agents) == original_len:
            return False
        self.save(storage)
        return True

    # -------------------------------------------------------------------------
    # Query operations
    # -------------------------------------------------------------------------

    def list_agents(self) -> list[SACPAgentConfig]:
        """Return all stored agents.

        Returns:
            list[SACPAgentConfig]: list of all agents
        """
        storage = self.load()
        return list(storage.agents)

    def get_agent(self, agent_id: str) -> Optional[SACPAgentConfig]:
        """Return a specific agent by ID.

        Args:
            agent_id: the ID of the agent to retrieve

        Returns:
            SACPAgentConfig | None: the agent, or None if not found
        """
        storage = self.load()
        for agent in storage.agents:
            if agent.id == agent_id:
                return agent
        return None
