# -*- coding: utf-8 -*-
"""Zero-cost rough-cut preview rendering (plan §4.8).

The blueprint's "播放粗剪" concatenates ALREADY-EXISTING artifacts — the
selected ``element_video`` per element, falling back to its
``r2v_storyboard_image`` (每个生成 element 的必经产物) held for the element
duration — into one low-resolution draft mp4. No model call is ever made;
the only tool involved is ffmpeg. Draft output is transient (streamed),
deliberately NOT registered as an artifact version so it can never be
confused with the real final cut.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from services.project_files.models import Project, Timeline

_DRAFT_HEIGHT = 480
_DRAFT_FPS = 24
_FFMPEG_TIMEOUT_SECONDS = 10 * 60.0


class RoughCutError(RuntimeError):
    """Raised when no frame source exists yet or ffmpeg fails."""


@dataclass(frozen=True)
class RoughCutClip:
    """One element's best available picture, in timeline order."""

    element_id: str
    kind: str  # "video" | "still"
    path: Path
    duration_seconds: float


def _slot_file(
    project: Project,
    slot_id: str,
    *,
    expected_kind: str,
) -> str | None:
    slot = project.assets.artifact_slots_by_id.get(slot_id)
    if slot is None or slot.kind != expected_kind:
        return None
    if not slot.selected_version_id:
        return None
    version = project.assets.artifact_versions_by_id.get(
        slot.selected_version_id,
    )
    return None if version is None else version.file_id


def collect_rough_cut_clips(
    project: Project,
    timeline: Timeline,
    *,
    resolve_file: "callable[[str], Path]",
) -> list[RoughCutClip]:
    """element_video ▸ r2v_storyboard_image, per element in time order."""

    clips: list[RoughCutClip] = []
    ordered = sorted(
        (
            element
            for element in timeline.elements_by_id.values()
            if element.enabled
        ),
        key=lambda element: (element.span.start_tick, element.element_id),
    )
    for element in ordered:
        duration = max(
            element.span.duration_tick / timeline.ticks_per_second,
            0.5,
        )
        video_file = None
        for output in element.outputs.values():
            video_file = _slot_file(
                project,
                output.slot_id,
                expected_kind="element_video",
            )
            if video_file:
                break
        if video_file:
            clips.append(
                RoughCutClip(
                    element_id=element.element_id,
                    kind="video",
                    path=resolve_file(video_file),
                    duration_seconds=duration,
                ),
            )
            continue
        storyboard_file = _slot_file(
            project,
            f"element:{element.element_id}:storyboard",
            expected_kind="r2v_storyboard_image",
        )
        if storyboard_file:
            clips.append(
                RoughCutClip(
                    element_id=element.element_id,
                    kind="still",
                    path=resolve_file(storyboard_file),
                    duration_seconds=duration,
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
            "没有可用的粗剪素材：该时间线还没有任何已生成的镜头视频或分镜图",
        )
    with tempfile.TemporaryDirectory(prefix="rough-cut-") as workdir_name:
        workdir = Path(workdir_name)
        segment_paths: list[Path] = []
        for index, clip in enumerate(clips):
            segment = workdir / f"seg-{index:03d}.mp4"
            duration = f"{clip.duration_seconds:.3f}"
            if clip.kind == "video":
                command = [
                    ffmpeg_binary,
                    "-y",
                    "-i",
                    str(clip.path),
                ]
                # Honor the planned span: freeze the last frame when the
                # generated clip runs short, hard-cap when it runs long.
                pad = f"tpad=stop_mode=clone:stop_duration={duration},"
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
                    f"scale=-2:{_DRAFT_HEIGHT},fps={_DRAFT_FPS},"
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
