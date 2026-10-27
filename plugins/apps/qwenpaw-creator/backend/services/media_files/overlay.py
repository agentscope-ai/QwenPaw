# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""Deterministic editorial-copy renderers used by AI Edit execution.

The AI Editing Director owns all copy generation.  These tools only turn an
already validated ``overlay_copy`` payload into pixels and composite those
pixels over a prepared media segment.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# pylint: disable=no-name-in-module
from utils.logger import setup_logger
from services.media_files.motion_templates import DEFAULT_CAPTION_LOCATION

# pylint: enable=no-name-in-module

logger = setup_logger("services.media_files.overlay")

PET_OS_VIBES = frozenset(("action", "surprise", "curious", "chill"))


@dataclass(frozen=True)
class OverlayRenderResult:
    success: bool
    error: str = ""


def _find_cjk_font() -> str | None:
    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        str(windows_fonts / "msyh.ttc"),
        str(windows_fonts / "msjh.ttc"),
    ]
    return next((path for path in candidates if Path(path).exists()), None)


def _placement_values(
    location: Mapping[str, Any],
    video_width: int,
    video_height: int,
) -> dict[str, float | int]:
    defaults = {
        "x": 0.5,
        "y": 0.5,
        "width": 1.0,
        "height": 1.0,
        "anchor_x": 0.5,
        "anchor_y": 0.5,
        "rotation_degrees": 0.0,
        "opacity": 1.0,
    }
    values: dict[str, float] = {}
    for key, fallback in defaults.items():
        try:
            value = float(location.get(key, fallback))
        except (TypeError, ValueError):
            value = fallback
        values[key] = value if math.isfinite(value) else fallback
    values["width"] = max(1 / video_width, values["width"])
    values["height"] = max(1 / video_height, values["height"])
    values["width"] = min(1.0, values["width"])
    values["height"] = min(1.0, values["height"])
    values["anchor_x"] = min(1.0, max(0.0, values["anchor_x"]))
    values["anchor_y"] = min(1.0, max(0.0, values["anchor_y"]))
    values["opacity"] = min(1.0, max(0.0, values["opacity"]))
    left = values["x"] - values["anchor_x"] * values["width"]
    top = values["y"] - values["anchor_y"] * values["height"]
    if left < 0.0:
        values["x"] -= left
    elif left + values["width"] > 1.0:
        values["x"] -= left + values["width"] - 1.0
    if top < 0.0:
        values["y"] -= top
    elif top + values["height"] > 1.0:
        values["y"] -= top + values["height"] - 1.0
    return {
        **values,
        "box_width": max(1, round(video_width * values["width"])),
        "box_height": max(1, round(video_height * values["height"])),
        "canvas_x": round(video_width * values["x"]),
        "canvas_y": round(video_height * values["y"]),
    }


def _place_layer(
    canvas: Any,
    layer: Any,
    location: Mapping[str, Any],
) -> Any:
    """Place a PIL layer using the same anchor transform as ElementLocation."""

    from PIL import Image

    values = _placement_values(location, canvas.width, canvas.height)
    anchor_x = round(layer.width * float(values["anchor_x"]))
    anchor_y = round(layer.height * float(values["anchor_y"]))
    padded_width = max(1, 2 * max(anchor_x, layer.width - anchor_x))
    padded_height = max(1, 2 * max(anchor_y, layer.height - anchor_y))
    padded = Image.new("RGBA", (padded_width, padded_height), (0, 0, 0, 0))
    padded.alpha_composite(
        layer,
        (padded_width // 2 - anchor_x, padded_height // 2 - anchor_y),
    )
    rotation = float(values["rotation_degrees"])
    placed = (
        padded.rotate(
            -rotation,
            resample=Image.Resampling.BICUBIC,
            expand=True,
        )
        if rotation
        else padded
    )
    opacity = float(values["opacity"])
    if opacity < 1:
        alpha = placed.getchannel("A").point(
            lambda value: round(value * opacity),
        )
        placed.putalpha(alpha)
    canvas.alpha_composite(
        placed,
        (
            round(int(values["canvas_x"]) - placed.width / 2),
            round(int(values["canvas_y"]) - placed.height / 2),
        ),
    )
    return canvas


def _wrap_subtitle(text: str, draw: Any, font: Any, width: int) -> str:
    """Preserve authored lines and keep Latin words together when they fit."""
    lines: list[str] = []
    for paragraph in text.splitlines():
        current = ""
        tokens = re.findall(
            r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[ \t]+|.",
            paragraph,
        )
        for token in tokens:
            pieces = [token]
            if draw.textlength(token, font=font) > width:
                pieces = list(token)
            for piece in pieces:
                if (
                    current
                    and draw.textlength(current + piece, font=font) > width
                ):
                    lines.append(current.rstrip())
                    current = piece.lstrip()
                else:
                    current += piece
        lines.append(current.rstrip())
    return "\n".join(lines)


def _render_plain_subtitle_png(
    text: str,
    video_width: int,
    video_height: int,
    output_path: Path,
    location: Mapping[str, Any] | None = None,
) -> bool:
    """Render exact subtitle copy over a transparent background."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError:
        logger.warning("PIL unavailable; subtitle rendering failed")
        return False
    location = (
        location if isinstance(location, Mapping) else DEFAULT_CAPTION_LOCATION
    )
    values = _placement_values(location, video_width, video_height)
    box_width, box_height = int(values["box_width"]), int(values["box_height"])
    layer = Image.new("RGBA", (box_width, box_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font_path = _find_cjk_font()
    padding = max(3, round(min(box_width, box_height) * 0.06))
    available_width = max(1, box_width - 2 * padding)
    available_height = max(1, box_height - 2 * padding)
    target_size = max(10, round(min(video_height * 0.04, video_width * 0.045)))
    for size in range(target_size, 9, -1):
        font = (
            ImageFont.truetype(font_path, size)
            if font_path
            else ImageFont.load_default()
        )
        display_text = _wrap_subtitle(
            text.strip(),
            draw,
            font,
            available_width,
        )
        spacing = max(2, round(size * 0.35))
        bounds = draw.multiline_textbbox(
            (0, 0),
            display_text,
            font=font,
            spacing=spacing,
            align="center",
        )
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        if width <= available_width and height <= available_height:
            break
    else:
        logger.warning("Subtitle copy does not fit its placement box")
        return False
    position = (
        (box_width - width) / 2 - bounds[0],
        (box_height - height) / 2 - bounds[1],
    )
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).multiline_text(
        (position[0], position[1] + max(1, round(size * 0.025))),
        display_text,
        font=font,
        spacing=spacing,
        align="center",
        fill=(0, 0, 0, 210),
        stroke_width=max(1, round(size * 0.025)),
        stroke_fill=(0, 0, 0, 180),
    )
    layer.alpha_composite(
        shadow.filter(ImageFilter.GaussianBlur(max(0.5, size * 0.025))),
    )
    ImageDraw.Draw(layer).multiline_text(
        position,
        display_text,
        font=font,
        spacing=spacing,
        align="center",
        fill="#FFFFFF",
    )
    canvas = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    _place_layer(canvas, layer, location)
    try:
        canvas.save(output_path, "PNG")
        return True
    except Exception as exc:
        logger.warning("Subtitle PNG save failed: %s", exc)
        return False


def _render_pet_os_png(
    text: str,
    vibe: str,
    video_width: int,
    video_height: int,
    output_path: Path,
    location: Mapping[str, Any] | None = None,
) -> bool:
    """Keep legacy pet-overlay inputs compatible with plain subtitles."""
    del vibe
    return _render_plain_subtitle_png(
        text,
        video_width,
        video_height,
        output_path,
        location,
    )


def _render_interview_summary_png(
    text: str,
    video_width: int,
    video_height: int,
    output_path: Path,
    location: Mapping[str, Any] | None = None,
) -> bool:
    return _render_plain_subtitle_png(
        text,
        video_width,
        video_height,
        output_path,
        location,
    )


def _composite_overlay(
    *,
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    overlay_path: Path,
    enable_expression: str,
) -> OverlayRenderResult:
    # A PNG has no duration/PTS.  Loop it as a 25 fps stream and stop at the
    # primary video boundary so the overlay remains visible for its requested
    # interval without extending the rendered segment.
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(input_path),
        "-loop",
        "1",
        "-framerate",
        "25",
        "-i",
        str(overlay_path),
        "-filter_complex",
        (
            "[1:v]format=rgba[ov],[0:v][ov]overlay=0:0:shortest=1:"
            f"enable='{enable_expression}',"
            "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        ),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-c:a",
        "copy",
        "-shortest",
        str(output_path),
    ]
    try:
        result = subprocess.run(
            command,
            # Detach stdin so ffmpeg is not suspended by SIGTTIN when it
            # reads the tty from a background process group.
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        return OverlayRenderResult(False, str(exc))
    if result.returncode != 0 or not output_path.exists():
        return OverlayRenderResult(False, (result.stderr or "")[-200:])
    return OverlayRenderResult(True)


def render_pet_os_overlay(
    *,
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    text: str,
    vibe: str,
    video_size: tuple[int, int],
    appear_at: float,
    duration: float,
    location: Mapping[str, Any] | None = None,
) -> OverlayRenderResult:
    """Render a legacy pet caption as a plain subtitle over the segment."""

    overlay_path = output_path.with_suffix(".overlay.png")
    if not _render_pet_os_png(
        text,
        vibe,
        *video_size,
        overlay_path,
        location=location,
    ):
        return OverlayRenderResult(False, "宠物 OS PNG 渲染失败")
    try:
        return _composite_overlay(
            ffmpeg_path=ffmpeg_path,
            input_path=input_path,
            output_path=output_path,
            overlay_path=overlay_path,
            enable_expression=f"between(t,{appear_at},{appear_at + duration})",
        )
    finally:
        overlay_path.unlink(missing_ok=True)


def render_interview_summary_overlay(
    *,
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    text: str,
    video_size: tuple[int, int],
    appear_at: float,
    duration: float,
    location: Mapping[str, Any] | None = None,
) -> OverlayRenderResult:
    """Render and composite an interview summary over one prepared segment."""

    overlay_path = output_path.with_suffix(".overlay.png")
    if not _render_interview_summary_png(
        text,
        *video_size,
        overlay_path,
        location=location,
    ):
        return OverlayRenderResult(False, "采访总结 PNG 渲染失败")
    try:
        return _composite_overlay(
            ffmpeg_path=ffmpeg_path,
            input_path=input_path,
            output_path=output_path,
            overlay_path=overlay_path,
            enable_expression=f"between(t,{appear_at},{appear_at + duration})",
        )
    finally:
        overlay_path.unlink(missing_ok=True)


__all__ = [
    "OverlayRenderResult",
    "PET_OS_VIBES",
    "render_interview_summary_overlay",
    "render_pet_os_overlay",
]
