# -*- coding: utf-8 -*-
"""Tool backing the ``/make-skill`` flow."""
from __future__ import annotations

import logging

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.context import get_current_workspace_dir
from ...exceptions import SkillsError
from ...security.skill_scanner import SkillScanError
from ..skill_system.store import (
    normalize_skill_dir_name,
    render_skill_md,
    workspace_skill_name_conflict,
)
from ..skill_system.workspace_service import SkillService

logger = logging.getLogger(__name__)


def _tool_text_response(text: str) -> ToolResponse:
    """Wrap text in a single-TextBlock ToolResponse."""
    return ToolResponse(content=[TextBlock(type="text", text=text)])


async def materialize_skill(
    name: str,
    description: str,
    body: str,
) -> ToolResponse:
    """Persist a confirmed skill proposal into the workspace.

    Runs format validation and the security scanner, writes
    ``SKILL.md`` plus the manifest entry, and enables the skill.

    Args:
        name: Normalised skill directory name. For ``/make-skill``,
            MUST equal ``plan.name``.
        description: The SKILL.md frontmatter trigger string
            (``Use this skill when …``). Keep it ≤ ~200 chars and
            push on synonyms / adjacent phrasings so future agents
            don't under-trigger.
        body: The SKILL.md body, no frontmatter.
    """
    if not name or not description or not body:
        return _tool_text_response(
            "**materialize_skill is missing required input**\n\n"
            "Need non-empty `name`, `description`, and `body`. "
            "Re-derive them from `plan.name` and `plan.description` "
            "and call `materialize_skill` again. "
            "Do NOT call `finish_subtask` yet.",
        )

    workspace_dir = get_current_workspace_dir()
    if workspace_dir is None:
        return _tool_text_response(
            "**Workspace directory not set in context**; cannot "
            "materialize. This is an internal error — abandon "
            "the plan.",
        )

    # Defence in depth: runner already normalised and checked conflict
    # on the focus before rewriting to /plan. Re-normalise here in case
    # the LLM-supplied `name` drifted from `plan.name`.
    try:
        normalized_name = normalize_skill_dir_name(name)
    except Exception as e:  # pylint: disable=broad-except
        return _tool_text_response(
            f"**Invalid skill name** `{name}`: {e}\n\n"
            "Call `revise_current_plan` to fix `plan.name` and "
            "try again.",
        )

    conflict = workspace_skill_name_conflict(workspace_dir, normalized_name)
    if conflict:
        conflict_name, suggested = conflict
        return _tool_text_response(
            f"**Skill named `{conflict_name}` already exists in "
            f"this workspace.**\n\n"
            f"Call `revise_current_plan` to switch `plan.name` to "
            f"`{suggested}` (or another fresh name) and update the "
            f"body accordingly. If the user wants to keep the "
            f"existing skill, call `finish_plan` with "
            f"state='abandoned'.",
        )

    content = render_skill_md(
        proposed_name=normalized_name,
        description=description,
        body=body,
    )

    try:
        service = SkillService(workspace_dir)
        skill_name = service.create_skill(
            name=normalized_name,
            content=content,
            enable=True,
            source="agent",
        )
        if not skill_name:
            raise RuntimeError(
                f"Skill '{normalized_name}' was created concurrently. "
                "Try a different focus.",
            )
    except Exception as e:  # pylint: disable=broad-except
        if isinstance(e, SkillsError):
            text = (
                f"**Skill format error**: {e}\n\n"
                "Fix the SKILL.md content (frontmatter fields, "
                "body sections, etc.) and call `materialize_skill` "
                "again. Do NOT call `finish_subtask` until "
                "materialize_skill returns success."
            )
        elif isinstance(e, SkillScanError):
            text = (
                f"**Skill creation rejected by security scan**"
                f"\n\n{e}\n\n"
                "Remove the flagged patterns from the body and "
                "call `materialize_skill` again. Do NOT call "
                "`finish_subtask` until materialize_skill returns "
                "success."
            )
        else:
            logger.exception("materialize_skill failed")
            text = (
                f"**Skill creation failed**: {e}\n\n"
                "Adjust the inputs and call `materialize_skill` "
                "again, or abandon the plan if the failure is "
                "not recoverable."
            )
        return _tool_text_response(text)

    return _tool_text_response(
        f"**Skill created and enabled**: `{skill_name}`\n\n"
        f"Visible via `/skills`; invoke with `/{skill_name}`.",
    )
