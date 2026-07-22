# -*- coding: utf-8 -*-
"""AutopilotMode — full lifecycle pipeline."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from qwenpaw.runtime.slash_command_registry import CommandSpec

from ..shared.args import split_args
from ..shared.mode_base import OMPModeBase, info_msg, rewrite_user_msg
from .gate import AutopilotGate

if TYPE_CHECKING:
    from typing import Any

    from agentscope.message import Msg

logger = logging.getLogger(__name__)

_HELP = (
    "**Autopilot** — full lifecycle pipeline\n\n"
    "Usage: `/autopilot [--skip-qa] [--skip-validation] <task>`\n\n"
    "Phases: expansion -> planning -> execution "
    "-> qa -> validation -> cleanup\n"
    "Phase 4 uses 3 parallel reviewers (architect + security + code)."
)


class AutopilotMode(OMPModeBase):
    """AgentMode for the Autopilot pipeline."""

    name = "autopilot"
    gate_cls = AutopilotGate
    plugin_id = "__omp_autopilot__"
    handler_name = "autopilot-stop-handler"
    scope = "omp-autopilot"

    def commands(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                name="autopilot",
                handler=self._handler,
                category="builtin",
                help_text=_HELP,
                metadata={"builtin": True},
            ),
        ]

    async def _handler(self, ctx: "Any", args: str) -> Optional["Msg"]:
        if not args or not args.strip() or args.strip().lower() == "help":
            return info_msg(_HELP)

        parsed = _parse_args(args)
        if parsed is None:
            return info_msg("Invalid arguments. " + _HELP)
        task = parsed["task"]
        if len(task) < 5:
            return info_msg("Please provide a task description.\n\n" + _HELP)

        workspace_dir = getattr(ctx, "workspace_dir", None)
        if not workspace_dir:
            return info_msg("ERROR: no workspace directory available.")

        self.claim_workflow()
        loop_dir = await asyncio.to_thread(
            self._gate.activate_for_autopilot,
            Path(workspace_dir),
            parsed["skip_qa"],
            parsed["skip_validation"],
        )

        prompt = (
            f"Autopilot activated.\n"
            f"Task: {task}\n"
            f"State directory: {loop_dir}\n"
            f"Phase: expansion — analyze requirements and create spec.md."
        )
        rewrite_user_msg(ctx, prompt)
        logger.info("Autopilot started: %s", loop_dir)
        return None


def _parse_args(raw: str) -> dict | None:
    """Parse /autopilot arguments.  ``None`` means invalid input."""
    tokens = split_args(raw)
    if tokens is None:
        return None

    skip_qa = False
    skip_validation = False
    task_parts: list[str] = []

    for t in tokens:
        if t == "--skip-qa":
            skip_qa = True
        elif t == "--skip-validation":
            skip_validation = True
        else:
            task_parts.append(t)

    return {
        "task": " ".join(task_parts),
        "skip_qa": skip_qa,
        "skip_validation": skip_validation,
    }
