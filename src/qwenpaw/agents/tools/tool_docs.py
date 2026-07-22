# -*- coding: utf-8 -*-
"""Load curated built-in tool docs and runtime parameter schemas.

Curated markdown lives under ``docs/{lang}/{tool_name}.md`` (zh/en). Console
UI may request any locale; resolution falls back exact → base → en → runtime
docstring / config description.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_DOCS_ROOT = Path(__file__).resolve().parent / "docs"


def normalize_tool_doc_lang(lang: str | None) -> str:
    """Normalize a Console / Accept-Language style code for doc lookup.

    Examples: ``zh-CN`` → ``zh``, ``en-US`` → ``en``, ``pt-BR`` → ``pt-BR``.
    Empty / unknown values become ``en``.
    """
    if not lang or not str(lang).strip():
        return "en"
    raw = str(lang).strip().replace("_", "-")
    lower = raw.lower()
    if lower.startswith("zh"):
        return "zh"
    if lower.startswith("en"):
        return "en"
    # Preserve region variants that may have dedicated packs later (pt-BR).
    if "-" in raw:
        primary, region = raw.split("-", 1)
        if primary.lower() == "pt" and region.upper() == "BR":
            return "pt-BR"
        return primary.lower()
    return lower


def _lang_candidates(lang: str | None) -> list[str]:
    """Ordered language candidates for curated doc lookup."""
    normalized = normalize_tool_doc_lang(lang)
    candidates: list[str] = []
    for item in (normalized, normalized.split("-")[0], "en"):
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def _parse_doc_markdown(text: str) -> dict[str, str]:
    """Parse optional YAML frontmatter ``summary`` and markdown body."""
    summary = ""
    body = text.strip()
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) >= 3:
            front = parts[1]
            body = parts[2].strip()
            for line in front.splitlines():
                line = line.strip()
                if line.lower().startswith("summary:"):
                    summary = line.split(":", 1)[1].strip().strip("\"'")
                    break
    return {"summary": summary, "body": body}


def _read_doc_file(tool_name: str, lang: str) -> dict[str, str] | None:
    path = _DOCS_ROOT / lang / f"{tool_name}.md"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to read tool doc %s: %s", path, exc)
        return None
    parsed = _parse_doc_markdown(text)
    if not parsed["summary"] and not parsed["body"]:
        return None
    return parsed


def load_tool_doc(
    tool_name: str,
    lang: str | None = "en",
) -> dict[str, str] | None:
    """Load curated tool documentation with language fallback.

    Returns:
        ``{"summary": str, "body": str}`` or ``None`` when no curated file
        exists for any candidate language.
    """
    for candidate in _lang_candidates(lang):
        doc = _read_doc_file(tool_name, candidate)
        if doc is not None:
            return doc
    return None


@lru_cache(maxsize=1)
def _builtin_tool_func_map() -> dict[str, Callable[..., Any]]:
    """Map tool name → callable for schema extraction."""
    # Import registers @tool_descriptor builtins.
    from . import discover_builtin_tool_funcs

    mapping: dict[str, Callable[..., Any]] = {}
    for func in discover_builtin_tool_funcs():
        name = getattr(func, "__name__", None)
        descriptor = getattr(func, "_tool_descriptor", None)
        if descriptor is not None and getattr(descriptor, "name", None):
            name = descriptor.name
        if name:
            mapping[name] = func
    return mapping


@lru_cache(maxsize=128)
def get_tool_input_schema(tool_name: str) -> dict[str, Any]:
    """Return JSON Schema for tool parameters via AgentScope FunctionTool."""
    func = _builtin_tool_func_map().get(tool_name)
    if func is None:
        return {}
    try:
        from agentscope.tool import FunctionTool

        return dict(FunctionTool(func).input_schema or {})
    except Exception as exc:
        logger.warning(
            "Failed to build input_schema for tool %s: %s",
            tool_name,
            exc,
        )
        return {}


@lru_cache(maxsize=128)
def get_tool_runtime_description(tool_name: str) -> str:
    """Return LLM-facing docstring description for a built-in tool."""
    func = _builtin_tool_func_map().get(tool_name)
    if func is None:
        return ""
    try:
        from agentscope.tool import FunctionTool

        return str(FunctionTool(func).description or "").strip()
    except Exception as exc:
        logger.warning(
            "Failed to build runtime description for tool %s: %s",
            tool_name,
            exc,
        )
        return ""


def resolve_tool_presentation(
    tool_name: str,
    *,
    lang: str | None = "en",
    fallback_description: str = "",
) -> dict[str, Any]:
    """Resolve summary, detail markdown, and input_schema for API responses."""
    curated = load_tool_doc(tool_name, lang)
    runtime_desc = get_tool_runtime_description(tool_name)
    summary = (
        (curated or {}).get("summary")
        or fallback_description
        or runtime_desc.split("\n", 1)[0].strip()
        or tool_name
    )
    detail = (curated or {}).get("body") or runtime_desc or summary
    return {
        "summary": summary,
        "detail": detail,
        "input_schema": get_tool_input_schema(tool_name),
    }
