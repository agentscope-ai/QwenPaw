# -*- coding: utf-8 -*-
"""Coding mode — self-contained ``AgentMode`` plugin.

All coding-mode logic lives under this package:

- ``CodingMode`` — the ``AgentMode`` entry point.
- ``CodingModeMixin`` — mixin that adds coding features to a ReActAgent.
- ``collect_coding_tools()`` — standalone tool-collection helper.
- ``_CODING_SYSTEM_PROMPT_TEMPLATE`` — system prompt template.
- ``ProjectDirInjectionHook`` — hook that stashes ``project_dir``
  into ``ctx.mode_state["coding"]``.
"""

from __future__ import annotations

from ..base import AgentMode
from ...runtime.hooks import HookBase, HookContext
from .mixin import (
    CodingModeMixin,
    _CODING_SYSTEM_PROMPT_TEMPLATE,
    collect_coding_tools,
)


class CodingMode(AgentMode):
    """Bundle for coding-mode behaviour."""

    name = "coding"

    def hooks(self) -> list[HookBase]:
        from .hooks import ProjectDirInjectionHook

        return [ProjectDirInjectionHook(owner_mode=self)]

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


__all__ = [
    "CodingMode",
    "CodingModeMixin",
    "_CODING_SYSTEM_PROMPT_TEMPLATE",
    "collect_coding_tools",
]
