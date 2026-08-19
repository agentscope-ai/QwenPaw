# -*- coding: utf-8 -*-
"""Shared business knowledge-base store, mount, and dream helpers."""

from .mount import (
    detect_dangling_mount,
    ensure_knowledge_mount,
    unmount_knowledge,
)
from .store import (
    KnowledgeBaseMeta,
    ensure_kb,
    kb_root,
    list_knowledge_bases,
    resolve_kb_id,
)

__all__ = [
    "KnowledgeBaseMeta",
    "detect_dangling_mount",
    "ensure_kb",
    "ensure_knowledge_mount",
    "kb_root",
    "list_knowledge_bases",
    "resolve_kb_id",
    "unmount_knowledge",
]
