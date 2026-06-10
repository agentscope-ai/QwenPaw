# -*- coding: utf-8 -*-
"""Tool backing the ``/make-skill`` flow."""
from __future__ import annotations

import json
import logging
import re

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

# Only the brace-delimited form ${steps.N.path} is recognised.
_STEP_REF_INLINE = re.compile(
    r"\$\{steps\.(\d+)(?:\.([A-Za-z0-9_.-]+))?\}",
)


def _analyse_batch_refs(
    extra_files: dict[str, str],
) -> list[dict[str, str]]:
    """Parse batch JSON files in extra_files and extract $steps references.

    Returns a list of dicts, each with:
      - file: the extra_files key (relative path)
      - step_index: the step index being referenced
      - path: the dotted path into the step result (or "" for whole result)
      - tool_name: the tool at that step index (if resolvable)
      - referencing_step: which step contains this reference
      - referencing_tool: the tool_name of the referencing step
    """
    refs = []
    for file_key, content in extra_files.items():
        if not file_key.endswith(".json"):
            continue
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue
        actions = data if isinstance(data, list) else data.get("actions", [])
        if not isinstance(actions, list):
            continue
        for step_idx, action in enumerate(actions):
            if not isinstance(action, dict):
                continue
            referencing_tool = str(
                action.get("tool_name") or action.get("tool") or "",
            )
            # Scan all string values in arguments for ${steps} refs
            step_args = action.get("arguments") or action.get("args") or {}
            if not isinstance(step_args, dict):
                continue
            for _val in _iter_strings(step_args):
                for m in _STEP_REF_INLINE.finditer(_val):
                    ref_index = int(m.group(1))
                    ref_path = m.group(2) or ""
                    source_tool = ""
                    if 0 <= ref_index < len(actions):
                        source_tool = str(
                            actions[ref_index].get("tool_name")
                            or actions[ref_index].get("tool")
                            or "",
                        )
                    refs.append(
                        {
                            "file": file_key,
                            "step_index": str(ref_index),
                            "path": ref_path,
                            "tool_name": source_tool,
                            "referencing_step": str(step_idx),
                            "referencing_tool": referencing_tool,
                        },
                    )
    return refs


def _iter_strings(obj: object) -> list[str]:
    """Recursively collect all string values from dicts/lists."""
    results: list[str] = []
    if isinstance(obj, str):
        results.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            results.extend(_iter_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            results.extend(_iter_strings(v))
    return results


def _format_ref_verification(refs: list[dict[str, str]]) -> str:
    """Format $steps references into a verification prompt."""
    if not refs:
        return ""

    lines = [
        "\n\n---\n"
        "**Batch JSON contains `${steps}` references that need "
        "verification.**\n"
        "Before calling `finish_subtask`, please run each referenced tool "
        "or check previous tool use history "
        "to confirm its return value contains the expected fields:\n",
    ]
    for ref in refs:
        source = ref["tool_name"] or f"step {ref['step_index']}"
        path = ref["path"] or "(whole result)"
        lines.append(
            f"- `{ref['file']}`: step {ref['referencing_step']} "
            f"(`{ref['referencing_tool']}`) references "
            f"`${{steps.{ref['step_index']}.{ref['path']}}}` "
            f"→ verify that `{source}` returns a field `{path}`",
        )
    lines.append(
        "\nCall each source tool with sample arguments, or check previous "
        "tool use history in this conversation, and verify "
        "that the returned JSON contains the referenced path. "
        "If a field doesn't exist, use `edit_file` to fix the batch JSON "
        "file directly in the skill directory.",
    )
    return "\n".join(lines)


def _tool_text_response(text: str) -> ToolResponse:
    """Wrap text in a single-TextBlock ToolResponse."""
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _parse_extra_files(
    extra_files: dict[str, str] | str | None,
) -> dict[str, str] | None:
    """Accept either a mapping or its JSON string representation."""
    if extra_files is None or isinstance(extra_files, dict):
        return extra_files
    try:
        parsed = json.loads(extra_files)
    except json.JSONDecodeError as exc:
        raise SkillsError(
            message="extra_files string must be a valid JSON object",
        ) from exc
    if not isinstance(parsed, dict):
        raise SkillsError(message="extra_files string must parse to an object")
    return parsed


# pylint: disable=too-many-return-statements,too-many-branches,too-many-locals
async def materialize_skill(
    name: str,
    description: str,
    body: str,
    extra_files: dict[str, str] | str | None = None,
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
        extra_files: Additional files to include alongside SKILL.md.
            Pass either a dict or a JSON object string. Keys are relative
            paths (e.g. ``"scripts/batch.json"``), values are file
            contents as strings. Useful for bundling ``run_tool_batch``
            JSON files or helper scripts referenced by the skill body.
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
        parsed_extra_files = _parse_extra_files(extra_files)
        service = SkillService(workspace_dir)
        skill_name = service.create_skill(
            name=normalized_name,
            content=content,
            extra_files=parsed_extra_files or None,
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

    # Analyse batch JSON files for $steps references
    verification = ""
    if parsed_extra_files:
        refs = _analyse_batch_refs(parsed_extra_files)
        verification = _format_ref_verification(refs)

    return _tool_text_response(
        f"**Skill created and enabled**: `{skill_name}`\n\n"
        f"Visible via `/skills`; invoke with `/{skill_name}`."
        f"{verification}",
    )


# pylint: enable=too-many-return-statements,too-many-branches,too-many-locals
