# -*- coding: utf-8 -*-
"""Machine-precision action facts recorded alongside one live-operation take.

A take manifest is the EXIF of a recorded operation: the coordinates and
instants an action actually happened at exist only while that action runs,
and cannot be recovered from the finished video without asking a VLM to
eyeball pixels. The bridge records them transparently, so the model carries
no extra burden, and motion design later reads them to place emphasis
exactly where the operation happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from typing import Any, Mapping, Sequence

# A take is only worth annotating when its facts can be mapped onto video
# pixels. Screencast metadata reports the visible page in CSS pixels, which
# is the space locator bounding boxes are already expressed in, so the two
# combine into normalized canvas coordinates without any further guessing.
_MIN_VIEWPORT_PIXELS = 1.0


def _finite_numbers(
    source: Mapping[str, Any],
    fields: Sequence[tuple[str, float]],
) -> tuple[float, ...] | None:
    """Read a fixed set of finite floats, or reject the set atomically."""
    values: list[float] = []
    for key, default in fields:
        try:
            value = float(source.get(key, default))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        values.append(value)
    return tuple(values)


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """One locator bounding box in viewport CSS pixels."""

    x: float
    y: float
    width: float
    height: float

    @classmethod
    def from_raw(cls, raw: Any) -> "BoundingBox | None":
        """Build a box from an SDK ``bounding_box()`` result, if usable."""
        if not isinstance(raw, Mapping):
            return None
        try:
            width = float(raw["width"])
            height = float(raw["height"])
            box = cls(float(raw["x"]), float(raw["y"]), width, height)
        except (KeyError, TypeError, ValueError):
            return None
        if not all(
            math.isfinite(item) for item in (box.x, box.y, width, height)
        ):
            return None
        if width <= 0 or height <= 0:
            return None
        return box

    def as_dict(self) -> dict[str, float]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class Viewport:
    """The visible page size a take's frames were captured at."""

    width: float
    height: float

    @property
    def usable(self) -> bool:
        return (
            math.isfinite(self.width)
            and math.isfinite(self.height)
            and self.width >= _MIN_VIEWPORT_PIXELS
            and self.height >= _MIN_VIEWPORT_PIXELS
        )


def normalized_location(
    box: BoundingBox,
    viewport: Viewport,
) -> dict[str, float] | None:
    """Project a viewport box onto Creator's normalized canvas space.

    ``x``/``y`` name the box centre because Creator's ElementLocation places
    the anchor point (default ``0.5, 0.5``) at those coordinates, so a centred
    result needs no anchor bookkeeping downstream.
    """
    if not viewport.usable:
        return None
    # Playwright may report a partially clipped locator (negative origin or
    # an edge beyond the viewport).  Motion overlays consume normalized
    # *visible-canvas* coordinates, so intersect the box with the captured
    # frame instead of emitting values outside ``0..1``.
    left = max(0.0, box.x)
    top = max(0.0, box.y)
    right = min(viewport.width, box.x + box.width)
    bottom = min(viewport.height, box.y + box.height)
    if right <= left or bottom <= top:
        return None
    return {
        "x": round((left + right) / 2 / viewport.width, 5),
        "y": round((top + bottom) / 2 / viewport.height, 5),
        "width": round((right - left) / viewport.width, 5),
        "height": round((bottom - top) / viewport.height, 5),
    }


def project_location_to_canvas(
    location: Mapping[str, Any],
    placement: Mapping[str, Any] | None,
) -> dict[str, float] | None:
    """Project a source-frame box through an Edit Element placement.

    Action manifests describe positions in the *source video*.  Once an Edit
    zooms, crops, or moves that video, those coordinates are no longer canvas
    coordinates.  This function applies the same axis-aligned placement model
    as the renderer, intersects the result with the visible canvas, and gives
    motion design the box that is actually on screen.

    Rotated placements deliberately return ``None``: projecting an
    axis-aligned source box through rotation would need a polygon, and a fake
    rectangle is worse than falling back to frame observation.
    """

    source_box = _finite_numbers(
        location,
        (("x", 0.5), ("y", 0.5), ("width", 0.0), ("height", 0.0)),
    )
    if source_box is None:
        return None
    source_x, source_y, source_width, source_height = source_box
    if source_width <= 0 or source_height <= 0:
        return None

    canvas_placement = placement or {}
    placement_values = _finite_numbers(
        canvas_placement,
        (
            ("x", 0.5),
            ("y", 0.5),
            ("width", 1.0),
            ("height", 1.0),
            ("anchor_x", 0.5),
            ("anchor_y", 0.5),
            ("rotation_degrees", 0.0),
        ),
    )
    if placement_values is None:
        return None
    (
        placed_x,
        placed_y,
        placed_width,
        placed_height,
        anchor_x,
        anchor_y,
        rotation,
    ) = placement_values
    valid_placement = all(
        (
            placed_width > 0,
            placed_height > 0,
            0 <= anchor_x <= 1,
            0 <= anchor_y <= 1,
            abs(rotation) <= 1e-6,
        ),
    )
    if not valid_placement:
        return None

    placement_left = placed_x - anchor_x * placed_width
    placement_top = placed_y - anchor_y * placed_height
    source_left = source_x - source_width / 2
    source_top = source_y - source_height / 2
    left = placement_left + source_left * placed_width
    top = placement_top + source_top * placed_height
    right = left + source_width * placed_width
    bottom = top + source_height * placed_height

    visible_left = max(0.0, left)
    visible_top = max(0.0, top)
    visible_right = min(1.0, right)
    visible_bottom = min(1.0, bottom)
    if visible_right <= visible_left or visible_bottom <= visible_top:
        return None
    return {
        "x": round((visible_left + visible_right) / 2, 5),
        "y": round((visible_top + visible_bottom) / 2, 5),
        "width": round(visible_right - visible_left, 5),
        "height": round(visible_bottom - visible_top, 5),
    }


@dataclass(frozen=True, slots=True)
class ActionFact:
    """One recorded operation with its position and instant in the take."""

    op: str
    t_start_ms: int
    t_end_ms: int
    target: str = ""
    bbox: BoundingBox | None = None
    screenshot_ref: str = ""
    failed: bool = False

    def as_dict(self, viewport: Viewport | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "op": self.op,
            "t_start_ms": self.t_start_ms,
            "t_end_ms": self.t_end_ms,
        }
        if self.target:
            payload["target"] = self.target
        if self.bbox is not None:
            payload["bbox"] = self.bbox.as_dict()
            if viewport is not None:
                location = normalized_location(self.bbox, viewport)
                if location is not None:
                    payload["location"] = location
        if self.screenshot_ref:
            payload["screenshot_ref"] = self.screenshot_ref
        if self.failed:
            payload["failed"] = True
        return payload


@dataclass
class TakeManifest:
    """Every fact gathered while one take was being recorded."""

    take_id: str
    label: str = ""
    viewport: Viewport | None = None
    video_width: int = 0
    video_height: int = 0
    fps: int = 0
    duration_ms: int = 0
    frame_count: int = 0
    facts: list[ActionFact] = field(default_factory=list)

    def record(self, fact: ActionFact) -> None:
        self.facts.append(fact)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": "creator.live_operation.take_manifest",
            "schema_version": 1,
            "take_id": self.take_id,
            "video": {
                "width": self.video_width,
                "height": self.video_height,
                "fps": self.fps,
                "duration_ms": self.duration_ms,
                "frame_count": self.frame_count,
            },
            "facts": [fact.as_dict(self.viewport) for fact in self.facts],
        }
        if self.label:
            payload["label"] = self.label
        if self.viewport is not None:
            payload["viewport"] = {
                "width": self.viewport.width,
                "height": self.viewport.height,
            }
        return payload

    def as_json_bytes(self) -> bytes:
        return json.dumps(
            self.as_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=False,
        ).encode("utf-8")

    def summary(self) -> str:
        """One compact line: everything the model needs, nothing more."""
        positioned = sum(1 for fact in self.facts if fact.bbox is not None)
        parts = [
            f"{self.duration_ms / 1000:.1f}s",
            f"{len(self.facts)} actions",
            f"{positioned} with coordinates",
        ]
        if self.video_width and self.video_height:
            parts.append(f"{self.video_width}x{self.video_height}")
        return ", ".join(parts)


def facts_within(
    manifest: Mapping[str, Any],
    *,
    start_ms: float,
    end_ms: float,
    playback_rate: float = 1.0,
) -> list[dict[str, Any]]:
    """Return the manifest facts a clip spanning ``[start, end)`` covers.

    Motion design asks per clip, so the window is applied here rather than
    making every caller re-derive which actions a cut actually contains.
    """
    if not math.isfinite(playback_rate) or playback_rate <= 0:
        return []
    raw_facts = manifest.get("facts")
    if not isinstance(raw_facts, Sequence):
        return []
    selected: list[dict[str, Any]] = []
    for fact in raw_facts:
        if not isinstance(fact, Mapping):
            continue
        try:
            fact_start = float(fact.get("t_start_ms", 0))
            fact_end = float(fact.get("t_end_ms", fact_start))
        except (TypeError, ValueError):
            continue
        if (
            not math.isfinite(fact_start)
            or not math.isfinite(fact_end)
            or fact_end < fact_start
            or fact_end <= start_ms
            or fact_start >= end_ms
        ):
            continue
        shifted = dict(fact)
        # Manifest facts use source-media time. The overlay, however, runs on
        # timeline time, so a sped-up or slowed-down edit must scale the event
        # offset by the source's playback rate.
        shifted["clip_offset_ms"] = int(
            max(fact_start - start_ms, 0) / playback_rate,
        )
        selected.append(shifted)
    return selected


__all__ = [
    "ActionFact",
    "BoundingBox",
    "TakeManifest",
    "Viewport",
    "facts_within",
    "normalized_location",
    "project_location_to_canvas",
]
