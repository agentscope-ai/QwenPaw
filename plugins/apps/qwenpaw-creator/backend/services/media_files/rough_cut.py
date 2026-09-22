# -*- coding: utf-8 -*-
"""Zero-cost rough-cut preview rendering (plan §4.8).

Use existing video, storyboard or visual designs for each timeline span,
including placeholders for gaps and pictures awaiting generation. No model
call is made. FFmpeg produces a transient low-resolution draft, never
registered as a final-cut artifact version.
"""

from __future__ import annotations

import subprocess
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from services.project_files.models import Project, Timeline

_DRAFT_HEIGHT = 480
_DRAFT_FPS = 24
_FFMPEG_TIMEOUT_SECONDS = 10 * 60.0


class RoughCutError(RuntimeError):
    """Raised when the timeline has no picture spans or ffmpeg fails."""


@dataclass(frozen=True)
class RoughCutClip:
    """One element's best available picture, in timeline order."""

    element_id: str
    kind: str  # "video" | "still" | "placeholder"
    path: Path | None
    duration_seconds: float
    source_start_seconds: float = 0
    playback_rate: float = 1
    loop: bool = False
    aspect_ratio: str = "16:9"


def collect_rough_cut_clips(
    project: Project,
    timeline: Timeline,
    *,
    resolve_file: "callable[[str], Path]",
) -> list[RoughCutClip]:
    """Preserve timeline spans, using the best available picture or a gap."""
    enabled = [
        item for item in timeline.elements_by_id.values() if item.enabled
    ]
    pictures = [
        item
        for item in enabled
        if item.creation.type
        in {
            "r2v",
            "t2v",
            "i2v",
            "s2v",
            "edit",
            "motion_clip",
        }
    ]
    if not pictures:
        return []
    end = max(
        item.span.start_tick + item.span.duration_tick for item in enabled
    )
    boundaries = sorted(
        {
            0,
            end,
            *(
                point
                for item in pictures
                for point in (
                    item.span.start_tick,
                    item.span.start_tick + item.span.duration_tick,
                )
            ),
        },
    )

    def version_file(version_id):
        version = project.assets.artifact_versions_by_id.get(
            version_id,
        ) or project.assets.source_versions_by_id.get(version_id)
        file_id = getattr(version, "file_id", None)
        indexed = project.assets.files_by_id.get(file_id)
        if indexed and indexed.media_type.startswith(("image/", "video/")):
            path = resolve_file(file_id)
            if path.is_file():
                return (
                    (
                        "still"
                        if indexed.media_type.startswith("image/")
                        else "video"
                    ),
                    path,
                )
        return None

    def picture(element):
        source = element.render_source
        if source and source.type in {
            "artifact_version",
            "source_asset_version",
        }:
            resolved = version_file(source.version_id)
            if resolved:
                return (*resolved, source)
        for kind in ("element_video", "r2v_storyboard_image"):
            for slot in project.assets.artifact_slots_by_id.values():
                if (
                    slot.owner_ref == f"element:{element.element_id}"
                    and slot.kind == kind
                    and slot.selected_version_id
                ):
                    resolved = version_file(slot.selected_version_id)
                    if resolved:
                        return (*resolved, None)
        creation = element.creation
        refs = [
            *getattr(creation, "character_refs", []),
            *getattr(creation, "prop_refs", []),
        ]
        refs += [
            getattr(creation, "scene_ref", None),
            getattr(creation, "character_ref", None),
        ]
        for ref in refs:
            entity = project.visual.entities.items.get(ref)
            if entity is None:
                continue
            variant_id = getattr(creation, "visual_variant_refs", {}).get(ref)
            variant = (
                entity.variants.items.get(variant_id) if variant_id else None
            )
            version_ids = (
                [variant.selected_artifact_version_id]
                if variant
                else [
                    entity.selected_artifact_version_id,
                    *(
                        item.selected_artifact_version_id
                        for item in entity.variants.items.values()
                    ),
                ]
            )
            for version_id in version_ids:
                if version_id and (resolved := version_file(version_id)):
                    return (*resolved, None)
        return ("placeholder", None, None)

    clips = []
    for start, stop in zip(boundaries, boundaries[1:]):
        if stop <= start:
            continue
        active = [
            item
            for item in pictures
            if item.span.start_tick
            <= start
            < item.span.start_tick + item.span.duration_tick
        ]
        element = (
            max(
                active,
                key=lambda item: (
                    item.z_index,
                    item.span.start_tick,
                    item.element_id,
                ),
            )
            if active
            else None
        )
        kind, path, source = (
            picture(element) if element else ("placeholder", None, None)
        )
        rate = source.playback_rate if source else 1
        offset = (
            ((start - element.span.start_tick) / timeline.ticks_per_second)
            * rate
            if element
            else 0
        )
        if source:
            offset += source.source_in_tick / timeline.ticks_per_second
        clips.append(
            RoughCutClip(
                element_id=element.element_id if element else "gap",
                kind=kind,
                path=path,
                duration_seconds=(stop - start) / timeline.ticks_per_second,
                source_start_seconds=offset if kind == "video" else 0,
                playback_rate=rate,
                loop=source.loop if source else False,
                aspect_ratio=project.settings.aspect_ratio,
            ),
        )
    return clips


def render_rough_cut(
    clips: list[RoughCutClip],
    *,
    ffmpeg_binary: str = "ffmpeg",
) -> bytes:
    """Normalize every clip to a 480p draft segment and concat them."""

    if not clips:
        raise RoughCutError(
            "没有可用的粗剪素材：请先在时间线中规划画面片段",
        )
    with tempfile.TemporaryDirectory(prefix="rough-cut-") as workdir_name:
        workdir = Path(workdir_name)
        segment_paths: list[Path] = []
        for index, clip in enumerate(clips):
            segment = workdir / f"seg-{index:03d}.mp4"
            duration = f"{clip.duration_seconds:.3f}"
            ratio = [
                float(part) for part in re.split(r"[:x]", clip.aspect_ratio)
            ]
            width = round(_DRAFT_HEIGHT * ratio[0] / ratio[1] / 2) * 2
            if clip.kind == "placeholder":
                command = [
                    ffmpeg_binary,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    (
                        f"color=c=0x211c18:s={width}x{_DRAFT_HEIGHT}:"
                        f"r={_DRAFT_FPS}:d={duration}"
                    ),
                ]
                pad = ""
            elif clip.kind == "video":
                command = [
                    ffmpeg_binary,
                    "-y",
                    *(["-stream_loop", "-1"] if clip.loop else []),
                    "-ss",
                    str(clip.source_start_seconds),
                    "-i",
                    str(clip.path),
                ]
                # Honor the planned span: freeze the last frame when the
                # generated clip runs short, hard-cap when it runs long.
                pad = (
                    f"setpts=(PTS-STARTPTS)/{clip.playback_rate},"
                    f"tpad=stop_mode=clone:stop_duration={duration},"
                )
            else:
                command = [
                    ffmpeg_binary,
                    "-y",
                    "-loop",
                    "1",
                    "-t",
                    duration,
                    "-i",
                    str(clip.path),
                ]
                pad = ""
            command += [
                "-an",
                "-vf",
                (
                    f"scale={width}:{_DRAFT_HEIGHT}:"
                    "force_original_aspect_ratio=decrease,"
                    f"pad={width}:{_DRAFT_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
                    f"setsar=1,fps={_DRAFT_FPS},"
                    f"{pad}format=yuv420p"
                ),
                "-t",
                duration,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "30",
                str(segment),
            ]
            _run_ffmpeg(command)
            segment_paths.append(segment)
        concat_list = workdir / "concat.txt"
        concat_list.write_text(
            "".join(f"file '{path}'\n" for path in segment_paths),
            encoding="utf-8",
        )
        output = workdir / "rough-cut.mp4"
        _run_ffmpeg(
            [
                ffmpeg_binary,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(output),
            ],
        )
        return output.read_bytes()


def _run_ffmpeg(command: list[str]) -> None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=_FFMPEG_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RoughCutError("ffmpeg 不可用，无法生成粗剪") from exc
    except subprocess.TimeoutExpired as exc:
        raise RoughCutError("粗剪渲染超时") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", "replace")[-400:]
        raise RoughCutError(f"粗剪 ffmpeg 失败: {stderr}")
