# -*- coding: utf-8 -*-
"""Persistence and CRUD helpers for skill judgement rules.

Each skill that declares ``metadata.rule_needed: true`` in its
``SKILL.md`` frontmatter can be paired with a standalone ``rules.json``
file living alongside ``SKILL.md`` inside the skill directory::

    workspaces/{agent_id}/skills/{skill_name}/
    ├── SKILL.md          # SOP (fixed workflow)
    └── rules.json        # judgement rules (user-editable, decoupled)

The rules file is intentionally **separate** from both ``SKILL.md`` and
the manifest ``skill.json`` so that:

* The LLM can safely modify rules via the ``skill_rules`` tool family
  without ever touching the SOP.
* Rules sync independently when a skill is exported / imported.

A rule is simply a natural-language sentence plus an on/off toggle —
no rigid schema, so the agent and the user can express any judgement
criterion in plain language.
"""

from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path
from typing import Any

from ...exceptions import SkillsError
from .store import (
    get_workspace_skills_dir,
    normalize_skill_dir_name,
    read_json,
    safe_skill_dir,
    write_json_atomic,
)

logger = logging.getLogger(__name__)

RULES_FILE_NAME = "rules.json"

# Default rule payload returned when the file does not exist yet.
_EMPTY_RULES_PAYLOAD: dict[str, Any] = {"version": 0, "rules": []}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def get_rules_file_path(workspace_dir: Path, skill_name: str) -> Path:
    """Return the absolute path to a skill's ``rules.json``.

    The file may not exist yet; callers should check with ``.exists()``
    or use :func:`read_rules` which gracefully handles missing files.
    """
    normalized = normalize_skill_dir_name(skill_name)
    skills_dir = get_workspace_skills_dir(workspace_dir)
    skill_dir = safe_skill_dir(skills_dir, normalized)
    return skill_dir / RULES_FILE_NAME


def rules_file_exists(workspace_dir: Path, skill_name: str) -> bool:
    """Return ``True`` when a ``rules.json`` is present for the skill."""
    return get_rules_file_path(workspace_dir, skill_name).exists()


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def read_rules(workspace_dir: Path, skill_name: str) -> list[dict[str, Any]]:
    """Read the rule list for a skill.

    Returns an empty list when the file does not exist yet.
    """
    rules_path = get_rules_file_path(workspace_dir, skill_name)
    if not rules_path.exists():
        return []
    payload = read_json(rules_path, dict(_EMPTY_RULES_PAYLOAD))
    rules = payload.get("rules", [])
    if not isinstance(rules, list):
        logger.warning(
            "rules.json for '%s' has non-list 'rules' field; treating as empty",
            skill_name,
        )
        return []
    return [r for r in rules if isinstance(r, dict)]


def _write_rules(
    workspace_dir: Path,
    skill_name: str,
    rules: list[dict[str, Any]],
) -> None:
    """Persist the full rule list (atomic write)."""
    rules_path = get_rules_file_path(workspace_dir, skill_name)
    # Ensure the parent skill directory exists.
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"rules": rules}
    write_json_atomic(rules_path, payload)


# ---------------------------------------------------------------------------
# Rule helpers
# ---------------------------------------------------------------------------


def _generate_rule_id() -> str:
    return f"rule_{secrets.token_hex(4)}"


def _build_rule(
    *,
    content: str,
    enabled: bool = True,
    rule_id: str | None = None,
) -> dict[str, Any]:
    """Construct a validated rule dict."""
    text = str(content or "").strip()
    if not text:
        raise SkillsError(message="Rule content cannot be empty")
    return {
        "id": rule_id or _generate_rule_id(),
        "content": text,
        "enabled": bool(enabled),
    }


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


def add_rule(
    workspace_dir: Path,
    skill_name: str,
    *,
    content: str,
    enabled: bool = True,
) -> dict[str, Any]:
    """Append a new rule and return it."""
    rules = read_rules(workspace_dir, skill_name)
    rule = _build_rule(content=content, enabled=enabled)
    rules.append(rule)
    _write_rules(workspace_dir, skill_name, rules)
    return rule


def update_rule(
    workspace_dir: Path,
    skill_name: str,
    rule_id: str,
    *,
    content: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any] | None:
    """Update fields of an existing rule.

    Only the fields that are not ``None`` are modified.  Returns the
    updated rule, or ``None`` when the id was not found.
    """
    rules = read_rules(workspace_dir, skill_name)
    for rule in rules:
        if rule.get("id") == rule_id:
            if content is not None:
                text = str(content).strip()
                if not text:
                    raise SkillsError(
                        message="Rule content cannot be empty",
                    )
                rule["content"] = text
            if enabled is not None:
                rule["enabled"] = bool(enabled)
            _write_rules(workspace_dir, skill_name, rules)
            return rule
    return None


def delete_rule(
    workspace_dir: Path,
    skill_name: str,
    rule_id: str,
) -> bool:
    """Delete a rule by id.  Returns ``True`` if a rule was removed."""
    rules = read_rules(workspace_dir, skill_name)
    new_rules = [r for r in rules if r.get("id") != rule_id]
    if len(new_rules) == len(rules):
        return False
    _write_rules(workspace_dir, skill_name, new_rules)
    return True


def replace_all_rules(
    workspace_dir: Path,
    skill_name: str,
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace the entire rule list (used by REST API bulk updates).

    Each rule is validated and normalised; ids are preserved when
    present, otherwise generated.
    """
    normalised: list[dict[str, Any]] = []
    for raw in rules:
        if not isinstance(raw, dict):
            continue
        normalised.append(
            _build_rule(
                content=str(raw.get("content", "")),
                enabled=bool(raw.get("enabled", True)),
                rule_id=raw.get("id") or None,
            ),
        )
    _write_rules(workspace_dir, skill_name, normalised)
    return normalised


def rules_to_json_string(rules: list[dict[str, Any]]) -> str:
    """Serialise a rule list to a compact JSON string (for env injection)."""
    return json.dumps(rules, ensure_ascii=False)
