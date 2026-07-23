# -*- coding: utf-8 -*-
"""TeamMode — multi-agent collaboration pipeline."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from qwenpaw.runtime.slash_command_registry import CommandSpec

from ..shared.args import split_args
from ..shared.mode_base import OMPModeBase, info_msg, rewrite_user_msg
from ..shared.role_prompts import resolve_role
from .gate import TeamPipelineGate

if TYPE_CHECKING:
    from typing import Any

    from agentscope.message import Msg

logger = logging.getLogger(__name__)

_HELP = (
    "**Team** — multi-agent collaboration pipeline\n\n"
    "Usage: `/team [N:role] <task>`\n\n"
    "Examples:\n"
    "  `/team 3:executor Implement authentication`\n"
    "  `/team ralph Build the REST API`\n\n"
    "Phases: plan -> prd -> exec -> verify -> fix (retry)"
)


class TeamMode(OMPModeBase):
    """AgentMode for the Team pipeline."""

    name = "team"
    gate_cls = TeamPipelineGate
    plugin_id = "__omp_team__"
    handler_name = "team-stop-handler"
    scope = "omp-team"

    def commands(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                name="team",
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
            self._gate.activate_for_team,
            Path(workspace_dir),
            parsed["agent_count"],
            parsed["agent_role"],
        )

        prompt = (
            f"Team pipeline activated.\n"
            f"Task: {task}\n"
            f"Workers: {parsed['agent_count']}, Role: {parsed['agent_role']}\n"
            f"State directory: {loop_dir}\n"
            "Phase: plan \u2014 explore the codebase and "
            "create a task breakdown."
        )
        rewrite_user_msg(ctx, prompt)
        logger.info("Team started: %s", loop_dir)
        return None


_TEAM_SPEC_RE = re.compile(r"^(\d+):(\w[\w-]*)$")


def _parse_args(raw: str) -> dict | None:
    """Parse /team arguments.  ``None`` means invalid input."""
    tokens = split_args(raw)
    if tokens is None:
        return None

    agent_count = 3
    agent_role = "executor"
    task_parts: list[str] = []

    for i, t in enumerate(tokens):
        m = _TEAM_SPEC_RE.match(t)
        if m and i == 0:
            agent_count = int(m.group(1))
            agent_role = m.group(2)
        elif t in ("executor", "ralph") and i == 0:
            agent_role = t
        else:
            task_parts.append(t)

    return {
        "task": " ".join(task_parts),
        "agent_count": max(1, min(agent_count, 10)),
        "agent_role": resolve_role(agent_role),
    }
