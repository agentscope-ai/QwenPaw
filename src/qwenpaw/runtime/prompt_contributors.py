# -*- coding: utf-8 -*-
"""Built-in :class:`PromptContributor` implementations.

Each contributor is responsible for one fragment of the system prompt.
``build_default_prompt_manager`` assembles a :class:`PromptManager`
pre-loaded with the built-in contributors, ready for ``build_sync(ctx)``.

Contributors read configuration from ``ctx.extras``:

* ``workspace_dir`` — from ``ctx.workspace_dir``
* ``agent_id``      — from ``ctx.agent_id``
* ``language``      — ``ctx.extras["language"]`` (default ``"zh"``)
* ``heartbeat_enabled`` — ``ctx.extras.get("heartbeat_enabled", False)``
* ``env_context``       — ``ctx.extras.get("env_context")``
* ``agent_config``      — ``ctx.extras.get("agent_config")``
* ``driver_prompt_hints`` — ``ctx.extras.get("driver_prompt_hints", [])``
* ``preloaded_skills`` — successfully preloaded AgentScope Skills
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .prompt_manager import PromptManager, SyncPromptContributor

if TYPE_CHECKING:
    from .hooks import HookContext

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT_FILES = ("AGENTS.md", "SOUL.md", "PROFILE.md")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_HEARTBEAT_PATTERN = re.compile(
    r"<!-- heartbeat:start -->.*?<!-- heartbeat:end -->",
    re.DOTALL,
)
_MEMORY_PATTERN = re.compile(
    r"<!-- memory:start -->.*?<!-- memory:end -->",
    re.DOTALL,
)


def _read_prompt_file(workspace_dir: Path, filename: str) -> str | None:
    """Read a markdown file from *workspace_dir* / *filename*.

    If the file starts with a ``---``-delimited YAML frontmatter block,
    that block is stripped and only the body content is returned.
    Returns ``None`` when the file does not exist or is empty after
    stripping.
    """
    try:
        workspace_root = workspace_dir.resolve()
        path = (workspace_root / filename).resolve()
        if path == workspace_root or not path.is_relative_to(workspace_root):
            logger.warning(
                "Prompt file %s resolves outside workspace, skipping",
                filename,
            )
            return None
        if not path.is_file():
            return None

        from ..agents.utils.file_handling import (
            decode_text_bytes_with_encoding_fallback,
        )
        from ..utils.file_snapshot_cache import get_file_snapshot_cache

        snapshot = get_file_snapshot_cache().get_bytes(path)
        content = decode_text_bytes_with_encoding_fallback(
            snapshot.data,
            file_name=path.name,
        ).strip()
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                content = parts[2].strip()
        return content or None
    except Exception:
        logger.warning("Failed to read %s, skipping", filename)
        return None


def _system_prompt_files(ctx: "HookContext") -> list[str]:
    """Return prompt files configured for the current agent.

    ``None`` means the profile predates the field, so use the historical
    defaults. An empty list is meaningful and disables workspace prompt files.
    """
    extras = getattr(ctx, "extras", {}) or {}
    agent_config = extras.get("agent_config")
    if agent_config is None:
        return list(DEFAULT_SYSTEM_PROMPT_FILES)
    files = getattr(agent_config, "system_prompt_files", None)
    if files is None:
        return list(DEFAULT_SYSTEM_PROMPT_FILES)
    return [str(filename) for filename in files]


def _process_heartbeat_section(content: str, enabled: bool) -> str:
    if "<!-- heartbeat:start -->" not in content:
        return content
    if enabled:
        content = content.replace("<!-- heartbeat:start -->", "")
        content = content.replace("<!-- heartbeat:end -->", "")
        return content.strip()
    return _HEARTBEAT_PATTERN.sub("", content).strip()


def _process_memory_section(
    content: str,
    memory_manager: Any | None,
) -> str:
    if "<!-- memory:start -->" in content:
        content = _MEMORY_PATTERN.sub("", content).strip()
    memory_section = ""
    if memory_manager is not None:
        memory_section = memory_manager.get_memory_prompt()
    if content and memory_section:
        return (content + "\n\n" + memory_section).strip()
    return (content or memory_section).strip()


# ---------------------------------------------------------------------------
# Contributors
# ---------------------------------------------------------------------------


class AgentIdentityContributor(SyncPromptContributor):
    """Prepend agent identity header when ``agent_id`` is set."""

    name = "agent_identity"
    priority = 5

    def contribute_sync(self, ctx: "HookContext") -> str | None:
        agent_id = getattr(ctx, "agent_id", None)
        if not agent_id:
            return None
        return (
            f"# Agent Identity\n\n"
            f"Your agent id is `{agent_id}`. "
            f"This is your unique identifier in the multi-agent system."
        )


class AgentsMdContributor(SyncPromptContributor):
    """Load ``AGENTS.md`` with heartbeat / memory section processing."""

    name = "agents_md"
    priority = 10

    def contribute_sync(self, ctx: "HookContext") -> str | None:
        wd = getattr(ctx, "workspace_dir", None)
        if not wd:
            return None
        content = _read_prompt_file(Path(wd), "AGENTS.md")
        if not content:
            return None
        extras = getattr(ctx, "extras", {}) or {}
        heartbeat_enabled = extras.get("heartbeat_enabled", False)
        try:
            content = _process_heartbeat_section(content, heartbeat_enabled)
        except Exception as e:
            logger.warning("Failed to process heartbeat: %s", e)
        memory_manager = extras.get("memory_manager")
        try:
            content = _process_memory_section(
                content,
                memory_manager,
            )
        except Exception as e:
            logger.warning("Failed to process memory section: %s", e)
        if not content:
            return None
        return f"# AGENTS.md\n\n{content}"


class SoulMdContributor(SyncPromptContributor):
    """Load ``SOUL.md``."""

    name = "soul_md"
    priority = 20

    def contribute_sync(self, ctx: "HookContext") -> str | None:
        wd = getattr(ctx, "workspace_dir", None)
        if not wd:
            return None
        content = _read_prompt_file(Path(wd), "SOUL.md")
        if not content:
            return None
        return f"# SOUL.md\n\n{content}"


class ProfileMdContributor(SyncPromptContributor):
    """Load ``PROFILE.md``."""

    name = "profile_md"
    priority = 30

    def contribute_sync(self, ctx: "HookContext") -> str | None:
        wd = getattr(ctx, "workspace_dir", None)
        if not wd:
            return None
        content = _read_prompt_file(Path(wd), "PROFILE.md")
        if not content:
            return None
        return f"# PROFILE.md\n\n{content}"


class WorkspacePromptFilesContributor(SyncPromptContributor):
    """Load configured workspace markdown files in UI-configured order."""

    name = "workspace_prompt_files"
    priority = 10

    def contribute_sync(self, ctx: "HookContext") -> str | None:
        wd = getattr(ctx, "workspace_dir", None)
        if not wd:
            return None

        workspace_dir = Path(wd)
        extras = getattr(ctx, "extras", {}) or {}
        parts: list[str] = []
        for filename in _system_prompt_files(ctx):
            content = _read_prompt_file(workspace_dir, filename)
            if not content:
                continue
            if filename == "AGENTS.md":
                content = self._process_agents_md(content, extras)
            if not content:
                continue
            parts.append(f"# {filename}\n\n{content}")
        return "\n\n".join(parts) or None

    @staticmethod
    def _process_agents_md(content: str, extras: dict[str, Any]) -> str:
        heartbeat_enabled = extras.get("heartbeat_enabled", False)
        try:
            content = _process_heartbeat_section(content, heartbeat_enabled)
        except Exception as e:
            logger.warning("Failed to process heartbeat: %s", e)
        memory_manager = extras.get("memory_manager")
        try:
            content = _process_memory_section(
                content,
                memory_manager,
            )
        except Exception as e:
            logger.warning("Failed to process memory section: %s", e)
        return content


class MultimodalHintContributor(SyncPromptContributor):
    """Inject multimodal capability awareness hint."""

    name = "multimodal_hint"
    priority = 80

    def contribute_sync(self, ctx: "HookContext") -> str | None:
        from ..agents.prompt import build_multimodal_hint

        hint = build_multimodal_hint()
        return hint or None


_DIRECTORY_CONTEXT_TEMPLATE = """\
### Directories

{project_dirs_block}
Agent workspace: {workspace_dir}

Relative file paths and shell commands resolve from the **primary
project directory** — `read_file("src/main.py")` and a bare `pytest`
both act on it, so you do not need to pass absolute paths or an
explicit `cwd` for ordinary work there.{extra_dirs_guidance}

The agent workspace holds internal QwenPaw state (config, memory,
sessions, skills). Do not read or write there unless the user asks.
"""

_EXTRA_DIRS_GUIDANCE = """
Other project directories are listed above. They are fully accessible,
but only by ABSOLUTE path — relative paths never resolve there. When
running shell commands in one, pass its path as the working directory."""

_DIRECTORY_CONTEXT_MISSING_SUFFIX = """\
WARNING: the configured primary project directory does not currently
exist. Tell the user instead of writing files to a different location.
"""


def _format_project_dirs_block(entries: list[tuple]) -> str:
    """Render the numbered directory list with a primary marker.

    ``entries`` is ``[(path, label, is_missing), ...]``, primary first.
    """
    if len(entries) == 1:
        path, label, _missing = entries[0]
        suffix = f" — {label}" if label else ""
        return f"Project directory (primary): {path}{suffix}"

    lines = ["Project directories:"]
    for index, (path, label, missing) in enumerate(entries, start=1):
        marker = " (primary)" if index == 1 else ""
        note = f" — {label}" if label else ""
        missing_note = " [MISSING]" if missing else ""
        lines.append(f"{index}. {path}{marker}{note}{missing_note}")
    return "\n".join(lines)


class DirectoryContextContributor(SyncPromptContributor):
    """State the project dirs and agent workspace, in every mode.

    Project directories are not a Coding Mode concept — normal chats
    resolve relative paths the same way — so this block is unconditional
    rather than gated on a mode being active.
    """

    name = "directory_context"
    priority = 84

    def contribute_sync(self, ctx: "HookContext") -> str | None:
        from ..config.context import (
            get_current_project_dir,
            get_current_project_dir_source,
            get_current_project_dirs,
        )

        workspace_dir = getattr(ctx, "workspace_dir", None)
        project_dir = get_current_project_dir()
        dirs = get_current_project_dirs() or ()
        if project_dir is None:
            # Direct builder calls (tests, harnesses) skip the hook;
            # fall back to the stamped config so the prompt still
            # agrees with where the tools operate.
            extras = getattr(ctx, "extras", {}) or {}
            agent_config = extras.get("agent_config")
            fallback = getattr(agent_config, "project_dir", None)
            if fallback:
                project_dir = fallback
        if project_dir is None:
            project_dir = workspace_dir
        if project_dir is None:
            return None

        # When no project was ever configured the two paths are
        # identical; printing the same path twice under two labels
        # invites the model to treat internal state as project content.
        if workspace_dir is not None and str(project_dir) == str(
            workspace_dir,
        ):
            return (
                "### Directories\n\n"
                f"Working directory: {project_dir}\n\n"
                "Relative file paths and shell commands resolve from "
                "here. This directory also holds internal QwenPaw state "
                "(config, memory, sessions, skills); leave those files "
                "alone unless the user asks about them.\n"
            )

        entries = [
            (str(entry.path), entry.label, not entry.exists) for entry in dirs
        ]
        if not entries:
            entries = [(str(project_dir), None, False)]
        block = _DIRECTORY_CONTEXT_TEMPLATE.format(
            project_dirs_block=_format_project_dirs_block(entries),
            workspace_dir=workspace_dir or "(unknown)",
            extra_dirs_guidance=(
                _EXTRA_DIRS_GUIDANCE if len(entries) > 1 else ""
            ),
        )
        if get_current_project_dir_source() != "workspace_fallback" and not (
            Path(project_dir).is_dir()
        ):
            block = f"{block}\n{_DIRECTORY_CONTEXT_MISSING_SUFFIX}"
        return block


class CodingModeContributor(SyncPromptContributor):
    """Inject Coding Mode persona block when coding mode is active.

    Only code-specific guidance lives here. The project/workspace paths
    themselves come from :class:`DirectoryContextContributor`, which
    runs for every mode.
    """

    name = "coding_mode"
    priority = 85

    def contribute_sync(self, ctx: "HookContext") -> str | None:
        extras = getattr(ctx, "extras", {}) or {}
        agent_config = extras.get("agent_config")
        if agent_config is None:
            return None
        cm = getattr(agent_config, "coding_mode", None)
        if not cm or not getattr(cm, "enabled", False):
            return None
        from ..modes.coding import _CODING_SYSTEM_PROMPT_TEMPLATE

        return _CODING_SYSTEM_PROMPT_TEMPLATE


class ScrollContextContributor(SyncPromptContributor):
    """Inject memory/recall guidance when the scroll context strategy is on."""

    name = "scroll_context"
    priority = 86

    def contribute_sync(self, ctx: "HookContext") -> str | None:
        extras = getattr(ctx, "extras", {}) or {}
        agent_config = extras.get("agent_config")
        if agent_config is None:
            return None
        try:
            strategy = agent_config.running.light_context_config.strategy
        except Exception:
            return None
        if strategy != "scroll":
            return None
        from ..agents.context.scroll.prompt import build_scroll_system_prompt

        language = getattr(agent_config, "language", "en")
        return build_scroll_system_prompt(language)


class EnvContextContributor(SyncPromptContributor):
    """Append the environment context block (time / session / OS)."""

    name = "env_context"
    priority = 90

    def contribute_sync(self, ctx: "HookContext") -> str | None:
        extras = getattr(ctx, "extras", {}) or {}
        return extras.get("env_context") or None


class DriverPolicyHintContributor(SyncPromptContributor):
    """Append request-time Driver policy guidance when tools are exposed."""

    name = "driver_policy_hint"
    priority = 88

    def contribute_sync(self, ctx: "HookContext") -> str | None:
        extras = getattr(ctx, "extras", {}) or {}
        hints = extras.get("driver_prompt_hints") or []
        rendered = "\n\n".join(str(hint) for hint in hints if hint)
        return rendered or None


class PreloadedSkillsContributor(SyncPromptContributor):
    """Add successfully preloaded Skill instructions to the system prompt."""

    name = "preloaded_skills"
    priority = 95

    def contribute_sync(self, ctx: "HookContext") -> str | None:
        extras = getattr(ctx, "extras", {}) or {}
        skills = extras.get("preloaded_skills") or []
        if not skills:
            return None

        parts = [
            "<preloaded-skills>",
            (
                "The following Skills are already loaded. Follow their "
                "instructions directly when relevant, and do not load them "
                "again with the Skill Viewer."
            ),
        ]
        for skill in skills:
            parts.extend(
                [
                    "",
                    "<skill>",
                    f"<name>{skill.name}</name>",
                    f"<description>{skill.description}</description>",
                    f"<dir>{skill.dir}</dir>",
                    "",
                    skill.markdown,
                    "</skill>",
                ],
            )
        parts.append("</preloaded-skills>")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_ALL_CONTRIBUTORS = (
    AgentIdentityContributor,
    WorkspacePromptFilesContributor,
    MultimodalHintContributor,
    DirectoryContextContributor,
    CodingModeContributor,
    ScrollContextContributor,
    DriverPolicyHintContributor,
    EnvContextContributor,
    PreloadedSkillsContributor,
)


def build_default_prompt_manager() -> PromptManager:
    """Create a :class:`PromptManager` with all built-in contributors."""
    pm = PromptManager()
    for cls in _ALL_CONTRIBUTORS:
        pm.register(cls())
    return pm


__all__ = [
    "AgentIdentityContributor",
    "AgentsMdContributor",
    "SoulMdContributor",
    "ProfileMdContributor",
    "WorkspacePromptFilesContributor",
    "MultimodalHintContributor",
    "DirectoryContextContributor",
    "CodingModeContributor",
    "ScrollContextContributor",
    "DriverPolicyHintContributor",
    "EnvContextContributor",
    "PreloadedSkillsContributor",
    "build_default_prompt_manager",
]
