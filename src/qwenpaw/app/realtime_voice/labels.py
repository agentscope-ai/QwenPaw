"""Locale-specific labels for realtime voice presentation.

Kept out of the coordination logic (``task_bridge``/``service``) so that user
facing wording lives in one place instead of being embedded in control flow.
"""

from __future__ import annotations

VOICE_CHAT_PLACEHOLDER_NAME = "Voice Chat"

_TASK_ORDINALS = (
    "一",
    "二",
    "三",
    "四",
    "五",
    "六",
    "七",
    "八",
    "九",
    "十",
    "十一",
    "十二",
    "十三",
    "十四",
    "十五",
    "十六",
    "十七",
    "十八",
    "十九",
    "二十",
)


def task_ref_label(ordinal: int) -> str:
    """Return the spoken task reference (e.g. ``请求一``) for one ordinal."""
    suffix = (
        _TASK_ORDINALS[ordinal - 1] if ordinal <= len(_TASK_ORDINALS) else str(ordinal)
    )
    return f"请求{suffix}"


__all__ = ["VOICE_CHAT_PLACEHOLDER_NAME", "task_ref_label"]
