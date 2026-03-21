# -*- coding: utf-8 -*-
"""YAML frontmatter parsing for workflow Markdown files."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import yaml

logger = logging.getLogger(__name__)


def _normalize_tags_value(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif item is not None and not isinstance(item, (dict, list)):
                s = str(item).strip()
                if s:
                    out.append(s)
        return out
    return []


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s or None
    s = str(value).strip()
    return s or None


def split_frontmatter(text: str) -> Tuple[bool, Dict[str, Any], str, str]:
    """Split workflow Markdown into (had_fence, meta_dict, body, raw).

    Optional leading ``---`` / ``---`` YAML block (Jekyll-style).
    If no opening fence, returns (False, {}, text, raw).
    If opening fence but invalid YAML or no closing fence, returns
    (False, {}, text, raw) and the caller treats the whole file as body.
    """
    raw = text
    if not text.startswith("---"):
        return False, {}, text, raw

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False, {}, text, raw

    yaml_lines: List[str] = []
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            body = "\n".join(lines[i + 1 :])
            block = "\n".join(yaml_lines)
            try:
                loaded = yaml.safe_load(block)
            except yaml.YAMLError as e:
                logger.debug("Workflow frontmatter YAML error: %s", e)
                return False, {}, text, raw
            if loaded is None:
                meta: Dict[str, Any] = {}
            elif isinstance(loaded, dict):
                meta = loaded
            else:
                return False, {}, text, raw
            return True, meta, body, raw
        yaml_lines.append(line)
        i += 1

    return False, {}, text, raw


def extract_meta_fields(
    meta: Dict[str, Any],
) -> tuple[
    str | None,
    str | None,
    List[str],
    str | None,
    str | None,
    str | None,
]:
    """Return name, description, tags, category, status, version."""
    name = _as_optional_str(meta.get("name"))
    description = _as_optional_str(meta.get("description"))
    tags = _normalize_tags_value(meta.get("tags"))
    category = _as_optional_str(meta.get("category"))
    status = _as_optional_str(meta.get("status"))
    version = _as_optional_str(meta.get("version"))
    return name, description, tags, category, status, version
