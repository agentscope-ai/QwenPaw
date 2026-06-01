# -*- coding: utf-8 -*-
"""Per-session agent construction and caching."""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

_AGENT_CACHE: Dict[tuple, Any] = {}


def _build_qwenpaw_agent(
    session_id: str,
    agent_id: str,
    workspace_dir: Any = None,
    mcp_clients: list | None = None,
) -> Any:
    """Construct a fully-wired :class:`QwenPawAgent` for one session.

    QwenPawAgent owns its own toolkit (built via ``_create_toolkit`` from
    the agent's ``builtin_tools`` config), system prompt (assembled from
    working-dir files), and middleware registration (bootstrap +
    context-manager middlewares).  The tool-guard ASK flow works because
    ``_create_toolkit`` reads ``agent_config.id`` and wraps every tool in
    :class:`GuardedFunctionTool`.
    """
    from ..agents.context.light_context_manager import LightContextManager
    from ..agents.react_agent import QwenPawAgent
    from ..config.config import load_agent_config
    from ..constant import WORKING_DIR

    agent_config = load_agent_config(agent_id)

    ctx_working_dir = str(workspace_dir) if workspace_dir else str(WORKING_DIR)
    context_manager = LightContextManager(
        working_dir=ctx_working_dir,
        agent_id=agent_id,
    )

    agent = QwenPawAgent(
        agent_config=agent_config,
        workspace_dir=workspace_dir,
        request_context={
            "session_id": session_id,
            "agent_id": agent_id,
            "channel": "console",
        },
        memory_manager=None,
        context_manager=context_manager,
        mcp_clients=mcp_clients,
    )
    return agent


def _get_or_build_agent(
    session_id: str,
    agent_id: str | None = None,
    workspace_dir: Any = None,
    mcp_clients: list | None = None,
) -> tuple[Any, bool]:
    """Return ``(agent, is_new)`` for the active (provider, model) on this
    session — build on first use, rebuild when the active model changes.

    ``is_new`` is ``True`` when the agent was just built (not from cache);
    callers use it to decide whether to load persisted session state.
    """
    from ..config.config import load_agent_config
    from ..providers.provider_manager import ProviderManager

    resolved_agent_id = agent_id or "default"

    # Resolve the *effective* model: agent-specific first, then global.
    active = None
    try:
        agent_cfg = load_agent_config(resolved_agent_id)
        slot = agent_cfg.active_model
        if slot and slot.provider_id and slot.model:
            active = slot
    except Exception:
        pass
    if active is None:
        active = ProviderManager.get_instance().get_active_model()
    if active is None or not active.provider_id or not active.model:
        raise RuntimeError(
            "stream_query: no active model configured; pick one in the UI",
        )
    key = (session_id, resolved_agent_id, active.provider_id, active.model)
    cached = _AGENT_CACHE.get(key)
    if cached is not None:
        return cached, False
    agent = _build_qwenpaw_agent(
        session_id,
        resolved_agent_id,
        workspace_dir=workspace_dir,
        mcp_clients=mcp_clients,
    )
    _AGENT_CACHE[key] = agent
    logger.info(
        "stream_query: built QwenPawAgent for session=%s agent=%s "
        "provider=%s model=%s tools=%d",
        session_id,
        resolved_agent_id,
        active.provider_id,
        active.model,
        len(agent.toolkit.tool_groups[0].tools),
    )
    return agent, True
