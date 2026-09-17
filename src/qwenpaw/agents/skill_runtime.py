# -*- coding: utf-8 -*-
"""Runtime skill discovery, loading, and intent routing."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import frontmatter
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ..config.context import (
    get_current_channel_name,
    get_current_workspace_dir,
)
from ..constant import WORKING_DIR
from .skill_system import (
    ensure_skills_initialized,
    get_workspace_skills_dir,
    resolve_effective_skills,
)
from .utils.file_handling import read_text_file_with_encoding_fallback

logger = logging.getLogger(__name__)

RouteKind = Literal["info", "list", "invoke", "clarify"]


@dataclass(frozen=True)
class SkillMeta:
    """Enabled skill metadata used by runtime routing."""

    name: str
    display_name: str
    description: str
    skill_dir: Path
    skill_md_path: Path
    source: str = "workspace"
    shadowed_by: str | None = None


@dataclass(frozen=True)
class SkillRoute:
    """Resolved skill routing decision."""

    kind: RouteKind
    skill: SkillMeta | None = None
    args: str = ""
    reason: str = ""
    candidates: tuple[tuple[str, int], ...] = ()
    skills: tuple[SkillMeta, ...] = ()
    diagnostics: tuple[str, ...] = ()


_WORD_RE = re.compile(r"[a-zA-Z0-9_-]+")
_EXPLICIT_RE = re.compile(
    r"(?:调用|使用|加载|启用|用|通过|invoke|use|load)\s+/?([a-zA-Z0-9_.-]+)",
    re.IGNORECASE,
)
_INLINE_SLASH_SKILL_RE = re.compile(r"(^|\s)/([a-zA-Z0-9_.-]+)(?=\s|$)")

_CAPABILITY_SPECS: dict[str, dict[str, set[str]]] = {
    "image": {
        "skill": {
            "image",
            "images",
            "picture",
            "photo",
            "poster",
            "illustration",
            "bitmap",
            "visual",
            "mockup",
            "imagegen",
            "nano-banana",
            "图片",
            "图像",
            "照片",
            "海报",
            "插画",
        },
        "query": {
            "image",
            "images",
            "picture",
            "photo",
            "poster",
            "illustration",
            "图片",
            "图像",
            "照片",
            "海报",
            "插画",
            "画图",
            "绘图",
            "生图",
            "生成图",
            "设计图",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
        },
    },
    "document": {
        "skill": {
            "docx",
            "word",
            "document",
            "documents",
            "memo",
            "letter",
            "文档",
            "报告",
            "word文档",
        },
        "query": {
            "docx",
            "word",
            "document",
            "documents",
            "memo",
            "letter",
            "report",
            "文档",
            "word文档",
            "报告",
            ".docx",
        },
    },
    "spreadsheet": {
        "skill": {
            "xlsx",
            "xls",
            "excel",
            "spreadsheet",
            "csv",
            "table",
            "表格",
            "电子表格",
        },
        "query": {
            "xlsx",
            "xls",
            "excel",
            "spreadsheet",
            "csv",
            "表格",
            "电子表格",
            ".xlsx",
            ".xls",
            ".csv",
        },
    },
    "presentation": {
        "skill": {
            "ppt",
            "pptx",
            "powerpoint",
            "presentation",
            "slides",
            "deck",
            "幻灯片",
            "演示",
        },
        "query": {
            "ppt",
            "pptx",
            "powerpoint",
            "presentation",
            "slides",
            "deck",
            "report",
            "幻灯片",
            "演示",
            "报告",
            ".pptx",
        },
    },
    "pdf": {
        "skill": {"pdf", "表单", "ocr"},
        "query": {"pdf", ".pdf", "表单", "ocr", "report", "报告"},
    },
    "browser": {
        "skill": {
            "browser",
            "playwright",
            "web",
            "website",
            "screenshot",
            "网页",
            "浏览器",
        },
        "query": {
            "browser",
            "playwright",
            "website",
            "webpage",
            "网页",
            "浏览器",
            "截图",
            "http://",
            "https://",
        },
    },
    "video": {
        "skill": {"video", "youtube", "bilibili", "douyin", "视频", "抖音"},
        "query": {"video", "youtube", "bilibili", "douyin", "视频", "抖音"},
    },
}

_DELIVERABLE_TERMS = {
    "report",
    "document",
    "presentation",
    "slides",
    "deck",
    "spreadsheet",
    "image",
    "poster",
    "pdf",
    "报告",
    "文档",
    "ppt",
    "幻灯片",
    "表格",
    "图片",
    "海报",
}


def _normalize_name(value: str) -> str:
    return str(value or "").strip().lower()


def _skill_aliases(skill: SkillMeta) -> set[str]:
    return {
        _normalize_name(skill.name),
        _normalize_name(skill.display_name),
        _normalize_name(skill.skill_dir.name),
    } - {""}


def _read_skill_post(skill_dir: Path) -> tuple[str, Any]:
    skill_md_path = skill_dir / "SKILL.md"
    raw = read_text_file_with_encoding_fallback(skill_md_path)
    return raw, frontmatter.loads(raw)


def discover_enabled_skills(
    workspace_dir: Path | None,
    channel_name: str | None,
) -> list[SkillMeta]:
    """Return enabled skills for the workspace and channel."""

    workspace = Path(workspace_dir or WORKING_DIR)
    channel = channel_name or "console"
    ensure_skills_initialized(workspace)
    skill_names = resolve_effective_skills(workspace, channel)
    skills_dir = get_workspace_skills_dir(workspace)
    result: list[SkillMeta] = []
    seen_aliases: dict[str, str] = {}
    for skill_name in skill_names:
        skill_dir = skills_dir / skill_name
        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.exists():
            continue
        try:
            _, post = _read_skill_post(skill_dir)
        except Exception as exc:
            logger.warning(
                "Failed to read skill metadata '%s': %s",
                skill_name,
                exc,
            )
            continue
        meta = SkillMeta(
            name=skill_name,
            display_name=str(post.get("name") or skill_name),
            description=str(post.get("description") or ""),
            skill_dir=skill_dir,
            skill_md_path=skill_md_path,
        )
        aliases = _skill_aliases(meta)
        shadowed_by = next(
            (seen_aliases[alias] for alias in aliases if alias in seen_aliases),
            None,
        )
        if shadowed_by is not None:
            logger.info(
                "Skill inventory: %s shadowed by %s",
                skill_name,
                shadowed_by,
            )
            result.append(
                SkillMeta(
                    name=meta.name,
                    display_name=meta.display_name,
                    description=meta.description,
                    skill_dir=meta.skill_dir,
                    skill_md_path=meta.skill_md_path,
                    source=meta.source,
                    shadowed_by=shadowed_by,
                ),
            )
            continue
        for alias in aliases:
            seen_aliases.setdefault(alias, skill_name)
        result.append(meta)
    return [skill for skill in result if skill.shadowed_by is None]


def resolve_enabled_skill(
    workspace_dir: Path | None,
    channel_name: str | None,
    requested: str,
) -> SkillMeta | None:
    """Resolve an enabled skill by directory name or frontmatter name."""

    wanted = _normalize_name(requested).lstrip("/$")
    if not wanted:
        return None
    for skill in discover_enabled_skills(workspace_dir, channel_name):
        if wanted in _skill_aliases(skill):
            return skill
    return None


def render_skill_list(skills: list[SkillMeta]) -> str:
    if not skills:
        return "No enabled skills are available for this channel."
    lines = ["**Enabled skills**"]
    for skill in sorted(skills, key=lambda item: item.name.lower()):
        if skill.shadowed_by is not None:
            continue
        desc = f" - {skill.description}" if skill.description else ""
        lines.append(f"- `{skill.name}`{desc}")
    return "\n".join(lines)


def render_skill_info(skill: SkillMeta) -> str:
    desc = skill.description or "No description."
    return (
        f"**{skill.name}**\n\n"
        f"- **command**: `/{skill.name} <input>` to invoke\n"
        f"- **name**: {skill.display_name}\n"
        f"- **description**: {desc}\n"
        f"- **path**: `{skill.skill_dir}`"
    )


def route_to_prompt(route: SkillRoute) -> str:
    """Build a short instruction injected before the original user text."""

    if route.kind != "invoke" or route.skill is None:
        return ""
    payload = {
        "skill": route.skill.name,
        "args": route.args,
        "reason": route.reason,
        "candidates": list(route.candidates),
    }
    return (
        "[Skill routing]\n"
        "The user's request matches an enabled local skill. "
        "Before doing the task, call the `load_skill` tool with "
        f"`skill={route.skill.name}` and `args` set to the user's task. "
        "Then follow the loaded SKILL.md instructions.\n"
        f"Routing metadata: {json.dumps(payload, ensure_ascii=False)}\n"
        "---\n"
    )


def _render_skill_runtime_prefix(meta: SkillMeta) -> str:
    skill_dir = str(meta.skill_dir)
    return (
        "[QwenPaw skill runtime]\n"
        f"- This skill is installed at: `{skill_dir}`.\n"
        "- Treat relative paths inside SKILL.md as relative to that skill "
        "directory, not the workspace root.\n"
        "- When running a bundled script from this skill, set the command "
        "working directory to the skill directory or prefix the command with "
        f"`cd \"{skill_dir}\" && ...`.\n"
        "- Save user-facing outputs in the workspace unless SKILL.md says "
        "otherwise.\n"
        "---\n\n"
    )


def _split_slash_invocation(query: str) -> tuple[str, str] | None:
    stripped = query.strip()
    if not stripped.startswith("/"):
        return None
    rest = stripped[1:]
    if rest.startswith("["):
        close = rest.find("]")
        if close < 0:
            return None
        name = rest[1:close].strip()
        args = rest[close + 1 :].strip()
        return (name, args) if name else None
    parts = rest.split(None, 1)
    if not parts:
        return None
    return parts[0], parts[1] if len(parts) > 1 else ""


def _first_token(text: str) -> str:
    match = _WORD_RE.match(text.strip())
    return match.group(0) if match else ""


def _text_has_term(text: str, term: str) -> bool:
    if not term:
        return False
    if re.fullmatch(r"[a-z0-9_.-]+", term):
        pattern = rf"(?<![a-z0-9_.-]){re.escape(term)}(?![a-z0-9_.-])"
        return re.search(pattern, text) is not None
    return term in text


def _matched_terms(text: str, terms: set[str]) -> set[str]:
    lowered = text.lower()
    return {term for term in terms if _text_has_term(lowered, term.lower())}


def _skill_domains(skill: SkillMeta) -> tuple[set[str], set[str]]:
    name_text = f"{skill.name} {skill.display_name} {skill.skill_dir.name}".lower()
    desc_text = skill.description.lower()
    primary: set[str] = set()
    secondary: set[str] = set()
    for domain, spec in _CAPABILITY_SPECS.items():
        skill_terms = spec["skill"]
        if _matched_terms(name_text, skill_terms):
            primary.add(domain)
        elif _matched_terms(desc_text, skill_terms):
            secondary.add(domain)

    # A description may mention an adjacent capability (for example
    # "replace images in Word documents"). Keep that as secondary unless the
    # skill name/frontmatter name itself declares the capability.
    if not primary and secondary:
        primary.add(next(iter(sorted(secondary))))
    return primary, secondary - primary


def _query_domains(query: str) -> set[str]:
    query_lower = query.lower()
    domains: set[str] = set()
    for domain, spec in _CAPABILITY_SPECS.items():
        if _matched_terms(query_lower, spec["query"]):
            domains.add(domain)
    return domains


def _query_terms(query: str) -> set[str]:
    return {
        term
        for term in re.split(r"[\s,，。.!?！？、:：;；()（）\[\]【】]+", query.lower())
        if len(term) >= 2
    }


def _score_semantic(query: str, skill: SkillMeta) -> tuple[int, str]:
    haystack = f"{skill.name} {skill.display_name} {skill.description}".lower()
    query_lower = query.lower()
    primary_domains, secondary_domains = _skill_domains(skill)
    requested_domains = _query_domains(query)
    score = 0
    reasons: list[str] = []

    primary_matches = primary_domains & requested_domains
    secondary_matches = secondary_domains & requested_domains
    if primary_matches:
        added = 12 * len(primary_matches)
        score += added
        reasons.append(f"primary={sorted(primary_matches)}(+{added})")
    if secondary_matches and primary_matches:
        added = 3 * len(secondary_matches)
        score += added
        reasons.append(f"secondary={sorted(secondary_matches)}(+{added})")

    # Weak lexical overlap. This helps locally named skills, but cannot by
    # itself make a skill high confidence.
    weak_hits = []
    for term in _query_terms(query_lower):
        if term in _DELIVERABLE_TERMS:
            continue
        if term and term in haystack:
            weak_hits.append(term)
    if weak_hits:
        added = min(4, len(weak_hits))
        score += added
        reasons.append(f"weak={weak_hits[:5]}(+{added})")

    # Exact capability name in the query is useful for natural language
    # requests like "用 pdf 合并文件", while explicit skill names are handled
    # earlier and never reach semantic scoring.
    aliases = _skill_aliases(skill)
    if any(_text_has_term(query_lower, alias) for alias in aliases):
        score += 8
        reasons.append("alias(+8)")

    if score and not primary_matches and requested_domains:
        # Avoid accidental matches from scoped secondary mentions when the
        # request clearly belongs to another primary domain.
        score = min(score, 5)
        reasons.append("capped_no_primary")

    reason = ",".join(reasons) or "no_match"
    return score, reason


class SkillIntentRouter:
    """Resolve explicit, bare-name, and semantic skill invocations."""

    def __init__(self, skills: list[SkillMeta]) -> None:
        self._skills = skills

    def route(self, query: str | None) -> SkillRoute | None:
        text = str(query or "").strip()
        if not text:
            return None

        slash = _split_slash_invocation(text)
        if slash is not None:
            command, args = slash
            if _normalize_name(command) in {"skills", "skill"}:
                return self._route_skills_command(args)
            skill = self._find_skill(command)
            if skill is None:
                return None
            if not args:
                return SkillRoute(kind="info", skill=skill, reason="slash_info")
            return SkillRoute(
                kind="invoke",
                skill=skill,
                args=args,
                reason="slash_skill",
                candidates=((skill.name, 100),),
            )

        inline_slash = self._find_inline_slash_skill(text)
        if inline_slash is not None:
            skill, args = inline_slash
            return SkillRoute(
                kind="invoke",
                skill=skill,
                args=args,
                reason="inline_slash_skill",
                candidates=((skill.name, 98),),
            )

        explicit = _EXPLICIT_RE.search(text)
        if explicit:
            skill = self._find_skill(explicit.group(1))
            if skill is not None:
                args = text[explicit.end() :].strip() or text
                return SkillRoute(
                    kind="invoke",
                    skill=skill,
                    args=args,
                    reason="explicit_skill_name",
                    candidates=((skill.name, 95),),
                )

        first = _first_token(text)
        if first:
            skill = self._find_skill(first)
            if skill is not None:
                args = text[len(first) :].strip()
                return SkillRoute(
                    kind="invoke",
                    skill=skill,
                    args=args,
                    reason="bare_skill_name",
                    candidates=((skill.name, 90),),
                )

        return self._route_semantic(text)

    def _find_inline_slash_skill(
        self,
        text: str,
    ) -> tuple[SkillMeta, str] | None:
        for match in _INLINE_SLASH_SKILL_RE.finditer(text):
            command = match.group(2)
            if _normalize_name(command) in {"skill", "skills"}:
                continue
            skill = self._find_skill(command)
            if skill is None:
                continue
            args = text[match.end() :].strip()
            if not args:
                args = (
                    text[: match.start()].strip()
                    + " "
                    + text[match.end() :].strip()
                ).strip()
            return skill, args or text
        return None

    def _route_skills_command(self, args: str) -> SkillRoute:
        parts = args.split(None, 1)
        if not parts or _normalize_name(parts[0]) in {"list", "ls"}:
            return SkillRoute(
                kind="list",
                reason="skills_list",
                skills=tuple(self._skills),
            )
        subcommand = _normalize_name(parts[0])
        rest = parts[1] if len(parts) > 1 else ""
        if subcommand in {"help"}:
            return SkillRoute(
                kind="list",
                reason="skills_help",
                skills=tuple(self._skills),
            )
        if subcommand in {"show", "info"}:
            skill = self._find_skill(rest)
            return (
                SkillRoute(kind="info", skill=skill, reason="skills_info")
                if skill is not None
                else SkillRoute(
                    kind="list",
                    reason="skills_info_missing",
                    skills=tuple(self._skills),
                )
            )
        skill = self._find_skill(parts[0])
        if skill is None:
            return SkillRoute(
                kind="list",
                reason="skills_unknown",
                skills=tuple(self._skills),
            )
        return SkillRoute(
            kind="invoke",
            skill=skill,
            args=rest,
            reason="skills_invoke",
            candidates=((skill.name, 100),),
        )

    def _find_skill(self, requested: str) -> SkillMeta | None:
        wanted = _normalize_name(requested).lstrip("/$")
        if not wanted:
            return None
        for skill in self._skills:
            if wanted in _skill_aliases(skill):
                return skill
        return None

    def _route_semantic(self, text: str) -> SkillRoute | None:
        scored = []
        diagnostics = []
        for skill in self._skills:
            score, reason = _score_semantic(text, skill)
            scored.append((skill, score, reason))
            if score > 0:
                primary, secondary = _skill_domains(skill)
                diagnostics.append(
                    f"{skill.name}: score={score} reason={reason} "
                    f"primary={sorted(primary)} "
                    f"secondary={sorted(secondary)}",
                )
        scored = [(skill, score) for skill, score, _ in scored if score > 0]
        scored.sort(key=lambda item: (-item[1], item[0].name.lower()))
        if not scored:
            logger.info("Skill router: no semantic candidates")
            return None
        candidates = tuple((skill.name, score) for skill, score in scored[:3])
        logger.info(
            "Skill router semantic diagnostics: %s",
            "; ".join(diagnostics),
        )
        best, best_score = scored[0]
        second_score = scored[1][1] if len(scored) > 1 else 0
        if best_score < 8:
            logger.info(
                "Skill router: semantic match not confident: %s",
                candidates,
            )
            return None
        if second_score and best_score - second_score <= 2:
            logger.info(
                "Skill router: semantic match ambiguous: %s",
                candidates,
            )
            return SkillRoute(
                kind="clarify",
                args=text,
                reason="semantic_ambiguous",
                candidates=candidates,
                skills=tuple(
                    skill
                    for skill, score in scored[:3]
                    if best_score - score <= 2
                ),
                diagnostics=tuple(diagnostics),
            )
        return SkillRoute(
            kind="invoke",
            skill=best,
            args=text,
            reason="semantic_description",
            candidates=candidates,
            diagnostics=tuple(diagnostics),
        )


async def load_skill(skill: str, args: str | None = None) -> ToolResponse:
    """Load an enabled local skill definition and its instructions.

    Call this tool before using a local skill. It only reads skills enabled
    for the current workspace and channel.

    Args:
        skill: Skill directory name or frontmatter name.
        args: Optional user task to pass through for context.
    """

    workspace_dir = get_current_workspace_dir() or WORKING_DIR
    channel_name = get_current_channel_name() or "console"
    meta = resolve_enabled_skill(workspace_dir, channel_name, skill)
    if meta is None:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        f"Error: skill '{skill}' is not enabled for "
                        f"channel '{channel_name}' or does not exist."
                    ),
                ),
            ],
        )
    raw, post = _read_skill_post(meta.skill_dir)
    runtime_prefix = _render_skill_runtime_prefix(meta)
    payload = {
        "skill": meta.name,
        "name": str(post.get("name") or meta.display_name),
        "description": str(post.get("description") or ""),
        "path": str(meta.skill_md_path),
        "skill_dir": str(meta.skill_dir),
        "runtime_note": (
            "Relative paths in SKILL.md are resolved from skill_dir. "
            "Run bundled scripts from skill_dir, not the workspace root."
        ),
        "args": args or "",
        "prompt": runtime_prefix + post.content,
        "raw": raw,
    }
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(payload, ensure_ascii=False, indent=2),
            ),
        ],
    )
