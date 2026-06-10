# -*- coding: utf-8 -*-
"""Per-request agent construction.

Each request builds a fresh QwenPawAgent. State continuity is handled by
session load/save in stream_query, not by caching agent instances.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_agent(
    session_id: str,
    agent_id: str | None = None,
    workspace_dir: Any = None,
    mcp_clients: list | None = None,
    request_context: dict[str, str] | None = None,
    memory_manager: Any = None,
    context_manager: Any = None,
) -> Any:
    """Construct a fully-wired :class:`QwenPawAgent` for one request.

    Validates that an active model is configured before building.

    Raises:
        RuntimeError: When no active model is configured for the resolved
            agent or globally.
    """
    from ..agents.context.light_context_manager import LightContextManager
    from ..agents.react_agent import QwenPawAgent
    from ..config.config import load_agent_config
    from ..constant import WORKING_DIR
    from ..providers.provider_manager import ProviderManager

    resolved_agent_id = agent_id or "default"
    agent_config = load_agent_config(resolved_agent_id)

    # Validate model availability before heavy construction.
    active = agent_config.active_model
    if not (active and active.provider_id and active.model):
        active = ProviderManager.get_instance().get_active_model()
    if active is None or not active.provider_id or not active.model:
        raise RuntimeError(
            "No active model configured; pick one in the UI",
        )

    ctx_working_dir = str(workspace_dir) if workspace_dir else str(WORKING_DIR)
    if context_manager is None:
        context_manager = LightContextManager(
            working_dir=ctx_working_dir,
            agent_id=resolved_agent_id,
        )

    ctx = dict(request_context or {})
    ctx.setdefault("session_id", session_id)
    ctx.setdefault("agent_id", resolved_agent_id)
    ctx.setdefault("channel", "console")

    # Build environment context (time, session, working dir, OS, etc.)
    # so the agent's system prompt includes runtime awareness.
    import os
    import sys
    from ..app.runner.utils import build_env_context

    _cm = getattr(agent_config, "coding_mode", None)
    _project_dir = (
        _cm.project_dir if _cm and getattr(_cm, "project_dir", None) else None
    )

    _configured_shell = getattr(
        getattr(agent_config, "running", None),
        "shell_command_executable",
        None,
    )
    _default_shell = (
        _configured_shell
        or os.environ.get("SHELL")
        or ("cmd.exe" if sys.platform == "win32" else "/bin/sh")
    )

    env_context = build_env_context(
        session_id=session_id,
        user_id=ctx.get("user_id"),
        user_name=ctx.get("user_name"),
        channel=ctx.get("channel"),
        working_dir=ctx_working_dir,
        default_shell=_default_shell,
        project_dir=_project_dir,
    )

    agent = QwenPawAgent(
        agent_config=agent_config,
        env_context=env_context,
        workspace_dir=workspace_dir,
        request_context=ctx,
        memory_manager=memory_manager,
        context_manager=context_manager,
        mcp_clients=mcp_clients,
    )
    logger.info(
        "agent_factory: built agent for session=%s agent=%s "
        "provider=%s model=%s tools=%d",
        session_id,
        resolved_agent_id,
        active.provider_id,
        active.model,
        len(agent.toolkit.tool_groups[0].tools),
    )
    return agent
