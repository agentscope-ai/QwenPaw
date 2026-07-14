# -*- coding: utf-8 -*-
"""Strip thinking blocks and null tokens from LLM output.

Some LLM providers (Qwen, DeepSeek, etc.) emit ```` blocks or
leading ``null`` / ``None`` / ``undefined`` tokens that leak through
to the user. This module cleans them out before sending.

Two public helpers:

- :func:`_strip_thinking` — removes ```` blocks, lone
  ``<think>`` / ``</think>`` lines, and ``Thinking:`` /
  ``Reasoning:`` label-only lines.
- :func:`_strip_null_tokens` — drops lines that are only a null-ish
  placeholder and leading ``null\\n\\n`` leaks some providers emit.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Full  block (multiline).
_THINK_BLOCK_RE = re.compile(
    r"\s*<think(?:ing)?\b[^>]*>.*?</think(?:ing)?\s*>\s*",
    re.DOTALL | re.IGNORECASE,
)

# Lone <think ...> or </think> line.
_THINK_LINE_RE = re.compile(
    r"^\s*(?:<think(?:ing)?\b[^>]*>|<\s*/\s*think(?:ing)?\s*>)\s*$",
    re.IGNORECASE,
)

# "Thinking:" / "Reasoning:" label-only line (in either ASCII or 「：」).
_THINKING_LABEL_RE = re.compile(
    r"^\s*(?:【\s*)?(?:thinking\s*(?:process|content)?|reasoning)\s*[：:]?\s*$",
    re.IGNORECASE,
)

# Leading null-ish leak on the first line.
_LEADING_NULL_RE = re.compile(
    r"^\s*(null|none|undefined|nil|nan)\s*\n\n",
    re.IGNORECASE,
)

# Placeholder tokens treated as "no content".
_NULL_TOKENS = frozenset({
    "null", "none", "undefined", "nil", "nan", "n/a", "()",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _strip_thinking(text: str) -> str:
    """Remove ```` blocks and lone think / "Thinking:" lines."""
    if not text:
        return text

    # 1. Drop full  blocks (multiline).
    text = _THINK_BLOCK_RE.sub("\n", text)

    # 2. Drop lone <think> / </think> lines and "Thinking:" label lines.
    cleaned_lines = []
    for ln in text.splitlines():
        if _THINK_LINE_RE.match(ln):
            continue
        if _THINKING_LABEL_RE.match(ln.strip()):
            continue
        cleaned_lines.append(ln)
    text = "\n".join(cleaned_lines)

    # 3. Collapse 3+ blank lines into 1.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_null_tokens(text: str) -> str:
    """Drop lines that are just a null-ish placeholder.

    Also strips the ``null\\n\\n``-style leak some providers put at the
    very start of an otherwise empty response.
    """
    if not text:
        return text

    # Drop placeholder-only lines.
    keep = [
        ln for ln in text.splitlines()
        if ln.strip().lower() not in _NULL_TOKENS
    ]
    text = "\n".join(keep).strip()

    # Strip leading "null\n\n" leak.
    text = _LEADING_NULL_RE.sub("", text)

    return text.strip()
