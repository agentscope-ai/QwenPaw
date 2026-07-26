# -*- coding: utf-8 -*-
"""RalphMode — PRD-driven continuous implementation loop."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from qwenpaw.runtime.slash_command_registry import CommandSpec

from ..shared.args import split_args
from ..shared.mode_base import OMPModeBase, info_msg, rewrite_user_msg
from .gate import RalphGate

if TYPE_CHECKING:
    from typing import Any

    from agentscope.message import Msg

logger = logging.getLogger(__name__)

_HELP = (
    "**Ralph** — PRD-driven continuous implementation loop\n\n"
    "Usage: `/ralph [--no-deslop] "
    "[--critic=architect|critic|codex] <task>`\n\n"
    "Creates a PRD with user stories, implements each one,\n"
    "verifies acceptance criteria, and runs reviewer verification."
)


class RalphMode(OMPModeBase):
    """AgentMode for the Ralph workflow."""

    name = "ralph"
    gate_cls = RalphGate
    plugin_id = "__omp_ralph__"
    handler_name = "ralph-stop-handler"
    scope = "omp-ralph"

    def commands(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                name="ralph",
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
            self._gate.activate_for_ralph,
            Path(workspace_dir),
            parsed["no_deslop"],
            parsed["critic_type"],
        )

        from .prompts import build_initial_prd_prompt

        prompt = build_initial_prd_prompt(task, loop_dir)
        rewrite_user_msg(ctx, prompt)
        logger.info("Ralph started: %s", loop_dir)
        return None


def _parse_args(raw: str) -> dict | None:
    """Parse /ralph arguments.  ``None`` means invalid input."""
    tokens = split_args(raw)
    if tokens is None:
        return None

    no_deslop = False
    critic_type = "architect"
    task_parts: list[str] = []

    for t in tokens:
        if t == "--no-deslop":
            no_deslop = True
        elif t.startswith("--critic="):
            critic_type = t.split("=", 1)[1]
            if critic_type not in ("architect", "critic", "codex"):
                critic_type = "architect"
        else:
            task_parts.append(t)

    return {
        "task": " ".join(task_parts),
        "no_deslop": no_deslop,
        "critic_type": critic_type,
    }
