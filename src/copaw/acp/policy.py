# -*- coding: utf-8 -*-
"""Shared ACP approval policy helpers."""
from __future__ import annotations

import re
from typing import Any

READ_ONLY_TOOL_KINDS = frozenset(
    {
        "read",
        "search",
        "find",
        "list",
        "glob",
        "grep",
    },
)

_DANGEROUS_PROMPT_KEYWORDS_EN = (
    "create",
    "write",
    "edit",
    "modify",
    "append",
    "delete",
    "remove",
    "rename",
    "move",
    "rewrite",
    "replace",
    "exec",
    "run",
    "bash",
    "shell",
)
_DANGEROUS_PROMPT_KEYWORDS_ZH = (
    "创建",
    "写入",
    "编辑",
    "修改",
    "追加",
    "删除",
    "移除",
    "重命名",
    "移动",
    "覆盖",
    "替换",
    "执行",
    "运行",
    "命令",
    "脚本",
)
_DANGEROUS_PROMPT_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(re.escape(keyword) for keyword in _DANGEROUS_PROMPT_KEYWORDS_EN)
    + r")\b",
    re.IGNORECASE,
)
_SAFE_REFERENCE_PATTERNS_ZH = (
    re.compile(
        r"(刚才|刚刚|之前|先前|刚刚).*(创建|修改|删除).*(内容|是什么|在哪|读取|看看|列出)",
    ),
    re.compile(r"刚才创建的文件内容是什么"),
)
_SAFE_REFERENCE_PATTERNS_EN = (
    re.compile(
        r"\b(?:what|which|show|read|list)\b.*\b(?:just|previously|earlier)\b"
        r".*\b(?:create|created|modify|modified|delete|deleted)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat\b.*\bcontent\b.*\b(?:created|modified|deleted)\b",
        re.IGNORECASE,
    ),
)


def is_read_only_tool(
    tool_name: str | None,
    tool_kind: str | None,
) -> bool:
    """Return whether a tool belongs to the ACP read-only allowlist."""
    candidates = {
        str(tool_name or "").strip().lower(),
        str(tool_kind or "").strip().lower(),
    }
    candidates.discard("")
    return any(candidate in READ_ONLY_TOOL_KINDS for candidate in candidates)


def prompt_blocks_to_text(prompt_blocks: list[dict[str, Any]]) -> str:
    """Flatten prompt blocks into a single text string."""
    parts: list[str] = []
    for block in prompt_blocks:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "").lower() != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts).strip()


def is_obviously_dangerous_prompt(prompt_text: str) -> bool:
    """Return whether a prompt clearly asks for write/exec behavior."""
    text = (prompt_text or "").strip()
    if not text:
        return True

    if any(pattern.search(text) for pattern in _SAFE_REFERENCE_PATTERNS_ZH):
        return False
    if any(pattern.search(text) for pattern in _SAFE_REFERENCE_PATTERNS_EN):
        return False

    if _DANGEROUS_PROMPT_PATTERN.search(text):
        return True

    return any(keyword in text for keyword in _DANGEROUS_PROMPT_KEYWORDS_ZH)


def build_unverified_harness_message(harness: str) -> str:
    """User-facing message when an unverified harness is blocked."""
    return f"ACP harness '{harness}' 未验证支持可审计审批；在已开启审批模式时，" "仅允许只读操作。"


def build_unverified_tool_violation_message(
    harness: str,
    tool_name: str | None,
    tool_kind: str | None,
) -> str:
    """User-facing message when runtime detects an unsafe tool call."""
    label = str(tool_name or tool_kind or "unknown").strip() or "unknown"
    return (
        f"ACP harness '{harness}' 在未验证审批能力的情况下触发了危险工具 " f"'{label}'，本次执行已被取消。"
    )
