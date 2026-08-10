# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""xfade/acrossfade filter-chain construction for Element transitions.

A Timeline Element with ``creation.type=transition`` explicitly references
two adjacent main-track Elements, and its span sits inside the time
intersection of both endpoint spans. This module translates that model
semantics into one deterministic ffmpeg ``filter_complex``:

- adjacent segments joined by a non-cut transition use ``xfade`` (video) +
  ``acrossfade`` (audio);
- cut joins, or adjacent pairs without a transition, use ``concat``;
- silent segments are padded with ``anullsrc`` so acrossfade/concat stream
  alignment holds.

Timing convention: blend duration d is the overlap consumed between adjacent
segments on the chain. For the k-th transition pair,
``offset = accumulated chain duration - d``, and the total chain duration is
Σ segment durations - Σ d, matching the Timeline authoring convention of
"endpoint Elements overlap by d and the transition span is the
intersection".
"""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_TRANSITION_DURATION_SECONDS = 0.4
# Whitelist of official xfade filter names; crossfade is a common
# model-side alias and is normalised to fade.
SUPPORTED_XFADE_KINDS = {
    "fade",
    "fadeblack",
    "fadewhite",
    "dissolve",
    "wipeleft",
}
_KIND_ALIASES = {
    "crossfade": "fade",
    "": "fade",
}


def normalize_transition_kind(value: object) -> str:
    """Normalise transition_kind: cut stays a hard cut, unknown kinds fall
    back to fade."""

    name = str(value or "").strip().casefold()
    if name == "cut":
        return "cut"
    name = _KIND_ALIASES.get(name, name)
    if name in SUPPORTED_XFADE_KINDS:
        return name
    return "fade"


@dataclass(frozen=True, slots=True)
class TransitionClip:
    """One normalised segment: on-chain duration (seconds) and whether it
    carries an audio stream."""

    duration_seconds: float
    has_audio: bool


@dataclass(frozen=True, slots=True)
class TransitionJoin:
    """How segments i-1 → i join. ``blend_seconds<=0`` means hard-cut concat."""

    kind: str = "cut"
    blend_seconds: float = 0.0

    def effective_blend(self) -> float:
        if normalize_transition_kind(self.kind) == "cut":
            return 0.0
        return max(0.0, float(self.blend_seconds))


def compute_chain_duration(
    clips: list[TransitionClip],
    joins: list[TransitionJoin],
) -> float:
    """Total chain duration = Σ segment durations - Σ effective blends."""

    _validate_shapes(clips, joins)
    total = sum(clip.duration_seconds for clip in clips)
    consumed = sum(join.effective_blend() for join in joins)
    return max(0.0, total - consumed)


def _validate_shapes(
    clips: list[TransitionClip],
    joins: list[TransitionJoin],
) -> None:
    if not clips:
        raise ValueError("transition chain requires at least one clip")
    if len(joins) != len(clips) - 1:
        raise ValueError(
            f"joins/clips length mismatch: {len(joins)} vs {len(clips) - 1}",
        )
    for index, clip in enumerate(clips):
        if not clip.duration_seconds > 0:
            raise ValueError(
                f"invalid clip duration at index {index}: "
                f"{clip.duration_seconds!r}",
            )
    for index, join in enumerate(joins):
        blend = join.effective_blend()
        if blend <= 0:
            continue
        # The blend consumes time from both neighbouring clips; exceeding
        # either clip would make the xfade offset go backwards.
        limit = min(
            clips[index].duration_seconds,
            clips[index + 1].duration_seconds,
        )
        if blend >= limit:
            raise ValueError(
                f"transition blend at join {index} ({blend:.3f}s) must be "
                f"shorter than both adjacent clips ({limit:.3f}s)",
            )


def build_transition_filter_chain(
    clips: list[TransitionClip],
    joins: list[TransitionJoin],
    *,
    canvas_size: tuple[int, int],
    fps: float = 30.0,
) -> str:
    """Build the N-segment filter_complex emitting ``[vout]``/``[aout]``.

    Segments are first normalised to the canvas size, frame rate, and
    yuv420p so xfade does not fail on mismatched specs; audio is normalised
    to 44100Hz stereo fltp, with missing tracks padded via anullsrc.
    """

    _validate_shapes(clips, joins)
    width, height = int(canvas_size[0]), int(canvas_size[1])
    n = len(clips)
    filters: list[str] = []
    for i, clip in enumerate(clips):
        filters.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            f"fps={fps:g},settb=AVTB,format=yuv420p,setpts=PTS-STARTPTS[v{i}]",
        )
        if clip.has_audio:
            filters.append(
                f"[{i}:a]aresample=44100,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"apad=whole_dur={clip.duration_seconds:.6f},"
                f"asetpts=PTS-STARTPTS[ai{i}]",
            )
        else:
            filters.append(
                "anullsrc=channel_layout=stereo:sample_rate=44100,"
                f"atrim=duration={clip.duration_seconds:.6f},"
                f"asetpts=PTS-STARTPTS[ai{i}]",
            )

    if n == 1:
        filters.append("[v0]format=yuv420p[vout]")
        filters.append("[ai0]anull[aout]")
        return ";".join(filters)

    prev_v = "v0"
    prev_a = "ai0"
    accumulated = clips[0].duration_seconds
    for i in range(1, n):
        join = joins[i - 1]
        blend = join.effective_blend()
        new_v = f"vchain{i}"
        new_a = f"achain{i}"
        if blend <= 0:
            filters.append(
                f"[{prev_v}][v{i}]concat=n=2:v=1:a=0[{new_v}]",
            )
            filters.append(
                f"[{prev_a}][ai{i}]concat=n=2:v=0:a=1[{new_a}]",
            )
            accumulated += clips[i].duration_seconds
        else:
            kind = normalize_transition_kind(join.kind)
            offset = max(0.0, accumulated - blend)
            filters.append(
                f"[{prev_v}][v{i}]xfade=transition={kind}:"
                f"duration={blend:.6f}:offset={offset:.6f}[{new_v}]",
            )
            filters.append(
                f"[{prev_a}][ai{i}]acrossfade=d={blend:.6f}:"
                f"c1=tri:c2=tri[{new_a}]",
            )
            accumulated = offset + clips[i].duration_seconds
        prev_v = new_v
        prev_a = new_a

    filters.append(f"[{prev_v}]format=yuv420p[vout]")
    filters.append(f"[{prev_a}]anull[aout]")
    return ";".join(filters)


__all__ = [
    "DEFAULT_TRANSITION_DURATION_SECONDS",
    "SUPPORTED_XFADE_KINDS",
    "TransitionClip",
    "TransitionJoin",
    "build_transition_filter_chain",
    "compute_chain_duration",
    "normalize_transition_kind",
]
