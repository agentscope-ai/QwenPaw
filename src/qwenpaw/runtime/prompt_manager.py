# -*- coding: utf-8 -*-
"""Per-workspace system-prompt assembly.

Each contributor declares one fragment of the system prompt;
``PromptManager`` orders them by priority and joins non-empty results
with ``PROMPT_SEPARATOR``.

``PROMPT_SEPARATOR`` is intentionally a module-level constant so
parity tests can pin the exact separator (any change is a contract break).
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .hooks import HookContext

logger = logging.getLogger(__name__)

PROMPT_SEPARATOR = "\n\n"


class PromptContributor:
    """Single-responsibility producer of one system-prompt fragment.

    Subclasses set ``name`` (unique within a manager, used for replacement /
    disable) and ``priority`` (ascending — lower runs first / appears earlier
    in the final prompt). ``contribute`` may return ``None`` or an empty
    string to opt out for the current request.
    """

    name: str
    priority: int = 100

    async def contribute(
        self,
        ctx: "HookContext",
    ) -> str | None:  # noqa: D401, ARG002
        raise NotImplementedError


class SyncPromptContributor(PromptContributor):
    """Convenience base for contributors that have no async work to do."""

    async def contribute(self, ctx: "HookContext") -> str | None:
        return self.contribute_sync(ctx)

    def contribute_sync(
        self,
        ctx: "HookContext",
    ) -> str | None:  # noqa: ARG002
        raise NotImplementedError


class PromptManager:
    """Hold contributors and assemble the final system prompt per request."""

    def __init__(self) -> None:
        self._contributors: list[PromptContributor] = []

    # ---------------------------------------------------------------- register
    def register(self, contributor: PromptContributor) -> None:
        if not isinstance(contributor, PromptContributor):
            raise TypeError(
                "register() requires a PromptContributor, "
                f"got {type(contributor).__name__}",
            )
        if not getattr(contributor, "name", None):
            raise ValueError(
                "PromptContributor.name must be a non-empty string",
            )
        if any(c.name == contributor.name for c in self._contributors):
            raise ValueError(
                f"prompt contributor {contributor.name!r} already registered",
            )
        self._contributors.append(contributor)
        self._contributors.sort(key=lambda c: c.priority)

    def names(self) -> list[str]:
        return [c.name for c in self._contributors]

    def __len__(self) -> int:
        return len(self._contributors)

    # ------------------------------------------------------------------ build
    async def build(self, ctx: "HookContext") -> str:
        """Run every contributor in priority order, join non-empty pieces.

        A contributor raising is logged and skipped — one broken contributor
        must not take down the prompt assembly for the whole request.
        ``await`` is used unconditionally on the return value so synchronous
        implementations (whether plain ``def`` or returning a non-awaitable
        from ``async def``) both work.
        """
        parts: list[str] = []
        for c in self._contributors:
            try:
                raw = c.contribute(ctx)
                fragment = await raw if inspect.isawaitable(raw) else raw
            except Exception:
                logger.exception(
                    "prompt contributor %s failed; skipping",
                    c.name,
                )
                continue
            if fragment:
                parts.append(fragment.strip())
        return PROMPT_SEPARATOR.join(parts)

    def build_sync(self, ctx: Any) -> str:
        """Synchronous variant of :meth:`build`.

        All built-in contributors use :class:`SyncPromptContributor`, so
        their ``contribute()`` returns a plain string (not a coroutine).
        This method calls ``contribute_sync`` directly when available,
        avoiding the need for an event loop.
        """
        parts: list[str] = []
        for c in self._contributors:
            try:
                if isinstance(c, SyncPromptContributor):
                    fragment = c.contribute_sync(ctx)
                else:
                    raw = c.contribute(ctx)
                    fragment = raw if not inspect.isawaitable(raw) else None
            except Exception:
                logger.exception(
                    "prompt contributor %s failed; skipping",
                    c.name,
                )
                continue
            if fragment:
                parts.append(fragment.strip())
        return PROMPT_SEPARATOR.join(parts)


__all__ = [
    "PROMPT_SEPARATOR",
    "PromptContributor",
    "PromptManager",
    "SyncPromptContributor",
]
