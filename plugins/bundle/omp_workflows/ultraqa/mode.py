# -*- coding: utf-8 -*-
"""UltraQAMode — QA cycle engine with 3-agent collaboration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from qwenpaw.runtime.slash_command_registry import CommandSpec

from ..shared.args import split_args
from ..shared.mode_base import OMPModeBase, info_msg, rewrite_user_msg
from .gate import UltraQAGate

if TYPE_CHECKING:
    from typing import Any

    from agentscope.message import Msg

logger = logging.getLogger(__name__)

_HELP = (
    "**UltraQA** — automated QA cycle engine\n\n"
    "Usage:\n"
    '  `/ultraqa [--tests|--build|--lint|--typecheck|--custom "cmd"]'
    " [--interactive]`\n\n"
    "Runs repeated QA cycles: check → diagnose → fix → re-check.\n"
    "Stops when all checks pass or max cycles reached."
)


class UltraQAMode(OMPModeBase):
    """AgentMode for the UltraQA workflow."""

    name = "ultraqa"
    gate_cls = UltraQAGate
    plugin_id = "__omp_ultraqa__"
    handler_name = "ultraqa-stop-handler"
    scope = "omp-ultraqa"

    def commands(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                name="ultraqa",
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

        workspace_dir = getattr(ctx, "workspace_dir", None)
        if not workspace_dir:
            return info_msg("ERROR: no workspace directory available.")

        self.claim_workflow()
        loop_dir = await asyncio.to_thread(
            self._gate.activate_for_qa,
            Path(workspace_dir),
            parsed["goal_type"],
            parsed["custom_cmd"],
            parsed["interactive"],
        )

        prompt = (
            f"UltraQA activated. Goal: {parsed['goal_type']}.\n"
            f"State directory: {loop_dir}\n"
            f"Read {loop_dir}/state.json and begin the QA cycle."
        )
        rewrite_user_msg(ctx, prompt)
        logger.info("UltraQA started: %s", loop_dir)
        return None


def _parse_args(raw: str) -> dict | None:
    """Parse /ultraqa arguments.  ``None`` means invalid input."""
    tokens = split_args(raw)
    if tokens is None:
        return None

    goal_type = "tests"
    custom_cmd = ""
    interactive = False

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "--tests":
            goal_type = "tests"
        elif t == "--build":
            goal_type = "build"
        elif t == "--lint":
            goal_type = "lint"
        elif t == "--typecheck":
            goal_type = "typecheck"
        elif t == "--interactive":
            interactive = True
        elif t == "--custom" and i + 1 < len(tokens):
            goal_type = "custom"
            i += 1
            custom_cmd = tokens[i]
        i += 1

    return {
        "goal_type": goal_type,
        "custom_cmd": custom_cmd,
        "interactive": interactive,
    }
