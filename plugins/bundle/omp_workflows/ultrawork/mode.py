# -*- coding: utf-8 -*-
"""UltraworkMode — parallel execution engine."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from qwenpaw.runtime.slash_command_registry import CommandSpec

from ..shared.mode_base import OMPModeBase, info_msg, rewrite_user_msg
from .gate import UltraworkGate

if TYPE_CHECKING:
    from typing import Any

    from agentscope.message import Msg

logger = logging.getLogger(__name__)

_HELP = (
    "**Ultrawork** — parallel task execution engine\n\n"
    "Usage: `/ultrawork <task description>`\n\n"
    "Decomposes the task into independent sub-tasks and executes\n"
    "them in parallel via spawn_subagent batch mode."
)


class UltraworkMode(OMPModeBase):
    """AgentMode for Ultrawork parallel execution."""

    name = "ultrawork"
    gate_cls = UltraworkGate
    plugin_id = "__omp_ultrawork__"
    handler_name = "ultrawork-stop-handler"
    scope = "omp-ultrawork"

    def commands(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                name="ultrawork",
                handler=self._handler,
                category="builtin",
                help_text=_HELP,
                metadata={"builtin": True},
            ),
        ]

    async def _handler(self, ctx: "Any", args: str) -> Optional["Msg"]:
        task = (args or "").strip()
        if not task or len(task) < 5 or task.lower() == "help":
            return info_msg(_HELP)

        workspace_dir = getattr(ctx, "workspace_dir", None)
        if not workspace_dir:
            return info_msg("ERROR: no workspace directory available.")

        self.claim_workflow()
        loop_dir = await asyncio.to_thread(
            self._gate.activate_for_work,
            Path(workspace_dir),
        )

        prompt = (
            f"Ultrawork activated.\n"
            f"Task: {task}\n"
            f"State directory: {loop_dir}\n"
            f"Decompose this task into independent sub-tasks and use "
            f"spawn_subagent batch mode to execute them in parallel."
        )
        rewrite_user_msg(ctx, prompt)
        logger.info("Ultrawork started: %s", loop_dir)
        return None
