# -*- coding: utf-8 -*-
"""Align newly drafted launch captions when generated hard cuts drift.

This is deliberately a narrow, evidence-based fast path: one selected full
R2V, a contiguous authored shot plan, exactly the same number of strong
cuts, and captions still occupying complete planned shots. Authored motion
and manually timed overlays are never retimed by this path.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from domain.errors import ValidationError
from services.media_files.element_adapter import selected_element_output
from services.media_files.informal_launch_template import (
    uses_informal_launch_captions,
)
from services.media_files.keyframe_cache import verified_indexed_path
from services.project_files.models import (
    ElementOutputRenderSource,
    OverlayCreation,
    Project,
    R2VCreation,
    Timeline,
    TimelineElement,
    TimelineSpan,
)

_SHOT_RANGE = re.compile(
    r"(?:镜头\s*\d+|第\s*\d+\s*镜)\s*[（(｜|:：]?\s*"
    r"(?P<start>\d+(?:\.\d+)?)\s*[–—~～至到-]\s*"
    r"(?P<end>\d+(?:\.\d+)?)\s*(?:秒|s\b|seconds?\b)",
)


def planned_shot_ranges(
    text: str,
    duration: float,
) -> list[tuple[float, float]]:
    ranges = list(
        dict.fromkeys(
            (float(m["start"]), float(m["end"]))
            for m in _SHOT_RANGE.finditer(text)
        ),
    )
    if (
        len(ranges) < 2
        or abs(ranges[0][0]) > 0.02
        or abs(ranges[-1][1] - duration) > 0.05
        or any(end <= start for start, end in ranges)
        or any(
            abs(left[1] - right[0]) > 0.02
            for left, right in zip(ranges, ranges[1:])
        )
    ):
        return []
    return ranges


def detect_hard_cuts(path: Path, ffmpeg_path: str) -> list[float]:
    """Use decoded pixels, never planned timestamps, as cut evidence."""
    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-i",
                str(path),
                "-vf",
                "scale=320:-1,select='gt(scene,0.10)',showinfo",
                "-an",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValidationError("非正式发布会实片切点检查失败，请重试后再设计字幕") from exc
    return [float(v) for v in re.findall(r"pts_time:([\d.]+)", result.stderr)]


# The guards intentionally decline ambiguous evidence before any retiming.
# pylint: disable=too-many-return-statements,too-many-boolean-expressions
def align_launch_caption_spans(
    project: Project,
    timeline: Timeline,
    overlays: list[TimelineElement],
    project_root: Path,
    ffmpeg_path: str,
) -> tuple[dict[str, TimelineSpan], dict[str, Any]]:
    """Propose a retime for the caller to commit with the final designs."""
    skipped = {"status": "kept_authored_timing"}
    if not uses_informal_launch_captions(timeline) or not overlays:
        return {}, skipped
    if any(
        not isinstance(item.creation, OverlayCreation) or item.creation.motion
        for item in overlays
    ):
        return {}, skipped
    videos = [
        item
        for item in timeline.elements_by_id.values()
        if item.enabled and isinstance(item.creation, R2VCreation)
    ]
    if len(videos) != 1:
        return {}, skipped
    video = videos[0]
    source = video.render_source
    if (
        video.span.start_tick != 0
        or not isinstance(source, ElementOutputRenderSource)
        or source.element_id != video.element_id
        or source.source_in_tick != 0
        or source.source_out_tick is not None
        or source.playback_rate != 1
        or source.loop
    ):
        return {}, skipped
    duration = video.span.duration_tick / timeline.ticks_per_second
    ranges = planned_shot_ranges(video.creation.narrative, duration)
    if not ranges:
        return {}, {"status": "unverified", "reason": "没有连续的逐镜时间计划；保留现有时序"}
    matches = {}
    for item in overlays:
        start = item.span.start_tick / timeline.ticks_per_second
        end = (
            item.span.start_tick + item.span.duration_tick
        ) / timeline.ticks_per_second
        index = next(
            (
                i
                for i, pair in enumerate(ranges)
                if abs(pair[0] - start) < 0.002 and abs(pair[1] - end) < 0.002
            ),
            None,
        )
        if index is None:
            return {}, skipped
        matches[item.element_id] = index
    selected = selected_element_output(project, video, source.output_name)
    if selected is None:
        raise ValidationError("非正式发布会字幕需等待实片生成后对齐切点")
    version = project.assets.artifact_versions_by_id[selected[1]]
    if version.stale:
        raise ValidationError("非正式发布会字幕不能对齐已过期的视频")
    path = verified_indexed_path(
        project_root,
        project.assets.files_by_id[version.file_id],
    )
    cuts = detect_hard_cuts(path, ffmpeg_path)
    boundaries = [0.0, *cuts, duration]
    if (
        len(boundaries) != len(ranges) + 1
        or any(b - a < 0.6 for a, b in zip(boundaries, boundaries[1:]))
        or any(
            abs(a - b[0]) > max(2, duration * 0.15)
            for a, b in zip(boundaries, ranges)
        )
    ):
        return {}, {
            "status": "unverified",
            "reason": "实片切点与计划不能一一对应，需核对时序；未盲目移动字幕",
            "cutTimesSeconds": cuts,
        }
    spans = {}
    for element_id, index in matches.items():
        start = round(boundaries[index] * timeline.ticks_per_second)
        end = round(boundaries[index + 1] * timeline.ticks_per_second)
        spans[element_id] = TimelineSpan(
            start_tick=start,
            duration_tick=end - start,
        )
    return spans, {
        "status": "aligned_to_real_cuts",
        "sourceVersionId": version.version_id,
        "sourceSlotId": video.outputs[source.output_name].slot_id,
        "cutTimesSeconds": cuts,
        "note": "镜头数量与强切点一一对应；保留叙事顺序，字幕改用实片边界。构图和语义仍按实帧验收。",
    }
