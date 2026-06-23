# -*- coding: utf-8 -*-
"""Agent tools for managing skill judgement rules.

These tools let the LLM **safely** add / update / delete / list
judgement rules for any skill that declares ``rule_needed: true`` —
without ever touching ``SKILL.md``.  This is the core of the
SOP ↔ rules decoupling: the agent can refine the rule set through
natural conversation while the SOP stays untouched.

Rules are persisted to ``rules.json`` next to ``SKILL.md`` (see
:mod:`qwenpaw.agents.skill_system.rule_store`).  Each rule is just a
natural-language sentence plus an on/off toggle.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.context import get_current_workspace_dir
from ..skill_system.rule_store import (
    add_rule,
    delete_rule,
    read_rules,
    update_rule,
)

__all__ = [
    "list_skill_rules",
    "add_skill_rule",
    "update_skill_rule",
    "delete_skill_rule",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text_response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _json_response(data: object) -> ToolResponse:
    return _text_response(json.dumps(data, ensure_ascii=False, indent=2))


def _resolve_workspace() -> Optional[str]:
    """Return workspace dir string or ``None`` if unset."""
    workspace_dir = get_current_workspace_dir()
    if workspace_dir is None:
        return None
    return str(workspace_dir)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


async def list_skill_rules(skill_name: str) -> ToolResponse:
    """List all judgement rules for a skill.

    Use this to inspect the current rule set of a skill that has
    ``rule_needed`` enabled.  Rules are numbered starting from 1.
    Use the number to reference a rule in update/delete operations.

    Args:
        skill_name (`str`):
            The skill name (same as the ``name`` field in the skill's
            SKILL.md frontmatter).

    Returns:
        `ToolResponse`: A numbered list of rules with their status.
    """
    workspace = _resolve_workspace()
    if workspace is None:
        return _text_response(
            "ERROR: workspace directory not set in context",
        )

    try:
        rules = await asyncio.to_thread(
            read_rules,
            Path(workspace),
            skill_name,
        )
    except Exception as exc:  # noqa: BLE001
        return _text_response(f"ERROR: {exc}")

    if not rules:
        return _text_response(f"Skill '{skill_name}' has no rules.")

    lines = []
    for i, r in enumerate(rules, 1):
        status = "启用" if r.get("enabled", True) else "禁用"
        lines.append(f"{i}. [{status}] {r.get('content', '')}")
    return _text_response("\n".join(lines))


async def add_skill_rule(
    skill_name: str,
    content: str,
) -> ToolResponse:
    """Add one judgement rule to a skill's ``rules.json``.

    The rule is a natural-language sentence describing a judgement
    criterion, e.g. *"内存使用率超过 95% 时触发严重告警并通知运维"*.
    The rule is stored independently from SKILL.md, so the SOP is never
    modified.

    Args:
        skill_name (`str`):
            The skill name to add the rule to.
        content (`str`):
            The rule text in natural language.

    Returns:
        `ToolResponse`: The newly created rule object (with its
        auto-generated ``id``).
    """
    workspace = _resolve_workspace()
    if workspace is None:
        return _text_response(
            "ERROR: workspace directory not set in context",
        )

    try:
        rule = await asyncio.to_thread(
            add_rule,
            Path(workspace),
            skill_name,
            content=content,
        )
    except Exception as exc:  # noqa: BLE001
        return _text_response(f"ERROR: {exc}")

    return _text_response(
        f"Rule added: {rule.get('content', '')}",
    )


async def update_skill_rule(
    skill_name: str,
    index: int,
    content: str,
) -> ToolResponse:
    """Update the text of an existing judgement rule by its number.

    Args:
        skill_name (`str`):
            The skill name the rule belongs to.
        index (`int`):
            The rule number (starting from 1) as shown by
            ``list_skill_rules``.
        content (`str`):
            The new rule text in natural language.

    Returns:
        `ToolResponse`: Confirmation or error message.
    """
    workspace = _resolve_workspace()
    if workspace is None:
        return _text_response(
            "ERROR: workspace directory not set in context",
        )

    try:
        rules = await asyncio.to_thread(
            read_rules, Path(workspace), skill_name,
        )
    except Exception as exc:  # noqa: BLE001
        return _text_response(f"ERROR: {exc}")

    if index < 1 or index > len(rules):
        return _text_response(
            f"ERROR: invalid index {index}, skill '{skill_name}' "
            f"has {len(rules)} rule(s).",
        )

    rule_id = rules[index - 1].get("id", "")
    try:
        rule = await asyncio.to_thread(
            update_rule,
            Path(workspace),
            skill_name,
            rule_id,
            content=content,
        )
    except Exception as exc:  # noqa: BLE001
        return _text_response(f"ERROR: {exc}")

    if rule is None:
        return _text_response("ERROR: rule not found.")

    return _text_response(
        f"Rule #{index} updated: {rule.get('content', '')}",
    )


async def delete_skill_rule(
    skill_name: str,
    index: int,
) -> ToolResponse:
    """Delete a judgement rule by its number.

    Args:
        skill_name (`str`):
            The skill name the rule belongs to.
        index (`int`):
            The rule number (starting from 1) as shown by
            ``list_skill_rules``.

    Returns:
        `ToolResponse`: A confirmation message, or an error if the
        index is out of range.
    """
    workspace = _resolve_workspace()
    if workspace is None:
        return _text_response(
            "ERROR: workspace directory not set in context",
        )

    try:
        rules = await asyncio.to_thread(
            read_rules, Path(workspace), skill_name,
        )
    except Exception as exc:  # noqa: BLE001
        return _text_response(f"ERROR: {exc}")

    if index < 1 or index > len(rules):
        return _text_response(
            f"ERROR: invalid index {index}, skill '{skill_name}' "
            f"has {len(rules)} rule(s).",
        )

    rule_id = rules[index - 1].get("id", "")
    try:
        deleted = await asyncio.to_thread(
            delete_rule,
            Path(workspace),
            skill_name,
            rule_id,
        )
    except Exception as exc:  # noqa: BLE001
        return _text_response(f"ERROR: {exc}")

    if not deleted:
        return _text_response("ERROR: rule not found.")

    return _text_response(
        f"Rule #{index} deleted from skill '{skill_name}'.",
    )
