# -*- coding: utf-8 -*-
"""Handler for /skills command.

Lists enabled skills for the current channel in a compact format.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter as fm

from .base import BaseControlCommandHandler, ControlContext
from ....agents.skills_manager import (
    get_workspace_skills_dir,
    reconcile_workspace_manifest,
)
from ....agents.utils.file_handling import (
    read_text_file_with_encoding_fallback,
)


class SkillsCommandHandler(BaseControlCommandHandler):
    """Handler for /skills command.

    Usage:
        /skills    # List enabled skills for this channel
    """

    command_name = "/skills"

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
        skills_dir = get_workspace_skills_dir(workspace_dir)

        lines = []
        found = False
        for folder_name, entry in sorted(
            manifest.get("skills", {}).items(),
        ):
            if not entry.get("enabled", False):
                continue
            channels = entry.get("channels") or ["all"]
            if "all" not in channels and channel_id not in channels:
                continue
            skill_dir = skills_dir / folder_name
            if not skill_dir.exists():
                continue
            found = True

            # Read frontmatter for display name.
            skill_md = skill_dir / "SKILL.md"
            description = (
                entry.get("metadata", {}).get("description")
                or "No description."
            )
            if skill_md.exists():
                raw = read_text_file_with_encoding_fallback(skill_md)
                post = fm.loads(raw)
                description = post.get("description") or description

            lines.append(
                f"**{folder_name}**: "
                f"{self._truncate_description(description)}",
            )

        if not found:
            return "No skills are currently enabled for this channel."
        lines.append(
            "\n---\n"
            "*Use `/<skill_name>` for details, "
            "`/<skill_name> <input>` to invoke. "
            "`/[skill_name]` also works.*",
        )
        return "\n\n".join(lines)
