# -*- coding: utf-8 -*-
"""Plugin-owned normalization for native pointer transitions."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .models import RecordingEvent


# CoreGraphics reports pointer coordinates in display points. Treat tiny
# movement inside this radius as click jitter even when macOS emitted one or
# more dragged events. The maximum excursion is used so a real drag that ends
# near its origin is still preserved as a drag.
_CLICK_SLOP_POINTS = 3.0


@dataclass
class _PointerAction:
    down: RecordingEvent
    samples: list[RecordingEvent] = field(default_factory=list)

    @property
    def last(self) -> RecordingEvent:
        return self.samples[-1] if self.samples else self.down


class RecordingActionNormalizer:
    """Turn down/drag/up evidence into durable click or drag events.

    Events that occur while a pointer action is open are held so persistence
    remains ordered. A missing boundary is represented as
    ``pointer_incomplete`` rather than guessed into an executable action.
    """

    def __init__(self) -> None:
        self._active: dict[str, _PointerAction] = {}
        self._held: list[RecordingEvent] = []

    def push(self, event: RecordingEvent) -> list[RecordingEvent]:
        """Consume one ordered event and return newly stable events."""
        if event.type == "pointer_down":
            return self._pointer_down(event)
        if event.type == "drag" and event.input.get("phase") == "update":
            return self._pointer_drag(event)
        if event.type == "pointer_up":
            return self._pointer_up(event)
        if self._active:
            self._held.append(event)
            return []
        return [event]

    def flush(
        self,
        *,
        status: str = "missing_pointer_up",
    ) -> list[RecordingEvent]:
        """Close incomplete actions without inventing click/drag semantics."""
        for action in self._active.values():
            self._held.append(self._incomplete(action, status=status))
        self._active.clear()
        return self._drain()

    def _pointer_down(self, event: RecordingEvent) -> list[RecordingEvent]:
        button = self._button(event)
        existing = self._active.pop(button, None)
        if existing is not None:
            self._held.append(
                self._incomplete(existing, status="superseded_pointer_down"),
            )
        self._active[button] = _PointerAction(down=event)
        return []

    def _pointer_drag(self, event: RecordingEvent) -> list[RecordingEvent]:
        action = self._active.get(self._button(event))
        if action is None:
            incomplete = self._standalone_incomplete(
                event,
                status="orphan_drag",
            )
            if self._active:
                self._held.append(incomplete)
                return []
            return [incomplete]
        action.samples.append(event)
        return []

    def _pointer_up(self, event: RecordingEvent) -> list[RecordingEvent]:
        action = self._active.pop(self._button(event), None)
        if action is None:
            incomplete = self._standalone_incomplete(
                event,
                status="orphan_pointer_up",
            )
            if self._active:
                self._held.append(incomplete)
                return []
            return [incomplete]
        self._held.append(self._complete(action, event))
        return [] if self._active else self._drain()

    def _complete(
        self,
        action: _PointerAction,
        up: RecordingEvent,
    ) -> RecordingEvent:
        down = action.down
        is_drag = self._is_drag(action, up)
        event_input: dict[str, Any] = {
            key: value
            for key, value in down.input.items()
            if key not in {"phase", "x", "y"}
        }
        if is_drag:
            event_input.update(
                {
                    "start_x": down.input.get("x"),
                    "start_y": down.input.get("y"),
                    "x": up.input.get("x"),
                    "y": up.input.get("y"),
                    "sample_count": len(action.samples),
                },
            )
        else:
            event_input.update(
                {
                    "x": down.input.get("x"),
                    "y": down.input.get("y"),
                },
            )
        duration = up.t_monotonic_ms - down.t_monotonic_ms
        if duration >= 0:
            event_input["duration_ms"] = duration
        return down.model_copy(
            update={
                "seq": up.seq,
                "t_monotonic_ms": up.t_monotonic_ms,
                "type": "drag" if is_drag else "click",
                "app": down.app or up.app,
                "window": down.window or up.window,
                "target": down.target or up.target,
                "input": event_input,
                "enrichment": down.enrichment or up.enrichment,
                "source": {
                    "raw_first_seq": down.seq,
                    "raw_last_seq": up.seq,
                    "raw_event_count": len(action.samples) + 2,
                    "status": "complete",
                },
                "redaction": self._combined_redaction(
                    [down, *action.samples, up],
                ),
            },
        )

    def _incomplete(
        self,
        action: _PointerAction,
        *,
        status: str,
    ) -> RecordingEvent:
        last = action.last
        return action.down.model_copy(
            update={
                "seq": last.seq,
                "t_monotonic_ms": last.t_monotonic_ms,
                "type": "pointer_incomplete",
                "source": {
                    "raw_first_seq": action.down.seq,
                    "raw_last_seq": last.seq,
                    "raw_event_count": len(action.samples) + 1,
                    "status": status,
                },
                "redaction": self._combined_redaction(
                    [action.down, *action.samples],
                ),
            },
        )

    @staticmethod
    def _standalone_incomplete(
        event: RecordingEvent,
        *,
        status: str,
    ) -> RecordingEvent:
        return event.model_copy(
            update={
                "type": "pointer_incomplete",
                "source": {
                    "raw_first_seq": event.seq,
                    "raw_last_seq": event.seq,
                    "raw_event_count": 1,
                    "status": status,
                },
            },
        )

    def _drain(self) -> list[RecordingEvent]:
        stable = sorted(self._held, key=lambda event: event.seq)
        self._held = []
        return stable

    @staticmethod
    def _button(event: RecordingEvent) -> str:
        button = event.input.get("button")
        return button if isinstance(button, str) and button else "unknown"

    @classmethod
    def _is_drag(
        cls,
        action: _PointerAction,
        up: RecordingEvent,
    ) -> bool:
        origin = cls._point(action.down)
        points = [cls._point(event) for event in [*action.samples, up]]
        if origin is None or any(point is None for point in points):
            # Missing coordinates make click semantics unsafe to infer. Keep
            # the native drag evidence when it exists.
            return bool(action.samples)
        origin_x, origin_y = origin
        return any(
            math.hypot(point[0] - origin_x, point[1] - origin_y)
            >= _CLICK_SLOP_POINTS
            for point in points
            if point is not None
        )

    @staticmethod
    def _point(event: RecordingEvent) -> tuple[float, float] | None:
        x = event.input.get("x")
        y = event.input.get("y")
        if (
            not isinstance(x, int | float)
            or isinstance(x, bool)
            or not isinstance(y, int | float)
            or isinstance(y, bool)
        ):
            return None
        return float(x), float(y)

    @staticmethod
    def _combined_redaction(
        events: list[RecordingEvent],
    ) -> dict[str, Any]:
        reasons = {
            str(reason)
            for event in events
            for reason in event.redaction.get("reasons", [])
        }
        return {
            "redacted": any(
                event.redaction.get("redacted") is True for event in events
            ),
            "reasons": sorted(reasons),
        }


__all__ = ["RecordingActionNormalizer"]
