# -*- coding: utf-8 -*-
"""AgentScope tool-call boundary guards for the file-native Runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import re


class NonNativeToolMarkupError(ValueError):
    """Raised when a TextBlock contains provider control markup."""


_NON_NATIVE_TOOL_MARKUP = re.compile(
    r"<\s*/?\s*(?:tool_call\b|function(?:\s*=|\b)|parameter(?:\s*=|\b))",
    re.IGNORECASE,
)


def contains_non_native_tool_markup(text: str) -> bool:
    """Return whether *text* contains a textual tool-call envelope."""

    return bool(_NON_NATIVE_TOOL_MARKUP.search(text))


class NativeToolTextStream:
    """Publish safe prose while withholding split textual control tags.

    AgentScope 2.x represents provider actions as ``ToolCallBlock`` objects.
    A provider emitting XML-looking function syntax in a ``TextBlock`` must
    therefore fail the model turn, never become an executable action or
    user-visible prose.
    """

    def __init__(
        self,
        callback: Callable[[str], Awaitable[None]] | None,
    ) -> None:
        self._callback = callback
        self._pending = ""
        self._saw_stream_text = False

    async def feed(self, delta: str) -> None:
        if not delta:
            return
        self._saw_stream_text = True
        self._pending += delta
        match = _NON_NATIVE_TOOL_MARKUP.search(self._pending)
        if match is not None:
            safe_prefix = self._pending[: match.start()]
            self._pending = ""
            if safe_prefix and self._callback is not None:
                await self._callback(safe_prefix)
            raise NonNativeToolMarkupError(
                "TextBlock contained textual tool-call markup",
            )

        # A tool tag may be split at any character, so retain one unfinished
        # angle-bracket suffix until its next chunk can classify it.
        last_open = self._pending.rfind("<")
        held = ""
        if last_open >= 0:
            suffix = self._pending[last_open:]
            if ">" not in suffix and len(suffix) <= 64:
                held = suffix
        safe = (
            self._pending[: len(self._pending) - len(held)]
            if held
            else self._pending
        )
        self._pending = held
        if safe and self._callback is not None:
            await self._callback(safe)

    async def finalize(self, final_text: str) -> None:
        """Validate final aggregate text and finish the callback contract."""

        if contains_non_native_tool_markup(final_text):
            self._pending = ""
            raise NonNativeToolMarkupError(
                "TextBlock contained textual tool-call markup",
            )
        if self._saw_stream_text:
            pending = self._pending
            self._pending = ""
            if pending and self._callback is not None:
                await self._callback(pending)
        elif final_text and self._callback is not None:
            await self._callback(final_text)


__all__ = [
    "NativeToolTextStream",
    "NonNativeToolMarkupError",
    "contains_non_native_tool_markup",
]
