# -*- coding: utf-8 -*-
"""Per-tool before/after hooks and timeout metadata."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ._context import ToolCallContext

logger = logging.getLogger(__name__)

BeforeHook = Callable[
    [dict[str, Any], ToolCallContext],
    Awaitable[dict[str, Any] | None],
]
AfterHook = Callable[[Any, ToolCallContext], Awaitable[Any | None]]


@dataclass
class _HookPair:
    """Per-tool runtime metadata.

    ``max_internal_timeout_secs`` marks an absolute hard cap the deadline
    API must honor (for example, browser Playwright or a coordinator-owned
    24-hour ceiling). When set, ``no_deadline`` and extensions past
    ``started_at + cap`` are refused.
    """

    before: BeforeHook | None = None
    after: AfterHook | None = None
    default_timeout_secs: float | None = None
    max_internal_timeout_secs: float | None = None


class ToolHookRegistry:
    """name -> _HookPair. O(1) lookup."""

    def __init__(self) -> None:
        self._hooks: dict[str, _HookPair] = {}

    def register(
        self,
        tool_name: str,
        *,
        before: BeforeHook | None = None,
        after: AfterHook | None = None,
        default_timeout_secs: float | None = None,
        max_internal_timeout_secs: float | None = None,
    ) -> None:
        """Register hook(s) and/or runtime metadata.

        Calling multiple times for the same tool merges fields — only
        explicitly-passed kwargs overwrite.
        """
        existing = self._hooks.get(tool_name) or _HookPair()
        self._hooks[tool_name] = _HookPair(
            before=before if before is not None else existing.before,
            after=after if after is not None else existing.after,
            default_timeout_secs=(
                default_timeout_secs
                if default_timeout_secs is not None
                else existing.default_timeout_secs
            ),
            max_internal_timeout_secs=(
                max_internal_timeout_secs
                if max_internal_timeout_secs is not None
                else existing.max_internal_timeout_secs
            ),
        )

    def unregister(self, tool_name: str) -> None:
        self._hooks.pop(tool_name, None)

    def get(self, tool_name: str) -> _HookPair:
        return self._hooks.get(tool_name) or _HookPair()
