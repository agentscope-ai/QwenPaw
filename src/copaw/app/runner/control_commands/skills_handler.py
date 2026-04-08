# -*- coding: utf-8 -*-
"""Handler for /skills command.

Lists enabled skills for the current channel.
"""

from __future__ import annotations

from pathlib import Path

from .base import BaseControlCommandHandler, ControlContext
from ....agents.skills_manager import (
    get_workspace_skills_dir,
    reconcile_workspace_manifest,
)


class SkillsCommandHandler(BaseControlCommandHandler):
    """Handler for /skills command.

    Usage:
        /skills    # List enabled skills for this channel
    """

    command_name = "/skills"

    async def handle(self, context: ControlContext) -> str:
        workspace = context.workspace
        workspace_dir: Path | None = getattr(
            workspace,
            "workspace_dir",
            None,
        )
        if workspace_dir is None:
            return "**Error**: Workspace not initialized."

        channel_id = context.channel.channel
        manifest = reconcile_workspace_manifest(workspace_dir)
        skills_dir = get_workspace_skills_dir(workspace_dir)

        lines = ["**Enabled Skills**\n"]
        found = False
        for name, entry in sorted(
            manifest.get("skills", {}).items(),
        ):
            if not entry.get("enabled", False):
                continue
            channels = entry.get("channels") or ["all"]
            if "all" not in channels and channel_id not in channels:
                continue
            if not (skills_dir / name).exists():
                continue
            found = True
            desc = (
                entry.get("metadata", {}).get("description")
                or "No description"
            )
            lines.append(f"- **{name}**: {desc}")

        if not found:
            return "No skills are currently enabled for this channel."
        lines.append(
            "\nUse `/<name> <input>` to invoke a skill"
            " (or `/[name with spaces] <input>`).",
        )
        return "\n".join(lines)
