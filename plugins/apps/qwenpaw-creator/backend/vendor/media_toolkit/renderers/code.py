# -*- coding: utf-8 -*-
# flake8: noqa: E501
# Vendored from Qwen-MM-Plugins (Apache-2.0), release commit 077aea6.
# Upstream path: src/capabilities/core/qwen_media_toolkit_core/renderers/code.py
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Render source code files as markdown-fenced text blocks.

Creator modifications: the leading block is a meta block, the line cap is
overridable via the ``max_lines`` option, and the complete file content is
emitted as a ``full_text`` block for deterministic indexing regardless of
the display cap.
"""

from __future__ import annotations

import os
from typing import Any

_EXT_TO_LANG = {
    ".css": "css",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".py": "python",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".sql": "sql",
    ".md": "markdown",
    ".toml": "toml",
    ".ini": "ini",
    ".lua": "lua",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".R": "r",
    ".dart": "dart",
    ".tex": "latex",
}

MAX_LINES = 500


def render(path: str, **opts: Any) -> list[dict[str, Any]]:
    max_lines = int(opts.get("max_lines") or MAX_LINES)
    ext = os.path.splitext(path)[1].lower()
    lang = _EXT_TO_LANG.get(ext, "")

    from vendor.media_toolkit.renderers import meta_block

    with open(path, "r", errors="replace", encoding="utf-8") as f:
        lines = f.readlines()

    total_lines = len(lines)
    full = "".join(lines)
    truncated = False
    if total_lines > max_lines:
        lines = lines[:max_lines]
        truncated = True

    code = "".join(lines)

    lang_label = lang.capitalize() if lang else ext.lstrip(".")
    summary = (
        f"File: {os.path.basename(path)} | {lang_label} | "
        f"{total_lines} lines"
    )

    parts = [summary, f"```{lang}\n{code}\n```"]
    if truncated:
        parts.append(f"... ({total_lines - max_lines} more lines truncated)")

    blocks = [
        meta_block(ext.lstrip(".") or "text", 1, []),
        {"type": "text", "text": "\n\n".join(parts)},
    ]
    if truncated:
        # The display block above is line-capped; indexing gets the whole
        # file (the reader applies its own character bound).
        blocks.append({"type": "full_text", "text": f"{summary}\n{full}"})
    return blocks
