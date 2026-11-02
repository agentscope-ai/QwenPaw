# -*- coding: utf-8 -*-
"""Coding mode activation."""

from __future__ import annotations

from ..base import AgentMode
from ...runtime.hooks import HookContext


class CodingMode(AgentMode):
    """Bundle for coding-mode behaviour."""

    name = "coding"

    def is_active(self, ctx: HookContext) -> bool:
        cfg = ctx.agent_config
        if cfg is None:
            try:
                from ...config.config import load_agent_config

                cfg = load_agent_config(ctx.agent_id)
            except Exception:
                return False
        cm = getattr(cfg, "coding_mode", None)
        return bool(cm and getattr(cm, "enabled", False))


__all__ = ["CodingMode"]
