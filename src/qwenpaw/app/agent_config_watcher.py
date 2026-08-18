"""Watch agent.json and trigger a graceful workspace reload on change.

Only watches channels, heartbeat, mcp.clients and skills sections.
Other runtime bookkeeping (like last_dispatch) won't trigger reloads.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from ..config.config import load_agent_config

if TYPE_CHECKING:
    from ..config.config import HeartbeatConfig
    from .workspace.workspace import Workspace

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 2.0


def _hash(obj: Any) -> Optional[int]:
    if obj is None:
        return None
    return hash(str(obj.model_dump(mode="json")))


def _channels_hash(channels: Any) -> Optional[int]:
    return _hash(channels)


def _heartbeat_hash(hb: Optional["HeartbeatConfig"]) -> int:
    if hb is None:
        return hash("None")
    return _hash(hb)


def _mcp_hash(mcp: Any) -> Optional[int]:
    if mcp is None:
        return None
    try:
        clients = getattr(mcp, "clients", None)
        if clients is not None:
            return hash(str(clients))
    except Exception:
        pass
    try:
        return hash(str(mcp.model_dump(mode="json")))
    except Exception:
        return hash(str(mcp))


def _skills_hash(skills: Any) -> Optional[int]:
    if skills is None:
        return None
    try:
        return hash(str(skills.model_dump(mode="json")))
    except Exception:
        return hash(str(skills))


class AgentConfigWatcher:
    def __init__(
        self,
        agent_id: str,
        workspace_dir: Path,
        workspace: "Workspace",
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ):
        self._agent_id = agent_id
        self._workspace_dir = workspace_dir
        self._config_path = workspace_dir / "agent.json"
        self._workspace = workspace
        self._poll_interval = poll_interval
        self._task: Optional[asyncio.Task] = None

        self._last_mtime: float = 0.0
        self._last_channels_hash: Optional[int] = None
        self._last_heartbeat_hash: Optional[int] = None
        self._last_mcp_hash: Optional[int] = None
        self._last_skills_hash: Optional[int] = None

        self._disabled: bool = False

    async def start(self) -> None:
        self._snapshot()
        self._task = asyncio.create_task(
            self._poll_loop(),
            name=f"agent_config_watcher_{self._agent_id}",
        )
        logger.info(
            f"AgentConfigWatcher started for agent {self._agent_id} "
            f"(poll={self._poll_interval}s, path={self._config_path})",
        )

    async def stop(self) -> None:
        if self._disabled:
            return
        self._disabled = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(f"AgentConfigWatcher stopped for agent {self._agent_id}")

    def _read_mtime(self) -> float:
        try:
            return self._config_path.stat().st_mtime
        except FileNotFoundError:
            return 0.0

    def _snapshot(self) -> None:
        self._last_mtime = self._read_mtime()
        try:
            agent_config = load_agent_config(self._agent_id)
        except Exception:
            logger.exception(
                f"AgentConfigWatcher ({self._agent_id}): failed to load config",
            )
            return
        self._last_channels_hash = _channels_hash(
            getattr(agent_config, "channels", None),
        )
        self._last_heartbeat_hash = _heartbeat_hash(
            getattr(agent_config, "heartbeat", None),
        )
        self._last_mcp_hash = _mcp_hash(
            getattr(agent_config, "mcp", None),
        )
        self._last_skills_hash = _skills_hash(
            getattr(agent_config, "skills", None),
        )

    def _resolve_manager(self):
        return getattr(self._workspace, "_manager", None)

    async def _poll_loop(self) -> None:
        while not self._disabled:
            try:
                await asyncio.sleep(self._poll_interval)
                if self._disabled:
                    break
                await self._check()
            except Exception:
                logger.exception(
                    f"AgentConfigWatcher ({self._agent_id}): poll failed",
                )

    async def _check(self) -> None:
        mtime = self._read_mtime()
        if mtime == self._last_mtime:
            return
        self._last_mtime = mtime

        try:
            agent_config = load_agent_config(self._agent_id)
        except Exception:
            logger.exception(
                f"AgentConfigWatcher ({self._agent_id}): failed to parse",
            )
            return

        new_channels_hash = _channels_hash(
            getattr(agent_config, "channels", None),
        )
        new_heartbeat_hash = _heartbeat_hash(
            getattr(agent_config, "heartbeat", None),
        )
        new_mcp_hash = _mcp_hash(
            getattr(agent_config, "mcp", None),
        )
        new_skills_hash = _skills_hash(
            getattr(agent_config, "skills", None),
        )

        changed = any([
            new_channels_hash != self._last_channels_hash,
            new_heartbeat_hash != self._last_heartbeat_hash,
            new_mcp_hash != self._last_mcp_hash,
            new_skills_hash != self._last_skills_hash,
        ])

        self._last_channels_hash = new_channels_hash
        self._last_heartbeat_hash = new_heartbeat_hash
        self._last_mcp_hash = new_mcp_hash
        self._last_skills_hash = new_skills_hash

        if not changed:
            return

        manager = self._resolve_manager()
        if manager is None:
            logger.warning(
                f"AgentConfigWatcher ({self._agent_id}): "
                f"config changed but manager not attached; skipping reload",
            )
            return

        self._disabled = True
        logger.info(
            f"AgentConfigWatcher ({self._agent_id}): "
            f"config changed, reloading "
            f"(channels, heartbeat, mcp, skills)",
        )
        try:
            await manager.reload_agent(self._agent_id)
        except Exception:
            logger.exception(
                f"AgentConfigWatcher ({self._agent_id}): reload_agent failed",
            )
