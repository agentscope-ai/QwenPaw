# -*- coding: utf-8 -*-
"""Leaf tool backing the ``/make-skill`` flow.

Lives alongside the other built-in agent tools (``file_io.py``,
``shell.py``, …); the rest of the make-skill feature (service,
prompt) is under :mod:`qwenpaw.agents.skill_system.make_skill`.
"""
from __future__ import annotations

import logging

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.context import get_current_workspace_dir
from ...exceptions import SkillsError
from ...security.skill_scanner import SkillScanError
from ..skill_system.make_skill.service import (
    materialize_workspace_skill,
    name_conflict,
    render_skill_md,
)
from ..skill_system.store import normalize_skill_dir_name

logger = logging.getLogger(__name__)


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
        return ToolResponse(content=[TextBlock(type="text", text=(
            "**materialize_skill is missing required input**\n\n"
            "Need non-empty `name`, `description`, and `body`. Re-derive "
            "them from `plan.name` and `plan.description` and call "
            "`materialize_skill` again. Do NOT call `finish_subtask` yet."
        ))])

    workspace_dir = get_current_workspace_dir()
    if workspace_dir is None:
        return ToolResponse(content=[TextBlock(type="text", text=(
            "**Workspace directory not set in context**; cannot "
            "materialize. This is an internal error — abandon the plan."
        ))])

    # Defence in depth: runner already normalised and checked conflict
    # on the focus before rewriting to /plan. Re-normalise here in case
    # the LLM-supplied `name` drifted from `plan.name`.
    try:
        normalized_name = normalize_skill_dir_name(name)
    except Exception as e:  # pylint: disable=broad-except
        return ToolResponse(content=[TextBlock(type="text", text=(
            f"**Invalid skill name** `{name}`: {e}\n\n"
            "Call `revise_current_plan` to fix `plan.name` and try "
            "again."
        ))])

    conflict = name_conflict(workspace_dir, normalized_name)
    if conflict:
        conflict_name, suggested = conflict
        return ToolResponse(content=[TextBlock(type="text", text=(
            f"**Skill named `{conflict_name}` already exists in this "
            f"workspace.**\n\nCall `revise_current_plan` to switch "
            f"`plan.name` to `{suggested}` (or another fresh name) "
            f"and update the body accordingly. If the user wants to "
            f"keep the existing skill, call `finish_plan` with "
            f"state='abandoned'."
        ))])

    content = render_skill_md(
        proposed_name=normalized_name,
        description=description,
        body=body,
    )

    try:
        skill_name = materialize_workspace_skill(
            workspace_dir,
            proposed_name=normalized_name,
            skill_md=content,
        )
    except SkillsError as e:
        return ToolResponse(content=[TextBlock(type="text", text=(
            f"**Skill format error**: {e}\n\n"
            "Fix the SKILL.md content (frontmatter fields, body sections, "
            "etc.) and call `materialize_skill` again. Do NOT call "
            "`finish_subtask` until materialize_skill returns success."
        ))])
    except SkillScanError as e:
        return ToolResponse(content=[TextBlock(type="text", text=(
            f"**Skill creation rejected by security scan**\n\n{e}\n\n"
            "Remove the flagged patterns from the body and call "
            "`materialize_skill` again. Do NOT call `finish_subtask` "
            "until materialize_skill returns success."
        ))])
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("materialize_skill failed")
        return ToolResponse(content=[TextBlock(type="text", text=(
            f"**Skill creation failed**: {e}\n\n"
            "Adjust the inputs and call `materialize_skill` again, or "
            "abandon the plan if the failure is not recoverable."
        ))])

    return ToolResponse(content=[TextBlock(type="text", text=(
        f"**Skill created and enabled**: `{skill_name}`\n\n"
        f"Visible via `/skills`; invoke with `/{skill_name}`."
    ))])
