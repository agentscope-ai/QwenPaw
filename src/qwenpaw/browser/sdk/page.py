# -*- coding: utf-8 -*-
"""Playwright-shaped per-page operations for the Unified Browser SDK."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from typing import Any

from ..errors import BrowserError, ErrorCause, ErrorCategory
from .contracts import (
    CurrentSurface,
    FrameLocatorView,
    LocatorView,
    Observation,
)

_LOAD_STATES = frozenset({"load", "domcontentloaded", "networkidle"})


class _Input:
    def __init__(self, page: "Page", kind: str) -> None:
        self._page = page
        self._kind = kind

    async def click(self, x: float, y: float) -> Any:
        return await self._page._engine._input(
            self._page.id,
            self._kind,
            "click",
            x=x,
            y=y,
        )

    async def press(self, key: str) -> Any:
        return await self._page._engine._input(
            self._page.id,
            self._kind,
            "press",
            key=key,
        )

    async def wheel(
        self,
        delta_x: float = 0.0,
        delta_y: float = 0.0,
    ) -> Any:
        """Scroll the viewport by a wheel delta; verify with snapshot()."""
        return await self._page._engine._input(
            self._page.id,
            self._kind,
            "wheel",
            delta_x=delta_x,
            delta_y=delta_y,
        )


class Page:
    """Navigation, locating, perception, and coordinate/keyboard operations."""

    def __init__(self, engine: Any, page_id: str) -> None:
        self._engine = engine
        self.id = page_id
        self._locator = engine.locator_for(page_id)
        self._observation = engine.observation_for(page_id)

    @property
    def mouse(self) -> "_Input":
        """Viewport-coordinate input surface.

        click(x, y) -> a result dict; verify the effect with snapshot().
        """
        return _Input(self, "mouse")

    @property
    def keyboard(self) -> "_Input":
        """Keyboard input surface.

        press(key) -> a result dict; verify the effect with snapshot().
        """
        return _Input(self, "keyboard")

    async def goto(self, url: str) -> dict[str, Any]:
        """Navigate this page to ``url`` and return raw navigation facts."""
        return await self._engine._navigate(self.id, "navigate", url)

    async def go_back(self) -> dict[str, Any]:
        """Navigate back to the previous page in history."""
        return await self._engine._navigate(self.id, "go_back")

    async def go_forward(self) -> dict[str, Any]:
        """Navigate forward to the next page in history."""
        return await self._engine._navigate(self.id, "go_forward")

    async def reload(self) -> dict[str, Any]:
        """Reload the current page."""
        return await self._engine._navigate(self.id, "reload")

    async def keep(self) -> None:
        """Retain this page across response cycles for the current chat."""
        await self._engine._keep_page(self.id)

    async def wait_for_timeout(self, timeout: float) -> None:
        """Sleep unconditionally for *timeout* milliseconds (capped at 30 000).

        Prefer :py:meth:`locator.wait_for(state, timeout)
        <LocatorView.wait_for>` when waiting for a specific DOM condition
        — it returns as soon as the condition is met and is both faster
        and more reliable than an unconditional sleep.
        """
        capped_ms = min(float(timeout), 30_000.0)
        await asyncio.sleep(capped_ms / 1000.0)

    async def wait_for_load_state(
        self,
        state: str = "load",
        *,
        timeout: float | None = None,
    ) -> None:
        """Wait until the page reaches the requested load state.

        ``networkidle`` semantics depend on the backend: the Playwright
        backend waits for true network quiescence, while CDP-based
        backends (cdp, chrome) degrade to ``document.readyState ==
        "complete"`` plus a fixed 500 ms quiet delay and do NOT track
        in-flight requests — content loaded by late XHR may still be
        missing when this returns.
        """
        if state not in _LOAD_STATES:
            raise BrowserError(
                category=ErrorCategory.FATAL,
                cause=ErrorCause.API_MISUSE,
                suggested_action=(
                    "Use one of: load, domcontentloaded, networkidle."
                ),
                reason=f"unknown load state {state!r}",
            )
        await self._engine._wait_for_load_state(self.id, state, timeout)

    async def screenshot(self) -> dict[str, str]:
        """Capture this page to a PNG file in the active workspace."""
        return await self._engine._screenshot(self.id)

    def get_by_role(
        self,
        role: str,
        *,
        name: str | None = None,
    ) -> LocatorView:
        """Locate elements by accessible role and optional name."""
        return self._locator.get_by_role(role, name=name)

    def get_by_text(self, text: str) -> LocatorView:
        """Locate elements by their visible text."""
        return self._locator.get_by_text(text)

    def get_by_label(self, text: str) -> LocatorView:
        """Locate a form control by its associated label text."""
        return self._locator.get_by_label(text)

    def get_by_placeholder(self, text: str) -> LocatorView:
        """Locate an input by its placeholder text."""
        return self._locator.get_by_placeholder(text)

    def locator(self, selector: str) -> LocatorView:
        """Locate elements by a CSS selector when no semantic locator fits."""
        return self._locator.locator(selector)

    def frame_locator(self, selector: str) -> FrameLocatorView:
        """Scope subsequent locators to the iframe matching ``selector``."""
        return self._locator._frame_locator(selector)

    async def snapshot(self, query: str | None = None) -> Observation:
        """Perceive the page and return readable content in ``.text``.

        Pass ``query`` to also report ``.match_count``.
        """
        return await self._observation.snapshot(query=query)

    async def current_surface(self) -> CurrentSurface:
        """Return this page's current URL, title, and load facts."""
        return await self._observation.current_surface()
