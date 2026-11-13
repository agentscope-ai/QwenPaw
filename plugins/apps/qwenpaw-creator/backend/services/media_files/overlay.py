# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""Deterministic editorial-copy renderers used by AI Edit execution.

The AI Editing Director owns all copy generation.  These tools only turn an
already validated ``overlay_copy`` payload into pixels and composite those
pixels over a prepared media segment.
"""

from __future__ import annotations

from collections.abc import Mapping
import glob
import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# pylint: disable=no-name-in-module
from utils.logger import setup_logger
from services.media_files.motion_blueprints import subtitle_pack_typography
from services.media_files.motion_templates import (
    DEFAULT_CAPTION_LOCATION,
    plate_with_opacity,
)

# pylint: enable=no-name-in-module

logger = setup_logger("services.media_files.overlay")

PET_OS_VIBES = frozenset(("action", "surprise", "curious", "chill"))

# User-chosen subtitle colours arrive as ``#rrggbb``; anything else keeps
# the renderer default so a malformed setting can never break a burn-in.
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class OverlayRenderResult:
    success: bool
    error: str = ""


def _find_cjk_font() -> str | None:
    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        str(windows_fonts / "msyh.ttc"),
        str(windows_fonts / "msjh.ttc"),
    ]
    existing = [path for path in candidates if Path(path).exists()]
    for path in existing:
        if _punctuation_hugs_baseline(path):
            return path
    # A face with centred punctuation still reads; the PIL default bitmap
    # font does not, so never fall through to None when a CJK face exists.
    return existing[0] if existing else None


def _punctuation_hugs_baseline(font_path: str, size: int = 48) -> bool:
    """Reject CJK faces whose full-width punctuation floats mid-em.

    Some bundled faces (STHeiti on recent macOS) set the ink of ``，。、``
    at the vertical middle of the em box instead of hugging the baseline,
    which burns subtitles whose commas sit at mid-line height next to the
    hanzi. Quotes fail the opposite way: ``“`` belongs at the top of the em,
    so a face that centres it drops the quote to mid-line too. Check both
    edges against a hanzi glyph: correct faces carry the comma down to (or
    past) the hanzi's descent and lift the quote up to the hanzi's ascent,
    centred faces stop short on whichever edge the glyph should hug.
    """

    from PIL import ImageFont

    try:
        font = ImageFont.truetype(font_path, size)
        comma = font.getbbox("，")
        quote = font.getbbox("“")
        hanzi = font.getbbox("你")
    except OSError:
        return False
    tolerance = max(1, round(size * 0.06))
    return (
        comma[3] >= hanzi[3] - tolerance and quote[1] <= hanzi[1] + tolerance
    )


# User-chosen subtitle faces, keyed by the ``font_family`` id the style bar
# persists.  Each entry lists candidate faces across macOS / Linux / Windows;
# ``{WINDIR}`` expands to the Windows fonts root at resolve time.  "default"
# is deliberately absent: it (and any unknown id) falls through to
# ``_find_cjk_font``'s auto sans face, so an untouched project renders byte
# for byte as before.
_SUBTITLE_FONT_FAMILIES: dict[str, tuple[str, ...]] = {
    # 宋体 — serif, the classic print face.  Current macOS ships the face
    # under Supplemental/ (the bare path only exists on older releases).
    "song": (
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Songti.ttc",
        "/System/Library/Fonts/Supplemental/STSong.ttf",
        "/System/Library/Fonts/STSong.ttf",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSerifCJK-Regular.ttc",
        "{WINDIR}/Fonts/simsun.ttc",
    ),
    # 黑体 — sans, pinned per OS (the family the auto face already prefers).
    "hei": (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "{WINDIR}/Fonts/msyh.ttc",
        "{WINDIR}/Fonts/simhei.ttf",
    ),
    # 楷体 — script, for a handwritten read.  On macOS 13+ Kaiti only ships
    # as an on-demand asset under AssetsV2, whose directory name is an
    # opaque hash — the glob picks it up wherever the system cached it.
    "kai": (
        "/System/Library/Fonts/Supplemental/Kaiti.ttc",
        "/System/Library/Fonts/Kaiti.ttc",
        "/System/Library/Fonts/Supplemental/STKaiti.ttf",
        "/System/Library/Fonts/STKaiti.ttf",
        "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/*/AssetData/Kaiti.ttc",
        "/usr/share/fonts/truetype/arphic/ukai.ttc",
        "{WINDIR}/Fonts/simkai.ttf",
    ),
}


def _resolve_subtitle_font(family: object) -> str | None:
    """Pick a subtitle face for a user ``font_family`` id.

    ``None`` / ``"default"`` / any unknown id keeps ``_find_cjk_font``'s auto
    sans face.  A named family prefers its own faces (rejecting ones whose
    punctuation floats mid-em, exactly like the auto picker) and falls back to
    the auto face when none of them are installed, so a font pick can never
    leave a subtitle unrenderable.
    """

    faces = _SUBTITLE_FONT_FAMILIES.get(str(family or "").strip().lower())
    if not faces:
        return _find_cjk_font()
    windir = os.environ.get("WINDIR", "C:/Windows")
    existing: list[str] = []
    for face in faces:
        expanded = face.replace("{WINDIR}", windir)
        # On-demand macOS faces (Kaiti…) sit under opaque asset hashes, so
        # a candidate may be a glob; plain paths stay literal.
        matches = (
            sorted(glob.glob(expanded))
            if glob.has_magic(expanded)
            else [expanded]
        )
        existing.extend(path for path in matches if Path(path).exists())
    for path in existing:
        if _punctuation_hugs_baseline(path):
            return path
    return existing[0] if existing else _find_cjk_font()


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


def _subtitle_style_values(
    style: Mapping[str, Any] | None,
) -> tuple[str, float, float]:
    """Clamp a user subtitle-style mapping to ``(color, font, stroke)``.

    Missing or malformed entries fall back to the historical defaults
    (white text, base size, base outline) so an untouched project renders
    exactly as before.
    """

    data = style if isinstance(style, Mapping) else {}
    color = str(data.get("color") or "").strip()
    if not _HEX_COLOR.fullmatch(color):
        color = "#FFFFFF"

    def _scale(raw: object, fallback: float, low: float, high: float) -> float:
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return fallback
        if not math.isfinite(value):
            return fallback
        return min(high, max(low, value))

    font_scale = _scale(data.get("font_scale"), 1.0, 0.6, 1.8)
    stroke_scale = _scale(data.get("stroke_scale"), 1.0, 0.0, 3.0)
    return color, font_scale, stroke_scale


def _css_rgba(value: object) -> tuple[int, int, int, int] | None:
    """Parse a pack plate colour (``rgba(r,g,b,a)``) into a PIL colour."""

    text = str(value or "").strip()
    match = re.fullmatch(
        r"rgba?\((\d+),(\d+),(\d+)(?:,([0-9.]+))?\)",
        text,
    )
    if not match:
        return None
    red, green, blue = (min(255, int(part)) for part in match.group(1, 2, 3))
    alpha = float(match.group(4) or "1")
    if not 0.0 <= alpha <= 1.0:
        return None
    return red, green, blue, round(alpha * 255)


def _subtitle_pack_painter(
    pack_id: str | None,
    style: Mapping[str, Any] | None = None,
) -> tuple[float, tuple[int, int, int, int] | None, float]:
    """ ``(stroke multiplier, plate colour, plate radius in em)`` for a pack.

    The last-resort PNG cannot offer the pack's font family, weight or
    letter-spacing (PIL drives one validated CJK face), but the two
    attributes that change how the bar reads at a glance — outline weight
    and the plate behind the glyphs — are drawn exactly like the HTML
    template does, so the fallback never contradicts the chosen style.  The
    user's background-opacity pick is applied through the same helper the
    template uses, which is what keeps ``0`` meaning "no plate" in both.
    """

    typography = subtitle_pack_typography(pack_id)
    try:
        stroke = float(typography.get("strokeScale", 1.0) or 1.0)
    except (TypeError, ValueError):
        stroke = 1.0
    if not math.isfinite(stroke) or stroke < 0:
        stroke = 1.0
    plate = _css_rgba(
        plate_with_opacity(str(typography.get("plate") or ""), style),
    )
    radius_em = 0.28
    if plate is not None:
        raw_radius = str(typography.get("plateRadius") or "0.28em")
        try:
            radius_em = max(0.0, float(raw_radius.rstrip("em")))
        except ValueError:
            radius_em = 0.28
    return stroke, plate, radius_em


def _render_plain_subtitle_png(
    text: str,
    video_width: int,
    video_height: int,
    output_path: Path,
    location: Mapping[str, Any] | None = None,
    style: Mapping[str, Any] | None = None,
    subtitle_template: str | None = None,
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
    color, font_scale, stroke_scale = _subtitle_style_values(style)
    pack_stroke, plate, plate_radius = _subtitle_pack_painter(
        subtitle_template,
        style,
    )
    box_width, box_height = int(values["box_width"]), int(values["box_height"])
    layer = Image.new("RGBA", (box_width, box_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font_family = (
        style.get("font_family") if isinstance(style, Mapping) else None
    )
    font_path = _resolve_subtitle_font(font_family)
    padding = max(3, round(min(box_width, box_height) * 0.06))
    available_width = max(1, box_width - 2 * padding)
    available_height = max(1, box_height - 2 * padding)
    target_size = max(
        10,
        round(min(video_height * 0.04, video_width * 0.045) * font_scale),
    )
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
    if plate is not None:
        # A pack with a plate (简洁讲解 / 治愈手写 / 霓虹音乐) paints the
        # pill behind the glyphs, hugging them the same way the template's
        # ``padding:.28em .6em`` does.
        pad_x = round(size * 0.6)
        pad_y = round(size * 0.28)
        draw.rounded_rectangle(
            (
                max(0, position[0] - pad_x),
                max(0, position[1] - pad_y),
                min(box_width, position[0] + width + pad_x),
                min(box_height, position[1] + height + pad_y),
            ),
            radius=min(pad_x, pad_y, round(size * plate_radius)),
            fill=plate,
        )
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).multiline_text(
        (position[0], position[1] + max(1, round(size * 0.025))),
        display_text,
        font=font,
        spacing=spacing,
        align="center",
        fill=(0, 0, 0, 210),
        stroke_width=max(
            0,
            round(size * 0.025 * stroke_scale * pack_stroke),
        ),
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
        fill=color,
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
    style: Mapping[str, Any] | None = None,
    subtitle_template: str | None = None,
) -> bool:
    return _render_plain_subtitle_png(
        text,
        video_width,
        video_height,
        output_path,
        location,
        style,
        subtitle_template,
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
    style: Mapping[str, Any] | None = None,
    subtitle_template: str | None = None,
) -> OverlayRenderResult:
    """Render and composite an interview summary over one prepared segment."""

    overlay_path = output_path.with_suffix(".overlay.png")
    if not _render_interview_summary_png(
        text,
        *video_size,
        overlay_path,
        location=location,
        style=style,
        subtitle_template=subtitle_template,
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
