# -*- coding: utf-8 -*-
"""Bootstrap guidance hook.

Checks for BOOTSTRAP.md in the workspace and injects guidance into
the first user message before agent execution.  Operates directly on
``ctx.input_msgs`` — does not require an agent instance.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)


class BootstrapHook(LifecycleHook):
    """Inject BOOTSTRAP.md guidance into the first user message."""

    phase = Phase.PRE_EXECUTE
    name = "bootstrap"
    priority = 20

    async def run(self, ctx: HookContext) -> HookResult:
        if ctx.extras.get("is_cron"):
            return HookResult()

        wd = ctx.workspace_dir
        if not wd:
            return HookResult()

        bootstrap_path = Path(wd) / "BOOTSTRAP.md"
        bootstrap_completed_flag = Path(wd) / ".bootstrap_completed"

        if bootstrap_completed_flag.exists():
            return HookResult()
        if not bootstrap_path.exists():
            return HookResult()

        if not ctx.input_msgs:
            return HookResult()

        try:
            from ...agents.prompt import build_bootstrap_guidance
            from ...agents.utils import prepend_to_message_content

            language = "zh"
            agent_config = ctx.agent_config
            if agent_config is not None:
                language = getattr(agent_config, "language", "zh") or "zh"

            bootstrap_guidance = build_bootstrap_guidance(language)

            for msg in ctx.input_msgs:
                if msg.role == "user":
                    prepend_to_message_content(msg, bootstrap_guidance)
                    break

            bootstrap_completed_flag.touch()
            logger.debug("Bootstrap guidance injected into input_msgs")
        except Exception:
            logger.debug("bootstrap: injection failed", exc_info=True)

        return HookResult()


__all__ = ["BootstrapHook"]
