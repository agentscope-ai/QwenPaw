# -*- coding: utf-8 -*-
"""Lazy locator projection domain."""

from __future__ import annotations

from typing import Any

from ..sdk.contracts import (
    ActionLevel,
    ActionResult,
    FrameLocatorView,
    LocatorStep,
    LocatorView,
    Owner,
)


def _spec_to_wire(spec: tuple[LocatorStep, ...]) -> list[dict[str, Any]]:
    return [
        {
            "method": step.method,
            "args": list(step.args),
            "kwargs": list(step.kwargs),
        }
        for step in spec
    ]


class LocatorDomain:
    """Lazy locator operations bound to one owner and concrete page."""

    def __init__(self, link: Any, owner: Owner, page_id: str) -> None:
        self.link = link
        self._owner = owner
        self._page_id = page_id

    def _params(self, **rest: Any) -> dict[str, Any]:
        """Build every provider request with this page's full identity."""
        return {
            "workspace_id": self._owner.workspace_id,
            "session_id": self._owner.session_id,
            "page_id": self._page_id,
            **rest,
        }

    def _root(self, method: str, *args: Any, **kwargs: Any) -> LocatorView:
        return LocatorView(
            self,
            (LocatorStep(method, args, tuple(sorted(kwargs.items()))),),
        )

    def get_by_role(
        self,
        role: str,
        *,
        name: str | None = None,
    ) -> LocatorView:
        return self._root("get_by_role", role, name=name)

    def get_by_text(self, text: str) -> LocatorView:
        return self._root("get_by_text", text)

    def get_by_label(self, text: str) -> LocatorView:
        return self._root("get_by_label", text)

    def get_by_placeholder(self, text: str) -> LocatorView:
        return self._root("get_by_placeholder", text)

    def locator(self, selector: str) -> LocatorView:
        return self._root("locator", selector)

    def _frame_locator(self, selector: str) -> FrameLocatorView:
        return FrameLocatorView(self, selector)

    async def _count(self, spec: tuple[LocatorStep, ...]) -> int:
        raw = await self.link.request(
            "locator_count",
            self._params(spec=_spec_to_wire(spec)),
        )
        return int(raw["count"])

    async def _read(
        self,
        spec: tuple[LocatorStep, ...],
        prop: str,
        *args: Any,
    ) -> Any:
        raw = await self.link.request(
            "locator_read",
            self._params(
                spec=_spec_to_wire(spec),
                property=prop,
                args=list(args),
            ),
        )
        return raw.get("value")

    async def _locator_wait_for(
        self,
        spec: tuple[LocatorStep, ...],
        state: str,
        timeout: float,
    ) -> None:
        await self.link.request(
            "locator_wait_for",
            self._params(
                spec=_spec_to_wire(spec),
                state=state,
                timeout=timeout,
            ),
        )

    async def _locator_screenshot(
        self,
        spec: tuple[LocatorStep, ...],
    ) -> dict[str, str]:
        raw = await self.link.request(
            "locator_screenshot",
            self._params(spec=_spec_to_wire(spec)),
        )
        return {"path": str(raw["path"])}

    async def _locator_bounding_box(
        self,
        spec: tuple[LocatorStep, ...],
    ) -> dict[str, float] | None:
        raw = await self.link.request(
            "locator_bounding_box",
            self._params(spec=_spec_to_wire(spec)),
        )
        value = raw.get("value")
        if value is None:
            return None
        return {
            key: float(value[key]) for key in ("x", "y", "width", "height")
        }

    async def _locator_action(
        self,
        spec: tuple[LocatorStep, ...],
        action: str,
        **params: Any,
    ) -> ActionResult:
        raw = await self.link.request(
            "locator_action",
            self._params(
                spec=_spec_to_wire(spec),
                action=action,
                **params,
            ),
        )
        return ActionResult(
            level=ActionLevel.RECEIVED,
            evidence=str(raw.get("evidence", "")),
        )
