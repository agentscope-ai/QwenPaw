# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter as fm
from fastapi import HTTPException

from .storage import validate_knowledge_id


DEFAULT_SOUL_CONTENT = """---
summary: \"SOUL.md workspace template\"
knowledge_base: []
---

_This file defines who you are. Evolve it carefully._
"""


def soul_file_path(workspace_dir: Path) -> Path:
    return workspace_dir / "SOUL.md"


def load_soul_post(workspace_dir: Path):
    path = soul_file_path(workspace_dir)
    if not path.exists():
        return fm.loads(DEFAULT_SOUL_CONTENT)
    try:
        return fm.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read SOUL.md: {exc}") from exc


def normalize_knowledge_reference(item: dict[str, Any]) -> dict[str, Any]:
    knowledge_id = validate_knowledge_id(item.get("id"))
    trigger = str(item.get("trigger") or "always").lower()
    if trigger not in {"always", "keyword"}:
        trigger = "always"
    return {
        "id": knowledge_id,
        "priority": max(1, int(item.get("priority") or 1)),
        "trigger": trigger,
        "retrieval_top_k": min(max(1, int(item.get("retrieval_top_k") or 3)), 20),
        "usage_rule": str(item.get("usage_rule") or "Use this knowledge base when it is relevant.").strip(),
        "keywords": [str(keyword).strip() for keyword in (item.get("keywords") or []) if str(keyword).strip()],
    }


def load_soul_knowledge_config(workspace_dir: Path) -> dict[str, Any]:
    post = load_soul_post(workspace_dir)
    items = [
        normalize_knowledge_reference(item)
        for item in (post.metadata.get("knowledge_base") or [])
        if isinstance(item, dict)
    ]
    return {
        "items": sorted(items, key=lambda item: (item["priority"], item["id"])),
        "soul_path": str(soul_file_path(workspace_dir)),
    }


def save_soul_knowledge_config(workspace_dir: Path, items: list[dict[str, Any]]) -> dict[str, Any]:
    post = load_soul_post(workspace_dir)
    normalized_items = [normalize_knowledge_reference(item) for item in items]
    post.metadata["knowledge_base"] = normalized_items
    path = soul_file_path(workspace_dir)
    path.write_text(fm.dumps(post), encoding="utf-8")
    return {
        "items": normalized_items,
        "soul_path": str(path),
    }