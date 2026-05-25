# -*- coding: utf-8 -*-
"""Coding Mode mixin for QwenPawAgent.

Provides one behaviour activated when ``coding_mode.enabled`` is
``True`` in the agent configuration:

1. **System Prompt Injection** — appends a coding-focused persona
   and workflow guidelines to the agent system prompt.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


_CODING_SYSTEM_PROMPT_TEMPLATE = """\
## Coding Mode

You are currently operating in **Coding Mode**.

### Active project
The user's active coding project directory is: `{project_dir}`

All file operations (`read_file`, `write_file`, `edit_file`, `list_directory`,
etc.) should use paths **relative to the project directory above** unless the
user explicitly specifies an absolute path.  Do NOT read or write outside this
directory unless explicitly asked.

### Agent workspace
The internal QwenPaw workspace (configs, sessions, memory) is located at:
`{workspace_dir}` — do NOT touch files here unless the user explicitly asks.

### Working guidelines
1. **Read before you write** — always read the relevant file(s) first.
2. **Prefer targeted edits** — use `edit_file` over full-file rewrites \
whenever possible.
3. **Announce changes** — before modifying a file, state the file path and \
the intent in plain language.
4. **Summarise after each batch** — briefly note what was done and what \
remains.

Keep reasoning concise.  Prefer small, verifiable steps over large monolithic \
changes.
"""


class CodingModeMixin:
    """Mixin that adds Coding Mode features to a ReActAgent.

    At runtime this class is mixed into ``QwenPawAgent`` and combined
    with ``ToolGuardMixin`` and ``ReActAgent`` via MRO. Currently only
    overrides ``_build_sys_prompt`` to inject a coding persona block.
    """

    # ------------------------------------------------------------------
    # System prompt injection
    # ------------------------------------------------------------------

    def _build_sys_prompt(self) -> str:  # noqa: D102
        """Append the Coding Mode persona block to the base system prompt."""
        base: str = super()._build_sys_prompt()  # type: ignore[misc]
        if not self._coding_mode_enabled():
            return base
        workspace_dir = str(getattr(self, "_workspace_dir", "") or "(unknown)")
        # Resolve the active coding project dir from agent config
        project_dir = self._get_coding_project_dir() or workspace_dir
        coding_block = _CODING_SYSTEM_PROMPT_TEMPLATE.format(
            project_dir=project_dir,
            workspace_dir=workspace_dir,
        )
        return base + "\n\n" + coding_block

    def _get_coding_project_dir(self) -> str | None:
        """Return the active coding project dir.

        Always reloads from disk so changes made via the API (which persist to
        ``agent.json``) are reflected immediately rather than stale in-memory
        config being used.

        Returns None when no project has been set (use workspace default).
        """
        from ..config.config import load_agent_config

        # Determine agent id: prefer _agent_config.id, then self.name
        agent_config = getattr(self, "_agent_config", None)
        agent_id: str | None = None
        if agent_config is not None:
            if isinstance(agent_config, dict):
                agent_id = agent_config.get("id")
            else:
                agent_id = getattr(agent_config, "id", None)
        if not agent_id:
            agent_id = getattr(self, "name", None)
        if not agent_id:
            return None

        try:
            config = load_agent_config(agent_id)
            cm = config.coding_mode
            if cm and cm.project_dir:
                return cm.project_dir
        except Exception:  # noqa: BLE001
            pass

        # Fallback to stale in-memory config
        if agent_config is None:
            return None
        if isinstance(agent_config, dict):
            cm_dict = agent_config.get("coding_mode") or {}
            return cm_dict.get("project_dir") or None
        cm_obj = getattr(agent_config, "coding_mode", None)
        return getattr(cm_obj, "project_dir", None) or None

    # ------------------------------------------------------------------
    # Helpers: config access
    # ------------------------------------------------------------------

    def _coding_mode_enabled(self) -> bool:
        """Return ``True`` when Coding Mode is active."""
        agent_config = getattr(self, "_agent_config", None)
        if agent_config is None:
            return False
        if isinstance(agent_config, dict):
            cm = agent_config.get("coding_mode") or {}
            return bool(cm.get("enabled", False))
        cm = getattr(agent_config, "coding_mode", None)
        if cm is None:
            return False
        return bool(getattr(cm, "enabled", False))
