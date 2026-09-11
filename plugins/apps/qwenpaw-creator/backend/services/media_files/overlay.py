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
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# pylint: disable=no-name-in-module
from utils.logger import setup_logger

# pylint: enable=no-name-in-module

logger = setup_logger("services.media_files.overlay")

PET_OS_VIBES = frozenset(("action", "surprise", "curious", "chill"))


@dataclass(frozen=True)
class OverlayRenderResult:
    success: bool
    error: str = ""


def _find_cjk_font() -> str | None:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    return next((path for path in candidates if Path(path).exists()), None)


def _find_emoji_font() -> str | None:
    candidates = [
        "/System/Library/Fonts/Apple Color Emoji.ttc",
        "/System/Library/Fonts/Supplemental/Apple Color Emoji.ttc",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/noto/NotoColorEmoji.ttf",
    ]
    return next((path for path in candidates if os.path.exists(path)), None)


def _vibe_emoji(vibe: str) -> str:
    return {
        "action": "😾",
        "surprise": "🙀",
        "curious": "🐱",
        "chill": "😺",
    }.get(vibe, "😺")


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


def _render_placed_text_box(
    *,
    text: str,
    video_width: int,
    video_height: int,
    output_path: Path,
    location: Mapping[str, Any],
    bubble: bool,
) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False

    values = _placement_values(location, video_width, video_height)
    box_width = int(values["box_width"])
    box_height = int(values["box_height"])
    canvas = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    font_path = _find_cjk_font()

    if bubble:
        layer = Image.new("RGBA", (box_width, box_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        padding = max(3, round(min(box_width, box_height) * 0.1))
        border = max(1, round(box_height * 0.035))
        draw.rounded_rectangle(
            (border, border, box_width - border - 1, box_height - border - 1),
            radius=max(4, round(box_height * 0.28)),
            fill=(255, 255, 255, 238),
            outline=(20, 20, 20, 255),
            width=border,
        )
        font_size = max(
            10,
            min(
                round(box_height * 0.34),
                round(box_width / max(4, len(text)) * 1.55),
            ),
        )
    else:
        target_font_size = max(16, round(video_width / 1280 * 34))
        max_box_w = min(box_width, round(video_width * 0.7))
        max_box_h = min(box_height, round(video_height * 0.25))
        _est_padding = max(8, round(min(max_box_w, max_box_h) * 0.12))
        try:
            _probe = (
                ImageFont.truetype(font_path, target_font_size)
                if font_path
                else ImageFont.load_default()
            )
        except Exception:
            _probe = ImageFont.load_default()
        _tmp = ImageDraw.Draw(canvas)
        _probe_avail_w = max(1, max_box_w - _est_padding * 2)
        _probe_lines: list[str] = []
        _cur = ""
        for _ch in text.strip():
            _cand = _cur + _ch
            if (
                _cur
                and _tmp.textbbox((0, 0), _cand, font=_probe)[2]
                > _probe_avail_w
            ):
                _probe_lines.append(_cur)
                _cur = _ch
            else:
                _cur = _cand
        if _cur:
            _probe_lines.append(_cur)
        _probe_text = "\n".join(_probe_lines)
        _pb = _tmp.multiline_textbbox(
            (0, 0),
            _probe_text,
            font=_probe,
            spacing=4,
        )
        _tw = _pb[2] - _pb[0]
        _th = _pb[3] - _pb[1]
        actual_w = min(_tw + _est_padding * 2, max_box_w)
        actual_h = min(_th + _est_padding * 2, max_box_h)
        padding = max(8, round(min(actual_w, actual_h) * 0.12))
        font_size = target_font_size
        if (
            _tw + _est_padding * 2 > max_box_w
            or _th + _est_padding * 2 > max_box_h
        ):
            font_size = max(
                10,
                round(
                    target_font_size
                    * min(
                        max_box_w / max(_tw + _est_padding * 2, 1),
                        max_box_h / max(_th + _est_padding * 2, 1),
                    ),
                ),
            )
        border = max(2, round(min(actual_w, actual_h) * 0.04))
        box_width = actual_w
        box_height = actual_h
        layer = Image.new("RGBA", (box_width, box_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        draw.rounded_rectangle(
            (0, 0, box_width - 1, box_height - 1),
            radius=max(4, round(min(box_width, box_height) * 0.18)),
            fill=(0, 0, 0, 153),
            outline=(255, 255, 255, 51),
            width=border,
        )

    try:
        font = (
            ImageFont.truetype(font_path, font_size)
            if font_path
            else ImageFont.load_default()
        )
    except Exception:
        font = ImageFont.load_default()

    if bubble:
        available_width = max(1, box_width - padding * 2)
        lines: list[str] = []
        current = ""
        for character in text.strip():
            candidate = current + character
            bounds = draw.textbbox((0, 0), candidate, font=font)
            if current and bounds[2] - bounds[0] > available_width:
                lines.append(current)
                current = character
            else:
                current = candidate
        if current:
            lines.append(current)
        display_text = "\n".join(lines[:2])
        bounds = draw.multiline_textbbox(
            (0, 0),
            display_text,
            font=font,
            spacing=2,
            align="center",
        )
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        try:
            descent = font.getmetrics()[1]
        except AttributeError:
            descent = 0
        text_x = (box_width - text_width) / 2
        text_y = (box_height - text_height + descent) / 2 - bounds[1]
        draw.multiline_text(
            (text_x, text_y),
            display_text,
            font=font,
            spacing=2,
            align="center",
            fill="#111111",
            stroke_width=0,
            stroke_fill="#000000",
        )
    else:
        available_width = max(1, box_width - padding * 2)
        lines = []
        current = ""
        for character in text.strip():
            candidate = current + character
            bounds = draw.textbbox((0, 0), candidate, font=font)
            if current and bounds[2] - bounds[0] > available_width:
                lines.append(current)
                current = character
            else:
                current = candidate
        if current:
            lines.append(current)
        display_text = "\n".join(lines)
        bounds = draw.multiline_textbbox(
            (0, 0),
            display_text,
            font=font,
            spacing=4,
            align="center",
        )
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        try:
            descent = font.getmetrics()[1]
        except AttributeError:
            descent = 0
        text_x = (box_width - text_width) / 2
        text_y = (box_height - text_height + descent) / 2 - bounds[1]
        draw.multiline_text(
            (text_x, text_y),
            display_text,
            font=font,
            spacing=4,
            align="center",
            fill="#FFFFFF",
            stroke_width=max(1, round(font_size * 0.08)),
            stroke_fill="#000000",
        )

    _place_layer(canvas, layer, location)
    try:
        canvas.save(output_path, "PNG")
        return True
    except Exception as exc:
        logger.warning("placed overlay save failed: %s", exc)
        return False


def _render_placed_pet_os_box(
    *,
    text: str,
    vibe: str,
    video_width: int,
    video_height: int,
    output_path: Path,
    location: Mapping[str, Any],
) -> bool:
    """Render the speech-bubble, tail, and emoji auto-sized to text content."""

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False

    values = _placement_values(location, video_width, video_height)
    max_box_w = int(values["box_width"])
    max_box_h = int(values["box_height"])
    canvas = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))

    font_path = _find_cjk_font()
    target_font_size = max(10, round(video_width / 1280 * 30))
    max_bubble_w = max(1, round(max_box_w * 0.9))

    tail_height = max(8, round(max_box_h * 0.09))
    emoji_size = max(18, round(max_box_h * 0.2))
    emoji_gap = max(2, round(max_box_h * 0.025))

    def _wrap_text(draw_ref, font_ref, max_w):
        result: list[str] = []
        cur = ""
        for ch in text.strip():
            cand = cur + ch
            if (
                cur
                and draw_ref.textbbox((0, 0), cand, font=font_ref)[2] > max_w
            ):
                result.append(cur)
                cur = ch
            else:
                cur = cand
        if cur:
            result.append(cur)
        return result

    probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    probe_draw = ImageDraw.Draw(probe)

    font_size = target_font_size
    lines: list[str] = []
    text_w = 0
    text_h = 0
    border = 2
    padding = 5
    box_width = 1
    box_height = 1
    bubble_body_height = 1

    while font_size >= 10:
        try:
            font = (
                ImageFont.truetype(font_path, font_size)
                if font_path
                else ImageFont.load_default()
            )
        except Exception:
            font = ImageFont.load_default()
        border = max(2, round(max_box_h * 0.018))
        padding = max(5, round(max_box_h * 0.04))
        avail_w = max(1, max_bubble_w - padding * 2 - border * 2)
        lines = _wrap_text(probe_draw, font, avail_w)
        display_text = "\n".join(lines)
        bounds = probe_draw.multiline_textbbox(
            (0, 0),
            display_text,
            font=font,
            spacing=2,
        )
        text_w = bounds[2] - bounds[0]
        text_h = bounds[3] - bounds[1]
        box_width = min(text_w + padding * 2 + border * 2, max_bubble_w)
        bubble_body_height = text_h + padding * 2 + border * 2
        box_height = bubble_body_height + max(
            tail_height,
            emoji_size + emoji_gap,
        )
        if (
            text_w + padding * 2 + border * 2 <= max_bubble_w
            and box_height <= max_box_h
        ):
            break
        font_size -= 1

    box_width = max(box_width, 1)
    box_height = max(box_height, 1)

    layer = Image.new("RGBA", (box_width, box_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    bubble_x = 0
    bubble_y = 0

    bubble_bottom = bubble_y + bubble_body_height - border / 2
    bubble_right = bubble_x + box_width - border
    bubble_radius = max(
        5,
        round(min(box_width, bubble_body_height) * 0.09),
    )
    draw.rounded_rectangle(
        (
            bubble_x + border / 2,
            bubble_y + border / 2,
            bubble_right,
            bubble_bottom,
        ),
        radius=bubble_radius,
        fill="white",
        outline="black",
        width=border,
    )

    tail_rel_x = min(
        box_width - border - tail_height * 2,
        max(border + tail_height * 2, round(box_width * 0.28)),
    )
    tail_x = bubble_x + tail_rel_x
    tail_tip = (
        tail_x - round(tail_height * 0.55),
        bubble_bottom + tail_height,
    )
    draw.polygon(
        [
            (tail_x, bubble_bottom),
            tail_tip,
            (tail_x + tail_height, bubble_bottom),
        ],
        fill="white",
    )
    draw.line(
        [(tail_x, bubble_bottom), tail_tip],
        fill="black",
        width=border,
    )
    draw.line(
        [tail_tip, (tail_x + tail_height, bubble_bottom)],
        fill="black",
        width=border,
    )

    # The filled bubble must be painted before its copy.  Otherwise the white
    # rectangle covers the glyphs and the fallback renders as an empty card.
    text_area_h = bubble_body_height - border * 2 - padding * 2
    text_y = (
        bubble_y
        + border
        + padding
        + max(0, (text_area_h - text_h) / 2)
        - bounds[1]
    )
    draw.multiline_text(
        (bubble_x + border + padding, text_y),
        display_text,
        font=font,
        spacing=2,
        fill="#111111",
    )

    emoji_font_path = _find_emoji_font()
    try:
        bitmap_sizes = [160, 96, 64, 48, 40, 32, 20]
        render_size = next(
            (s for s in bitmap_sizes if s >= emoji_size),
            bitmap_sizes[0],
        )
        emoji_font = (
            ImageFont.truetype(emoji_font_path, render_size)
            if emoji_font_path
            else None
        )
        if emoji_font:
            cell = render_size + 4
            emoji_image = Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
            ImageDraw.Draw(emoji_image).text(
                (2, 2),
                _vibe_emoji(vibe),
                font=emoji_font,
                embedded_color=True,
            )
            emoji_image = emoji_image.resize(
                (emoji_size, emoji_size),
                Image.Resampling.LANCZOS,
            )
            emoji_x = max(
                bubble_x,
                min(
                    bubble_x + box_width - emoji_size,
                    tail_tip[0] - emoji_size // 2,
                ),
            )
            emoji_y = min(
                box_height - emoji_size,
                round(bubble_bottom + emoji_gap),
            )
            layer.alpha_composite(emoji_image, (emoji_x, emoji_y))
    except Exception:
        logger.debug("emoji font rendering unavailable", exc_info=True)

    _place_layer(canvas, layer, location)
    try:
        canvas.save(output_path, "PNG")
        return True
    except Exception as exc:
        logger.warning("placed pet OS overlay save failed: %s", exc)
        return False


def _render_pet_os_png(
    text: str,
    vibe: str,
    video_width: int,
    video_height: int,
    output_path: Path,
    location: Mapping[str, Any] | None = None,
) -> bool:
    if isinstance(location, Mapping):
        return _render_placed_pet_os_box(
            text=text,
            vibe=vibe,
            video_width=video_width,
            video_height=video_height,
            output_path=output_path,
            location=location,
        )
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("PIL unavailable; pet OS overlay skipped")
        return False

    image = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    scale = video_width / 1280.0
    font_path = _find_cjk_font()
    font_size = max(20, round(30 * scale))
    if font_path:
        try:
            font = ImageFont.truetype(font_path, font_size)
        except Exception:
            font = ImageFont.load_default()
    else:
        font = ImageFont.load_default()

    padding = round(14 * scale)
    line_height = round(font_size * 1.45)
    max_line_chars = max(5, round(8 * scale))
    lines: list[str] = []
    current = ""
    for character in text:
        current += character
        if len(current) >= max_line_chars:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)

    max_line_pixels = max(
        draw.textbbox((0, 0), line, font=font)[2] for line in lines
    )
    bubble_width = min(
        max_line_pixels + padding * 2,
        round(video_width * 0.44),
    )
    bubble_height = len(lines) * line_height + padding * 2
    margin = round(18 * scale)
    bubble_x = video_width - bubble_width - margin
    bubble_y = margin
    border = max(2, round(3 * scale))
    tail_height = round(28 * scale)

    draw.rounded_rectangle(
        [
            bubble_x,
            bubble_y,
            bubble_x + bubble_width,
            bubble_y + bubble_height,
        ],
        radius=round(18 * scale),
        fill="white",
        outline="black",
        width=border,
    )
    tail_x = bubble_x + round(44 * scale)
    tail_y = bubble_y + bubble_height
    draw.polygon(
        [
            (tail_x, tail_y),
            (tail_x - round(14 * scale), tail_y + tail_height),
            (tail_x + round(28 * scale), tail_y),
        ],
        fill="white",
    )
    draw.line(
        [(tail_x, tail_y), (tail_x - round(14 * scale), tail_y + tail_height)],
        fill="black",
        width=border,
    )
    draw.line(
        [
            (tail_x - round(14 * scale), tail_y + tail_height),
            (tail_x + round(28 * scale), tail_y),
        ],
        fill="black",
        width=border,
    )
    for index, line in enumerate(lines):
        draw.text(
            (bubble_x + padding, bubble_y + padding + index * line_height),
            line,
            fill="#111111",
            font=font,
        )

    target_emoji_pixels = max(48, round(72 * scale))
    emoji_font_path = _find_emoji_font()
    try:
        bitmap_sizes = [160, 96, 64, 48, 40, 32, 20]
        render_size = next(
            (size for size in bitmap_sizes if size >= target_emoji_pixels),
            bitmap_sizes[0],
        )
        emoji_font = (
            ImageFont.truetype(emoji_font_path, render_size)
            if emoji_font_path
            else None
        )
        if emoji_font:
            cell = render_size + 4
            emoji_image = Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
            ImageDraw.Draw(emoji_image).text(
                (2, 2),
                _vibe_emoji(vibe),
                font=emoji_font,
                embedded_color=True,
            )
            scaled = emoji_image.resize(
                (target_emoji_pixels, target_emoji_pixels),
                Image.LANCZOS,
            )
            emoji_x = round(tail_x - 14 * scale)
            emoji_y = round(tail_y + tail_height + 8 * scale)
            image.paste(scaled, (emoji_x, emoji_y), scaled)
    except Exception:
        logger.debug("emoji font rendering unavailable", exc_info=True)

    try:
        image.save(output_path, "PNG")
        return True
    except Exception as exc:
        logger.warning("pet OS overlay save failed: %s", exc)
        return False


def _render_interview_summary_png(
    text: str,
    video_width: int,
    video_height: int,
    output_path: Path,
    location: Mapping[str, Any] | None = None,
) -> bool:
    if isinstance(location, Mapping):
        return _render_placed_text_box(
            text=text,
            video_width=video_width,
            video_height=video_height,
            output_path=output_path,
            location=location,
            bubble=False,
        )
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("PIL unavailable; interview summary overlay skipped")
        return False

    image = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    scale = video_width / 1280.0
    font_path = _find_cjk_font()
    font_size = max(22, round(34 * scale))
    if font_path:
        try:
            font = ImageFont.truetype(font_path, font_size)
        except Exception:
            font = ImageFont.load_default()
    else:
        font = ImageFont.load_default()

    display_text = text.replace("\n", " ").strip()
    padding_h = round(40 * scale)
    max_text_width = video_width - padding_h * 2

    actual_font = font
    actual_font_size = font_size
    while actual_font_size > 12:
        text_width = draw.textbbox((0, 0), display_text, font=actual_font)[2]
        if text_width <= max_text_width:
            break
        actual_font_size -= 1
        if font_path:
            actual_font = ImageFont.truetype(font_path, actual_font_size)
        else:
            actual_font = ImageFont.load_default()
    font = actual_font

    lines = [display_text]

    line_height = round(actual_font_size * 1.3)
    margin_top = round(video_height * 0.08)
    outline = max(2, round(3 * scale))
    for index, line in enumerate(lines):
        bounds = draw.textbbox((0, 0), line, font=font)
        width = bounds[2] - bounds[0]
        x = (video_width - width) // 2
        y = margin_top + index * line_height
        for offset_x in (-outline, 0, outline):
            for offset_y in (-outline, 0, outline):
                if offset_x or offset_y:
                    draw.text(
                        (x + offset_x, y + offset_y),
                        line,
                        fill="#000000",
                        font=font,
                    )
        draw.text((x, y), line, fill="#FFFFFF", font=font)

    try:
        image.save(output_path, "PNG")
        return True
    except Exception as exc:
        logger.warning("interview summary overlay save failed: %s", exc)
        return False


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
    """Render and composite a pet speech bubble over one prepared segment."""

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
