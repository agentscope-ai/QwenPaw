# -*- coding: utf-8 -*-
"""Handler for /skills command.

Lists enabled skills for the current channel.
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
            display_name = folder_name
            desc = (
                entry.get("metadata", {}).get("description")
                or "No description"
            )
            if skill_md.exists():
                raw = read_text_file_with_encoding_fallback(skill_md)
                post = fm.loads(raw)
                display_name = post.get("name") or folder_name
                desc = post.get("description") or desc

            lines.append(
                f"**{folder_name}**\n\n"
                f"- **name**: {display_name}\n"
                f"- **description**: {desc}\n"
                f"- **command**: `/{folder_name}`, "
                f"`/[{folder_name}]`",
            )

        if not found:
            return "No skills are currently enabled for this channel."
        lines.append(
            "\n---\n"
            "*These are all enabled skills for this channel. "
            "Use `/<skill_name> <input>` to invoke, "
            "or `/<skill_name>` to view details.*",
        )
        return "\n\n".join(lines)
