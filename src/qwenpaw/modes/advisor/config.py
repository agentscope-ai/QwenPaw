# -*- coding: utf-8 -*-
"""Config access shared by the advisor mode, its hooks and middleware."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...config.config import AgentProfileConfig
    from ...runtime.hooks import HookContext

logger = logging.getLogger(__name__)


def resolve_agent_config(ctx: "HookContext") -> "AgentProfileConfig | None":
    """Request config when present, else the persisted one.

    ``ctx.agent_config`` is only populated by ``AgentBuilder`` — hooks in
    earlier phases and ``is_active`` must fall back to disk.
    """
    cfg = getattr(ctx, "agent_config", None)
    if cfg is not None:
        return cfg
    agent_id = getattr(ctx, "agent_id", None)
    if not agent_id:
        return None
    try:
        from ...config.config import load_agent_config

        return load_agent_config(agent_id)
    except Exception:
        logger.debug(
            "Advisor Mode: failed to load agent config",
            exc_info=True,
        )
        return None


def is_enabled(cfg: Any) -> bool:
    """Whether Advisor Mode is switched on in ``cfg`` (``None`` = no)."""
    return cfg is not None and cfg.advisor_mode.enabled


__all__ = ["is_enabled", "resolve_agent_config"]
