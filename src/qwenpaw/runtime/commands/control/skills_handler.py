# -*- coding: utf-8 -*-
"""Handler for /skills command.

Lists available skills for the current channel in a compact format.
"""

from __future__ import annotations

from pathlib import Path

from ....agents.skill_system import (
    reconcile_workspace_manifest,
    resolve_effective_skills,
)

from .base import BaseControlCommandHandler, ControlContext


class SkillsCommandHandler(BaseControlCommandHandler):
    """Handler for /skills command.

    Usage:
        /skills    # List available skills for this channel
    """

    command_name = "/skills"
    description = (
        "List chat-available skills and expose explicit skill commands"
    )

    @staticmethod
    def _truncate_description(
        text: str,
        limit: int = 32,
    ) -> str:
        """Return a single-line shortened description for compact lists."""
        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: limit - 3].rstrip()}..."

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
        lines = []
        for folder_name in resolve_effective_skills(workspace_dir, channel_id):
            entry = manifest.get("skills", {}).get(folder_name, {})
            description = (
                entry.get("metadata", {}).get("description")
                or "No description."
            )

            lines.append(
                f"**{folder_name}**: "
                f"{self._truncate_description(description)}",
            )

        if not lines:
            return "No skills are currently available for this channel."
        lines.append(
            "\n---\n"
            "*Use `/<skill_name>` for details, "
            "`/<skill_name> <input>` to invoke. "
            "`/[skill_name]` also works.*",
        )
        return "\n\n".join(lines)
