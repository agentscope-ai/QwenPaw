# -*- coding: utf-8 -*-
"""Browser variant control-link port (dependency-inversion anchor)."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol, runtime_checkable

EventSink = Callable[[Mapping[str, Any]], None]


@runtime_checkable
class ControlLink(Protocol):
    """Raw command/fact channel to one browser variant."""

    @property
    def variant(self) -> str:
        pass

    def is_available(self) -> bool:
        pass

    async def request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        pass

    def on_event(self, sink: EventSink) -> Callable[[], None]:
        pass
