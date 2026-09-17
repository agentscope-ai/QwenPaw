# -*- coding: utf-8 -*-
"""Compatibility fixes for Textual releases supported by the TUI."""

from __future__ import annotations

from typing import Any

from textual.screen import Screen


_ORIGINAL_GET_WIDGET_AND_OFFSET_AT = Screen.get_widget_and_offset_at
_COMPAT_APPLIED = False


def _safe_get_widget_and_offset_at(
    self: Screen,
    x: int,
    y: int,
) -> tuple[Any, Any]:
    """Ignore widgets detached after the compositor's latest reflow."""
    widget, offset = _ORIGINAL_GET_WIDGET_AND_OFFSET_AT(self, x, y)
    if (
        widget is not None
        and not isinstance(widget, Screen)
        and widget.parent is None
    ):
        return None, None
    return widget, offset


def apply_textual_compat() -> None:
    """Apply process-wide Textual compatibility fixes exactly once."""
    global _COMPAT_APPLIED  # pylint: disable=global-statement
    if _COMPAT_APPLIED:
        return

    # Textualize/textual#6643: Markdown.update() may detach a widget before
    # the compositor reflows. Textual 8.2.8 can return that stale widget from
    # hit testing, then crash while beginning a selection. Remove this shim
    # after QwenPaw requires the first Textual release containing the fix.
    Screen.get_widget_and_offset_at = _safe_get_widget_and_offset_at
    _COMPAT_APPLIED = True
