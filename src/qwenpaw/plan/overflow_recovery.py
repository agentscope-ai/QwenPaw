# -*- coding: utf-8 -*-
"""Emergency tool-result compaction helper for plan-mode context overflow.

Extracted from ``react_agent`` so the agent file only needs a tiny call
site in its existing ``_reasoning`` / ``_summarizing`` overflow branches.
The helper short-circuits to ``False`` when no real compaction happened
(no memory manager configured or ReMe disabled), letting callers re-raise
the original overflow error instead of looping on it.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Aggressive byte cap for emergency tool-result truncation; mirrors the
# value previously hard-coded inside ``QwenPawAgent``.
OVERFLOW_EMERGENCY_MAX_BYTES = 300


def _total_tool_result_text_bytes(memory_content) -> int:
    """Sum textual sizes of ``ToolResultBlock`` outputs in *memory_content*.

    Used to detect whether emergency compaction made progress before
    retrying the failing reasoning / summarizing call.
    """
    total = 0
    for msg, _marks in memory_content:
        if not isinstance(msg.content, list):
            continue
        for block in msg.content:
            is_dict_block = isinstance(block, dict)
            is_tool_result = False
            if is_dict_block:
                is_tool_result = block.get("type") == "tool_result"
            if not is_tool_result:
                continue
            output = block.get("output")
            if isinstance(output, str):
                total += len(output.encode("utf-8", "ignore"))
            elif isinstance(output, list):
                for item in output:
                    if not isinstance(item, dict):
                        continue
                    text = item.get("text") or ""
                    if isinstance(text, str):
                        total += len(text.encode("utf-8", "ignore"))
    return total


async def emergency_compact_made_progress(
    *,
    memory_manager: Any,
    memory_content: list,
    label: str = "context overflow recovery",
    max_bytes: int = OVERFLOW_EMERGENCY_MAX_BYTES,
) -> bool:
    """Run aggressive ReMe tool-result compaction; True iff bytes shrank.

    Returns ``False`` (without raising) when:

    * ``memory_manager`` is ``None`` (memory manager disabled), or
    * the underlying ``compact_tool_result`` had no effect (e.g. ReMe
      backend not configured, or nothing left to truncate).

    Callers should re-raise the original overflow exception in that case
    instead of looping on the same context.
    """
    if memory_manager is None:
        return False
    before = _total_tool_result_text_bytes(memory_content)
    await memory_manager.compact_tool_result(
        messages=[p[0] for p in memory_content],
        recent_n=0,
        old_max_bytes=max_bytes,
        recent_max_bytes=max_bytes,
    )
    after = _total_tool_result_text_bytes(memory_content)
    if after >= before:
        logger.warning(
            "%s: no progress (before=%d, after=%d); not retrying.",
            label,
            before,
            after,
        )
        return False
    logger.warning(
        "%s: compacted tool-result outputs %d -> %d bytes, retrying.",
        label,
        before,
        after,
    )
    return True
