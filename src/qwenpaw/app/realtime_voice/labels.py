"""User-facing labels for realtime voice, kept out of control flow."""

from __future__ import annotations

VOICE_CHAT_PLACEHOLDER_NAME = "Voice Chat"

_TASK_ORDINALS = (
    "一 二 三 四 五 六 七 八 九 十 " "十一 十二 十三 十四 十五 十六 十七 十八 十九 二十"
).split()


def task_ref_label(ordinal: int) -> str:
    """Return the spoken task reference (e.g. ``请求一``) for one ordinal."""
    if ordinal <= len(_TASK_ORDINALS):
        return f"请求{_TASK_ORDINALS[ordinal - 1]}"
    return f"请求{ordinal}"


__all__ = ["VOICE_CHAT_PLACEHOLDER_NAME", "task_ref_label"]
