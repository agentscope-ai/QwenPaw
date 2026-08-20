# -*- coding: utf-8 -*-
"""Stateful input policy for managed terminal sessions."""

from __future__ import annotations

_MAX_PENDING_INPUT_CHARS = 64 * 1024

CTRL_C_INPUT_ALIASES = frozenset(
    {
        "\x03",
        r"\u0003",
        r"\x03",
        "&#3;",
        "&#x3;",
        "&#x03;",
    },
)


def normalize_terminal_input(chars: str, *, interrupt: bool) -> str:
    """Turn whole-value Ctrl-C representations into one ETX character."""
    value = chars or ""
    if interrupt or value.strip().lower() in CTRL_C_INPUT_ALIASES:
        return "\x03"
    return value


class TerminalInputBuffer:
    """Hold input fragments until a complete terminal line is available."""

    def __init__(self) -> None:
        self._pending = ""

    def preview(self, fragment: str) -> str:
        """Return pending and proposed input without mutating state."""
        combined = self._pending + fragment
        if len(combined) > _MAX_PENDING_INPUT_CHARS:
            raise ValueError(
                "pending terminal input exceeds the 65536 character limit",
            )
        return combined

    def commit(self, fragment: str) -> str:
        """Append input and return only complete lines ready for delivery."""
        combined = self.preview(fragment)
        boundary = max(combined.rfind("\n"), combined.rfind("\r"))
        if boundary < 0:
            self._pending = combined
            return ""
        ready = combined[: boundary + 1]
        self._pending = combined[boundary + 1 :]
        return ready

    def clear(self) -> None:
        """Discard fragments that have not reached the terminal."""
        self._pending = ""
