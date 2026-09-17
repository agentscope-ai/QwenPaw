# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
"""Agent skills: domain knowledge catalogs for the Creator main Agent.

A skill is a local directory carrying a single SKILL.md document. Builtin
skills ship inside the backend source tree under ``skills/``; additional
directories can be declared in
``<CREATOR_DATA_ROOT>/config/skills_config.json``. Loading is fully
isolated: any parse failure, missing path or unmet requirement marks the
skill ``unavailable`` with a readable reason and never raises, so session
establishment and the existing Creator pipeline are unaffected.

Skills follow the AgentScope viewer contract and provide domain knowledge
only — problem decomposition methods, pacing, copy rules, layout styles
and templates. The system prompt carries a bounded name/description
catalog, the agent pulls the full SKILL.md through the read-only
``view_skill`` tool, and every deliverable (visuals, narration, timeline)
is built from the ground up with native Creator tools and data structures
(Elements, assets, specialist delegation). There is no skill sandbox, no
skill-side script execution and no side-channel media pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any

from models.config import load_skills_config, load_skills_config_issues
from schemas.skills import SkillEntry, SkillRequirement, SkillRequirementKind
from services.observability import trace_event
from utils.logger import setup_logger

logger = setup_logger("creator.external_skills")

SKILL_CONTEXT_MAX_CHARS = 8000
# Upper bound for one SKILL.md returned by the viewer tool.
SKILL_FILE_READ_MAX_BYTES = 256 * 1024

VIEW_SKILL_TOOL_NAME = "view_skill"

EXTERNAL_SKILL_TOOL_NAMES = frozenset({VIEW_SKILL_TOOL_NAME})

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_NODE_VERSION = re.compile(r"v?(\d+)")


class SkillExecutionError(RuntimeError):
    """A skill lookup/view request that must be refused."""


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    entry: SkillEntry
    status: str  # "available" | "unavailable"
    reason: str | None
    skill_md: str
    root: Path

    @property
    def available(self) -> bool:
        return self.status == "available"


# ── SKILL.md parsing ─────────────────────────────────────────────────────────


def parse_skill_md(text: str) -> dict[str, Any]:
    """Extract front matter (name/description) and body from SKILL.md."""

    match = _FRONT_MATTER.match(text)
    if match is None:
        raise ValueError("SKILL.md front matter block (--- ... ---) not found")
    import yaml

    meta = yaml.safe_load(match.group(1))
    if not isinstance(meta, dict):
        raise ValueError("SKILL.md front matter must be a YAML mapping")
    body = text[match.end() :].strip()
    return {
        "name": str(meta.get("name") or "").strip(),
        "description": str(meta.get("description") or "").strip(),
        "body": body,
    }


# ── Requirement probing ──────────────────────────────────────────────────────


def _probe_requirement(requirement: SkillRequirement) -> str | None:
    """Return a readable failure reason, or None when satisfied.

    Domain-knowledge skills normally declare no requirements; the probe is
    kept for configured entries whose knowledge only applies when a host
    capability (binary/env/node) is actually present.
    """

    if requirement.kind is SkillRequirementKind.BINARY:
        if shutil.which(requirement.value) is None:
            return (
                f"required binary not found on PATH: {requirement.value}; "
                f"install it manually (e.g. via a system package manager)"
            )
        return None
    if requirement.kind is SkillRequirementKind.ENV:
        if not os.environ.get(requirement.value, "").strip():
            return (
                f"required env variable is not set: {requirement.value}; "
                f"export it in the Creator server environment before "
                f"enabling this skill"
            )
        return None
    if requirement.kind is SkillRequirementKind.NODE_MIN:
        node = shutil.which("node")
        if node is None:
            return (
                "required binary not found on PATH: node; install "
                f"Node.js >= {requirement.value} manually"
            )
        try:
            probe = subprocess.run(
                [node, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            match = _NODE_VERSION.match(probe.stdout.strip())
            major = int(match.group(1)) if match else -1
        except Exception as exc:
            return f"node --version probe failed: {type(exc).__name__}"
        minimum = int(str(requirement.value).lstrip("v").split(".", 1)[0])
        if major < minimum:
            return (
                f"node major version {major} is below required {minimum}; "
                f"upgrade Node.js manually"
            )
        return None
    return f"unknown requirement kind: {requirement.kind}"


def _load_one(entry: SkillEntry) -> LoadedSkill:
    root = Path(entry.path).expanduser()

    def unavailable(reason: str) -> LoadedSkill:
        return LoadedSkill(
            entry=entry,
            status="unavailable",
            reason=reason,
            skill_md="",
            root=root,
        )

    try:
        root = root.resolve(strict=False)
        if not root.is_dir():
            return unavailable(f"skill path is not a directory: {root}")
        skill_md_path = root / "SKILL.md"
        if not skill_md_path.is_file():
            return unavailable(f"SKILL.md not found under {root}")
        text = skill_md_path.read_text(encoding="utf-8")
        parse_skill_md(text)
        for requirement in entry.requirements:
            reason = _probe_requirement(requirement)
            if reason is not None:
                return unavailable(reason)
        return LoadedSkill(
            entry=entry,
            status="available",
            reason=None,
            skill_md=text,
            root=root,
        )
    except Exception as exc:  # Isolation: a bad skill never raises.
        return unavailable(f"skill load failed: {type(exc).__name__}: {exc}")


def _issue_placeholder(issue: dict) -> LoadedSkill:
    """Surface one rejected configuration entry as an unavailable skill."""

    entry = SkillEntry.model_construct(
        name=str(issue.get("name") or "invalid-entry"),
        path=str(issue.get("path") or ""),
        enabled=True,
        description=None,
        env=[],
        requirements=[],
    )
    return LoadedSkill(
        entry=entry,
        status="unavailable",
        reason=f"invalid configuration entry: {issue.get('reason')}",
        skill_md="",
        root=Path(str(issue.get("path") or "")),
    )


_LOAD_CACHE: tuple[float, tuple[str, ...], list[LoadedSkill]] | None = None
_LOAD_CACHE_TTL_SECONDS = 30.0

# Skills vendored inside the backend source tree. They ship with the code
# (domain knowledge only, no runtime requirements) and are always available
# without any skills_config.json entry.
_BUILTIN_SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skills"


def _builtin_entries(configured_names: set[str]) -> list[SkillEntry]:
    """Discover code-vendored skills under the backend ``skills/`` tree.

    A skills_config.json entry with the same name shadows the builtin
    (including a disabled one), so deployments keep full override control.
    """

    entries: list[SkillEntry] = []
    try:
        if not _BUILTIN_SKILLS_ROOT.is_dir():
            return entries
        for child in sorted(_BUILTIN_SKILLS_ROOT.iterdir()):
            if not child.is_dir() or not (child / "SKILL.md").is_file():
                continue
            if child.name in configured_names:
                continue
            try:
                entries.append(
                    SkillEntry(name=child.name, path=str(child)),
                )
            except Exception:
                logger.warning(
                    "builtin skill entry rejected: %s",
                    child,
                )
    except Exception:
        logger.exception("builtin skill scan failed; continuing without")
    return entries


def load_skills() -> list[LoadedSkill]:
    """Load builtin and configured skills; never raises.

    Rejected configuration entries (schema failures, duplicate names, a
    broken document) stay observable as ``unavailable`` placeholders with
    a readable reason instead of being silently dropped.
    """

    global _LOAD_CACHE
    try:
        config_entries = load_skills_config()
        configured_names = {entry.name for entry in config_entries}
        entries = [item for item in config_entries if item.enabled]
        entries.extend(_builtin_entries(configured_names))
        issues = load_skills_config_issues()
        signature = (
            *(entry.model_dump_json() for entry in entries),
            *(str(sorted(issue.items())) for issue in issues),
        )
        now = time.monotonic()
        if (
            _LOAD_CACHE is not None
            and _LOAD_CACHE[1] == signature
            and now - _LOAD_CACHE[0] < _LOAD_CACHE_TTL_SECONDS
        ):
            return list(_LOAD_CACHE[2])
        loaded = [_load_one(entry) for entry in entries]
        loaded.extend(_issue_placeholder(issue) for issue in issues)
        for skill in loaded:
            if not skill.available:
                logger.warning(
                    "external skill unavailable: name=%s reason=%s",
                    skill.entry.name,
                    skill.reason,
                )
        _LOAD_CACHE = (now, signature, loaded)
        return list(loaded)
    except Exception:
        logger.exception("external skill loading failed; continuing empty")
        return []


def _clear_load_cache() -> None:
    global _LOAD_CACHE
    _LOAD_CACHE = None


# ── System prompt context ────────────────────────────────────────────────────


def _skill_context_block(skill: LoadedSkill) -> str:
    parsed = parse_skill_md(skill.skill_md)
    description = (
        skill.entry.description or parsed["description"] or "（无描述）"
    ).strip()
    return (
        "<skill>\n"
        f"<name>{skill.entry.name}</name>\n"
        f"<description>{description}</description>\n"
        "</skill>"
    )


# Mirrors the AgentScope skill-viewer contract: the prompt only carries a
# name/description catalog and the agent must pull the full SKILL.md via
# the viewer tool before following a skill.
_CONTEXT_HEADER = (
    "<agent-skills>\n"
    "以下是当前可用的 Agent Skill。Skill 提供领域知识——拆解方法、节奏把控、"
    "文案规范、版式风格与模板等。当用户请求命中某个 skill 的适用场景时，"
    f"先用 `{VIEW_SKILL_TOOL_NAME}` 工具读取它的完整说明（SKILL.md），再按"
    "其中的领域知识组织创作。\n"
    "**IMPORTANT**: Skill 不是工具，也不是生产线：画面、配音、时间轴等一切"
    "产物都通过 Creator 原生工具与数据结构（Element、资产、委派 "
    "specialist）从源头构建。\n"
    "\n"
    "# Available Skills:"
)


def render_external_skills_context(
    skills: list[LoadedSkill] | None = None,
) -> str:
    """Build the bounded ``external_skills`` placeholder value.

    Available skills are appended in configuration order under a total
    budget of ``SKILL_CONTEXT_MAX_CHARS``; the block that overflows is
    truncated and later blocks are dropped, with a trace warning. No
    available skill renders an empty string (placeholder-compatible).
    """

    try:
        if skills is None:
            skills = load_skills()
        available = [skill for skill in skills if skill.available]
        if not available:
            return ""
        parts = [_CONTEXT_HEADER]
        footer = "\n</agent-skills>"
        budget = SKILL_CONTEXT_MAX_CHARS - len(footer)
        used = len(_CONTEXT_HEADER)
        truncated = False
        for skill in available:
            block = "\n\n" + _skill_context_block(skill)
            if used + len(block) > budget:
                remaining = budget - used
                if remaining > 0:
                    parts.append(block[:remaining])
                truncated = True
                break
            parts.append(block)
            used += len(block)
        if truncated:
            trace_event(
                "creator.external_skills.context_truncated",
                component="creator.external_skills",
                status="warning",
                attributes={
                    "maxChars": SKILL_CONTEXT_MAX_CHARS,
                    "availableSkills": [
                        skill.entry.name for skill in available
                    ],
                },
            )
            logger.warning(
                "external skills context truncated at %s chars",
                SKILL_CONTEXT_MAX_CHARS,
            )
        parts.append(footer)
        return "".join(parts)
    except Exception:
        logger.exception(
            "external skills context build failed; injecting empty",
        )
        return ""


# ── Skill viewer ─────────────────────────────────────────────────────────────


def find_skill(name: str) -> LoadedSkill:
    for skill in load_skills():
        if skill.entry.name == name:
            return skill
    raise SkillExecutionError(f"skill is not configured or disabled: {name}")


def _require_available(name: str) -> LoadedSkill:
    skill = find_skill(name)
    if not skill.available:
        raise SkillExecutionError(
            f"skill {name} is unavailable: {skill.reason}",
        )
    return skill


def view_skill(*, skill_name: str) -> dict[str, Any]:
    """Return the full SKILL.md of one available skill (viewer tool).

    Mirrors the AgentScope built-in skill viewer: the prompt catalog only
    lists names and descriptions, and the agent pulls the authoritative
    domain knowledge on demand through this read-only tool.
    """

    skill = _require_available(skill_name)
    markdown = skill.skill_md
    truncated = len(markdown.encode("utf-8")) > SKILL_FILE_READ_MAX_BYTES
    if truncated:
        markdown = markdown.encode("utf-8")[:SKILL_FILE_READ_MAX_BYTES].decode(
            "utf-8",
            errors="replace",
        )
    return {
        "ok": True,
        "skill": skill.entry.name,
        "content": markdown,
        "truncated": truncated,
    }


# ── Main-Agent tool manifests ────────────────────────────────────────────────


def _flat_schema(
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    # projectId stays accepted for backwards compatibility but is neither
    # required nor trusted: the runtime always injects the authoritative
    # Project identity for skill tools.
    return {
        "type": "object",
        "properties": {
            "projectId": {"type": "string"},
            **properties,
        },
        "required": list(required),
        "additionalProperties": False,
    }


def external_skill_tool_manifests(
    skills: list[LoadedSkill],
) -> list[dict[str, Any]]:
    """Tool manifests for the main Agent when any skill is available."""

    names = sorted(skill.entry.name for skill in skills if skill.available)
    if not names:
        return []
    skill_property = {
        "type": "string",
        "enum": names,
        "description": "当前可用的 skill 名称。",
    }
    return [
        {
            "type": "function",
            "function": {
                "name": VIEW_SKILL_TOOL_NAME,
                "description": (
                    "读取一个 skill 的完整领域知识说明（SKILL.md 全文）。"
                    "使用任何 skill 前必须先调用本工具，再按其中的领域知识"
                    "用 Creator 原生工具组织创作。只读，不修改任何内容。"
                ),
                "parameters": _flat_schema(
                    {"skill": skill_property},
                    ["skill"],
                ),
            },
        },
    ]


__all__ = [
    "EXTERNAL_SKILL_TOOL_NAMES",
    "LoadedSkill",
    "SKILL_CONTEXT_MAX_CHARS",
    "SKILL_FILE_READ_MAX_BYTES",
    "SkillExecutionError",
    "VIEW_SKILL_TOOL_NAME",
    "external_skill_tool_manifests",
    "find_skill",
    "load_skills",
    "parse_skill_md",
    "render_external_skills_context",
    "view_skill",
]
