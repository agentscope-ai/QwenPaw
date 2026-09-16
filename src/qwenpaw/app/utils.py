# -*- coding: utf-8 -*-
"""Utility functions for app routers."""

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from fastapi import HTTPException

from ..config.config import load_agent_config

if TYPE_CHECKING:
    from fastapi import Request
    from .multi_agent_manager import MultiAgentManager


class RunningConfigRuntimeStatus(BaseModel):
    """运行配置相对当前 Agent 进程的应用状态。"""

    state: Literal["applied", "pending_reload"]


class AgentReloadSummary(BaseModel):
    """全局模型变更后继承型 Agent 的运行态应用摘要。"""

    applied_agent_ids: list[str]
    pending_reload_agent_ids: list[str]


async def reload_inherited_agents(request: "Request") -> AgentReloadSummary:
    """只重载当前已加载且跟随全局模型的 Agent。"""
    manager: "MultiAgentManager" | None = getattr(
        request.app.state,
        "multi_agent_manager",
        None,
    )
    if manager is None:
        return AgentReloadSummary(
            applied_agent_ids=[],
            pending_reload_agent_ids=[],
        )

    applied: list[str] = []
    pending: list[str] = []
    for agent_id in sorted(manager.agents):
        try:
            agent_config = load_agent_config(agent_id)
        except Exception as exc:  # noqa: BLE001 - 全局模型已经持久化
            logger.warning(
                "Cannot inspect loaded agent '%s' for model reload: %s",
                agent_id,
                exc,
                exc_info=True,
            )
            pending.append(agent_id)
            continue
        if agent_config.active_model is not None:
            continue
        try:
            if await manager.reload_agent(agent_id):
                applied.append(agent_id)
            else:
                pending.append(agent_id)
        except Exception as exc:  # noqa: BLE001 - 全局模型已经持久化
            logger.warning(
                "Inherited agent reload failed for '%s': %s",
                agent_id,
                exc,
                exc_info=True,
            )
            pending.append(agent_id)
    return AgentReloadSummary(
        applied_agent_ids=applied,
        pending_reload_agent_ids=pending,
    )


def get_agent_reload_status(
    request: "Request",
    agent_id: str,
) -> RunningConfigRuntimeStatus:
    """读取当前进程内的运行配置重载状态。"""
    statuses = getattr(
        request.app.state,
        "running_config_reload_statuses",
        {},
    )
    raw = statuses.get(agent_id, {"state": "applied"})
    return RunningConfigRuntimeStatus.model_validate(raw)


async def reload_agent_and_track(
    request: "Request",
    agent_id: str,
) -> RunningConfigRuntimeStatus:
    """同步重载 Agent，并记录配置是否仍待应用。"""
    statuses = getattr(
        request.app.state,
        "running_config_reload_statuses",
        None,
    )
    if statuses is None:
        statuses = {}
        request.app.state.running_config_reload_statuses = statuses

    manager: "MultiAgentManager" = getattr(
        request.app.state,
        "multi_agent_manager",
        None,
    )
    state: Literal["applied", "pending_reload"] = "pending_reload"
    if manager is not None:
        try:
            if await manager.reload_agent(agent_id):
                state = "applied"
        except Exception as exc:  # noqa: BLE001 - persistence already succeeded
            logger.warning(
                "Runtime reload failed for saved agent config '%s': %s",
                agent_id,
                exc,
                exc_info=True,
            )
    status = RunningConfigRuntimeStatus(state=state)
    statuses[agent_id] = status.model_dump()
    return status

logger = logging.getLogger(__name__)


def safe_join(root: Path, user_path: str) -> Path:
    """Resolve *user_path* under *root* and reject path-traversal attempts.

    Uses :py:meth:`Path.is_relative_to` instead of string-prefix
    matching, which is vulnerable to sibling-directory bypasses
    (``/foo/bar2/...`` would prefix-match ``/foo/bar``).

    Args:
        root: Trusted base directory (assumed already resolved).
        user_path: Untrusted relative path provided by the caller.

    Returns:
        The resolved absolute target path.

    Raises:
        HTTPException(400): When the resolved target falls outside
            *root*.
    """
    root_resolved = root.resolve()
    target = (root_resolved / user_path).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Path traversal not allowed",
        ) from exc
    return target


def safe_project_dest(base: Path, name: str) -> Path:
    """Build a project destination directory under *base* from *name*.

    Validates that *name* is a single path component (no separators,
    not ``.``/``..``, no NUL) and that the resolved destination stays
    inside *base*. Permissive on character set so user folders with
    spaces or non-ASCII names still work.

    Args:
        base: Parent directory where projects live (e.g.
            ``coding_projects/``).
        name: Untrusted folder name.

    Returns:
        Resolved destination path inside *base*.

    Raises:
        HTTPException(400): When *name* is empty, contains a path
            separator, equals ``.``/``..``, or escapes *base*.
    """
    cleaned = (name or "").strip()
    if (
        not cleaned
        or cleaned in (".", "..")
        or "/" in cleaned
        or "\\" in cleaned
        or "\x00" in cleaned
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid project name: {name!r}",
        )
    base_resolved = base.resolve()
    dest = (base_resolved / cleaned).resolve()
    try:
        dest.relative_to(base_resolved)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Project name escapes coding_projects/",
        ) from exc
    return dest


def schedule_agent_reload(request: "Request", agent_id: str) -> None:
    """Schedule an agent reload in background (non-blocking).

    This is a common pattern used across multiple endpoints to reload
    agent configuration after making changes. The reload happens
    asynchronously without blocking the API response.

    IMPORTANT: This function extracts manager and agent_id from the
    request context before creating the background task, to avoid
    accessing request/workspace objects after their lifecycle ends.

    Args:
        request: FastAPI request object (must have multi_agent_manager)
        agent_id: Agent ID to reload

    Example:
        >>> from qwenpaw.app.utils import schedule_agent_reload
        >>> save_agent_config(workspace.agent_id, agent_config)
        >>> schedule_agent_reload(request, workspace.agent_id)
    """
    # Extract manager before creating background task (defensive)
    manager: "MultiAgentManager" = getattr(
        request.app.state,
        "multi_agent_manager",
        None,
    )

    if manager is None:
        logger.warning(
            f"Cannot schedule agent reload for '{agent_id}': "
            "MultiAgentManager not initialized in app state",
        )
        return

    async def reload_in_background():
        try:
            await manager.reload_agent(agent_id)
        except Exception as e:
            logger.warning(
                f"Background reload failed for agent '{agent_id}': {e}",
                exc_info=True,
            )

    asyncio.create_task(reload_in_background())


def check_upload_size(data: bytes) -> None:
    """Raise HTTP 400 if *data* exceeds the configured upload size limit.

    Reads ``UPLOAD_MAX_SIZE_MB`` from ``constant.py``; when ``None``
    (the default), no check is performed.
    """
    from ..constant import UPLOAD_MAX_SIZE_MB

    if UPLOAD_MAX_SIZE_MB is None:
        return
    max_bytes = UPLOAD_MAX_SIZE_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File too large ({len(data) // (1024 * 1024)} MB). "
                f"Maximum is {UPLOAD_MAX_SIZE_MB} MB."
            ),
        )
