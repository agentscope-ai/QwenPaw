# -*- coding: utf-8 -*-
"""Coding mode hooks."""

from __future__ import annotations

from ..base import ModeGatedHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase


class ProjectDirInjectionHook(ModeGatedHook):
    """Stash ``project_dir`` into ``ctx.mode_state["coding"]``."""

    phase = Phase.PRE_AGENT_BUILD
    name = "coding_mode_project_dir"
    priority = 30

    async def _run(self, ctx: HookContext) -> HookResult:
        cfg = ctx.agent_config
        if cfg is None:
            try:
                from ...config.config import load_agent_config

                cfg = load_agent_config(ctx.agent_id)
            except Exception:
                return HookResult()
        cm = getattr(cfg, "coding_mode", None)
        if cm and getattr(cm, "project_dir", None):
            ctx.mode_state.setdefault("coding", {})[
                "project_dir"
            ] = cm.project_dir
        return HookResult()


__all__ = ["ProjectDirInjectionHook"]
