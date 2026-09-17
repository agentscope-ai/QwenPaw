# -*- coding: utf-8 -*-
"""Deterministic text layout and PNG rendering."""

from __future__ import annotations

import base64
import hashlib
import re
import struct
import sys
import zlib
from array import array
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image

from ..config import (
    CANVAS_MAX_HEIGHT,
    CANVAS_PADDING,
    CANVAS_WIDTH,
    LOW_EFFORT_PRESET,
    ROLE_MARK_ASSISTANT,
    ROLE_MARK_USER,
    EffortPreset,
)


@dataclass(frozen=True)
class RenderedPage:
    """Immutable geometry and bytes returned by the renderer."""

    png: bytes
    width: int
    height: int
    dropped_chars: int = 0
    dropped_codepoints: dict[str, int] = field(default_factory=dict)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.png).hexdigest()


@dataclass(frozen=True)
class _DenseGrayAtlas:
    """Decoded grayscale glyph atlas."""

    ranks: dict[int, int]
    offsets: array
    wide_flags: bytes
    pixels: bytes
    cell_width: int
    cell_height: int


@dataclass(frozen=True)
class _RenderProfile:
    effort: str
    line_height: int
    cell_width: int
    width: int = CANVAS_WIDTH
    max_height: int = CANVAS_MAX_HEIGHT
    padding: int = CANVAS_PADDING


def _profile_for_preset(preset: EffortPreset) -> _RenderProfile:
    return _RenderProfile(
        effort=preset.effort,
        line_height=preset.line_height,
        cell_width=preset.cell_width,
    )


_ASSET_ROOT = Path(__file__).resolve().parent.parent / "assets"
_DENSE_ATLAS_PROFILES = {
    "low": (_ASSET_ROOT / "atlas-gray.ts", 5, 8),
    "medium": (_ASSET_ROOT / "atlas-gray-medium.ts", 4, 7),
    "high": (_ASSET_ROOT / "atlas-gray-high.ts", 3, 6),
}
_INVERT_BYTES = bytes.maketrans(bytes(range(256)), bytes(reversed(range(256))))
_COVERAGE_TO_ROLE_1 = bytes(
    0 if coverage == 0 else 1 for coverage in range(256)
)
_COVERAGE_TO_ROLE_2 = bytes(
    0 if coverage == 0 else 2 for coverage in range(256)
)
_ROLE_TO_MASK = {
    slot: bytes(255 if value == slot else 0 for value in range(256))
    for slot in (1, 2)
}
_ROLE_PALETTE = ((20, 120, 50), (30, 70, 180))


@lru_cache(maxsize=3)
def _load_gray_atlas(
    source_path: Path,
    cell_width: int,
    cell_height: int,
) -> _DenseGrayAtlas:
    """Decode the packaged glyph atlas."""
    source = source_path.read_text(encoding="utf-8")

    def blob(name: str) -> bytes:
        match = re.search(rf'const {name}_B64\s*=\s*"([^"]*)"', source)
        if match is None:
            raise ValueError(f"missing {name}_B64 in {source_path}")
        return base64.b64decode(match.group(1))

    codepoints = array("I")
    codepoints.frombytes(blob("GRAY_CODEPOINTS"))
    offsets = array("I")
    offsets.frombytes(blob("GRAY_OFFSETS"))
    if sys.byteorder != "little":
        codepoints.byteswap()
        offsets.byteswap()
    return _DenseGrayAtlas(
        ranks={codepoint: rank for rank, codepoint in enumerate(codepoints)},
        offsets=offsets,
        wide_flags=blob("GRAY_WIDE_FLAGS"),
        pixels=blob("GRAY_PIXELS"),
        cell_width=cell_width,
        cell_height=cell_height,
    )


def _load_dense_gray_atlas(effort: str = "low") -> _DenseGrayAtlas:
    """Load the frozen atlas for one effort profile."""
    try:
        source, cell_width, cell_height = _DENSE_ATLAS_PROFILES[effort]
    except KeyError as error:
        raise ValueError(f"unknown frozen atlas profile: {effort}") from error
    return _load_gray_atlas(source, cell_width, cell_height)


def _atlas_for_profile(profile: _RenderProfile) -> _DenseGrayAtlas:
    atlas = _load_dense_gray_atlas(profile.effort)
    if (
        atlas.cell_width != profile.cell_width
        or atlas.cell_height > profile.line_height
    ):
        raise ValueError(
            f"frozen atlas does not match {profile.effort} preset",
        )
    return atlas


@lru_cache(maxsize=4096)
def _dense_glyph_scanlines(
    rank: int,
    effort: str = "low",
) -> tuple[int, tuple[bytes, ...]]:
    """Return immutable pixel rows for one dense glyph."""
    atlas = _load_dense_gray_atlas(effort)
    cells = 2 if atlas.wide_flags[rank] == 1 else 1
    src_width = cells * atlas.cell_width
    src_offset = atlas.offsets[rank]
    pixel_rows: list[bytes] = []
    for glyph_y in range(atlas.cell_height):
        start = src_offset + glyph_y * src_width
        coverage = atlas.pixels[start : start + src_width]
        pixel_rows.append(coverage.translate(_INVERT_BYTES))
    return src_width, tuple(pixel_rows)


@lru_cache(maxsize=1024)
def _dense_glyph_role_scanlines(
    rank: int,
    role_slot: int,
    effort: str = "low",
) -> tuple[bytes, ...]:
    """Return sparse role-mask rows for one glyph."""
    if role_slot not in {1, 2}:
        raise ValueError(f"unknown role slot: {role_slot}")
    atlas = _load_dense_gray_atlas(effort)
    cells = 2 if atlas.wide_flags[rank] == 1 else 1
    src_width = cells * atlas.cell_width
    src_offset = atlas.offsets[rank]
    role_table = _COVERAGE_TO_ROLE_1 if role_slot == 1 else _COVERAGE_TO_ROLE_2
    return tuple(
        atlas.pixels[
            src_offset
            + glyph_y * src_width : src_offset
            + (glyph_y + 1) * src_width
        ].translate(role_table)
        for glyph_y in range(atlas.cell_height)
    )


@lru_cache(maxsize=4096)
def _char_cells(char: str) -> int:
    if not char:
        return 0
    atlas = _load_dense_gray_atlas()
    rank = atlas.ranks.get(ord(char))
    return 2 if rank is not None and atlas.wide_flags[rank] == 1 else 1


def _escape_missing_glyphs(
    line: str,
    *,
    preserve_role_markers: bool = False,
) -> str:
    """Escape atlas misses, preserving role markers only in ``slot_text``."""
    atlas = _load_dense_gray_atlas()
    out: list[str] | None = None
    for index, char in enumerate(line):
        codepoint = ord(char)
        is_role_marker = codepoint in {
            ord(ROLE_MARK_USER),
            ord(ROLE_MARK_ASSISTANT),
        }
        if codepoint not in atlas.ranks and not (
            preserve_role_markers and is_role_marker
        ):
            if out is None:
                out = list(line[:index])
            out.append(f"[U+{codepoint:X}]")
        elif out is not None:
            out.append(char)
    return line if out is None else "".join(out)


def _expand_tabs_visible(line: str) -> str:
    if "\t" not in line:
        return line
    out: list[str] = []
    col = 0
    for char in line:
        if char == "\t":
            span = 4 - (col % 4)
            out.append("→")
            if span > 1:
                out.append(" " * (span - 1))
            col += span
        else:
            out.append(char)
            col += _char_cells(char)
    return "".join(out)


def _wrap_line(
    line: str,
    max_cols: int,
    *,
    preserve_role_markers: bool = False,
) -> list[str]:
    if not line:
        return [""]
    out: list[str] = []
    current = ""
    used_cols = 0
    prepared = _escape_missing_glyphs(
        _expand_tabs_visible(line),
        preserve_role_markers=preserve_role_markers,
    )
    for char in prepared:
        cells = _char_cells(char)
        if used_cols + cells > max_cols:
            out.append(current)
            current = char
            used_cols = cells
        else:
            current += char
            used_cols += cells
    if current:
        out.append(current)
    return out


def _minify_for_render(text: str) -> str:
    stripped = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    return re.sub(r"\n{4,}", "\n\n\n", stripped)


def _visual_lines(
    text: str,
    profile: _RenderProfile,
    columns: int | None = None,
    *,
    preserve_role_markers: bool = False,
) -> list[str]:
    max_cols = columns or max(
        1,
        (profile.width - 2 * profile.padding) // profile.cell_width,
    )
    lines: list[str] = []
    for raw in _minify_for_render(text).split("\n"):
        lines.extend(
            _wrap_line(
                raw,
                max_cols,
                preserve_role_markers=preserve_role_markers,
            ),
        )
    return lines or [""]


def measure_content_columns(
    text: str,
    preset: EffortPreset = LOW_EFFORT_PRESET,
) -> int:
    """Return the widest prepared line, capped by the preset width."""
    profile = _profile_for_preset(preset)
    cap = max(
        1,
        (profile.width - 2 * profile.padding) // profile.cell_width,
    )
    widest = 1
    for raw in text.split("\n"):
        prepared = _escape_missing_glyphs(_expand_tabs_visible(raw))
        width = sum(_char_cells(char) for char in prepared)
        widest = max(widest, width)
        if widest >= cap:
            return cap
    return min(cap, widest)


def _profile_with_columns(
    profile: _RenderProfile,
    columns: int | None,
) -> tuple[_RenderProfile, int]:
    max_columns = max(
        1,
        (profile.width - 2 * profile.padding) // profile.cell_width,
    )
    if columns is None:
        return profile, max_columns
    actual_columns = max(1, min(max_columns, columns))
    width = 2 * profile.padding + actual_columns * profile.cell_width
    return replace(profile, width=width), actual_columns


def render_rows_per_page(
    preset: EffortPreset,
    columns: int,
) -> int:
    profile = _profile_for_preset(preset)
    hard_rows = max(
        1,
        (profile.max_height - 2 * profile.padding) // profile.line_height,
    )
    readable_rows = max(
        1,
        (preset.readable_chars_per_image + 1) // (max(1, int(columns)) + 1),
    )
    return min(hard_rows, readable_rows)


def _split_visual_pages(
    lines: list[str],
    max_lines: int,
    max_chars: int,
) -> list[list[str]]:
    """Apply the joint row-count and serialized-character page bounds."""
    pages: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    line_limit = max(1, max_lines)
    char_limit = max(1, max_chars)
    for line in lines:
        line_chars = len(line) + int(bool(current))
        if current and (
            len(current) >= line_limit
            or current_chars + line_chars > char_limit
        ):
            pages.append(current)
            current = []
            current_chars = 0
        current.append(line)
        current_chars += len(line) + int(len(current) > 1)
    if current:
        pages.append(current)
    return pages or [[]]


def _page_render_lines(
    page_lines: list[str],
    profile: _RenderProfile,
    columns: int,
    max_lines: int,
    *,
    preserve_role_markers: bool = False,
) -> list[str]:
    # Most pages are already fully laid out. Repeat layout only for edge cases
    # where whitespace or a forced one-column canvas changes the result.
    if (
        page_lines
        and columns >= 2
        and len(page_lines) <= max(1, max_lines)
        and all(not line.endswith((" ", "\t")) for line in page_lines)
    ):
        return page_lines
    chunk = "\n".join(page_lines)
    return _visual_lines(
        chunk,
        profile,
        columns,
        preserve_role_markers=preserve_role_markers,
    )[: max(1, max_lines)]


def reflow_for_render(text: str) -> str:
    """Compact text and preserve hard breaks with a visible glyph."""
    normalized = _minify_for_render(text).replace("↵", "⏎")
    return "↵".join(
        _expand_tabs_visible(line) for line in normalized.split("\n")
    )


def prepare_render_text(text: str) -> str:
    return reflow_for_render(text)


def page_count_for_text(
    text: str,
    preset: EffortPreset = LOW_EFFORT_PRESET,
    *,
    columns: int | None = None,
) -> int:
    profile = _profile_for_preset(preset)
    profile, actual_columns = _profile_with_columns(profile, columns)
    per_page = render_rows_per_page(
        preset,
        actual_columns,
    )
    return len(
        _split_visual_pages(
            _visual_lines(text, profile, actual_columns),
            per_page,
            preset.readable_chars_per_image,
        ),
    )


def estimate_text_pages(
    text: str,
    preset: EffortPreset = LOW_EFFORT_PRESET,
    *,
    columns: int | None = None,
) -> list[RenderedPage]:
    """Return geometry-only pages for a gate without rasterizing PNG bytes."""
    profile = _profile_for_preset(preset)
    profile, actual_columns = _profile_with_columns(profile, columns)
    lines = _visual_lines(text, profile, actual_columns)
    per_page = render_rows_per_page(
        preset,
        actual_columns,
    )
    pages: list[RenderedPage] = []
    for page_lines in _split_visual_pages(
        lines,
        per_page,
        preset.readable_chars_per_image,
    ):
        rendered_lines = _page_render_lines(
            page_lines,
            profile,
            actual_columns,
            per_page,
        )
        count = len(rendered_lines)
        height = max(
            profile.padding * 2 + profile.line_height,
            profile.padding * 2 + count * profile.line_height,
        )
        pages.append(
            RenderedPage(
                png=b"",
                width=profile.width,
                height=height,
            ),
        )
    return pages


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return (
        struct.pack(">I", len(data))
        + payload
        + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
    )


def _encode_png(
    pixels: bytes,
    width: int,
    height: int,
    *,
    channels: int,
) -> bytes:
    """Encode a deterministic PNG with fixed filters and compression."""
    if len(pixels) != width * height * channels:
        raise ValueError("invalid framebuffer length")
    stride = width * channels
    raw = b"".join(
        b"\x00" + pixels[row * stride : (row + 1) * stride]
        for row in range(height)
    )
    color_type = 0 if channels == 1 else 2
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", zlib.compress(raw, level=6)),
            _png_chunk(b"IEND", b""),
        ),
    )


def _encode_gray_png(pixels: bytes, width: int, height: int) -> bytes:
    return _encode_png(pixels, width, height, channels=1)


def _encode_rgb_png(pixels: bytes, width: int, height: int) -> bytes:
    return _encode_png(pixels, width, height, channels=3)


@lru_cache(maxsize=6)
def _role_blend_lut(channel: int) -> bytes:
    """Map grayscale coverage to one role-color channel."""
    return bytes(
        255 - ((255 - gray) * (255 - channel) + 127) // 255
        for gray in range(256)
    )


def _role_colored_image(
    framebuffer: bytearray,
    role_mask: bytearray,
    width: int,
    height: int,
) -> Image.Image | None:
    """Apply role colors only where the matching glyph mask is present."""
    present_slots = [slot for slot in (1, 2) if role_mask.count(slot) > 0]
    if not present_slots:
        return None

    size = (width, height)
    gray = Image.frombytes("L", size, bytes(framebuffer))
    channels = [gray.copy(), gray.copy(), gray.copy()]
    role_bytes = bytes(role_mask)
    for slot in present_slots:
        mask = Image.frombytes(
            "L",
            size,
            role_bytes.translate(_ROLE_TO_MASK[slot]),
        )
        color = _ROLE_PALETTE[slot - 1]
        for channel_index, channel in enumerate(color):
            colored = gray.point(_role_blend_lut(channel))
            channels[channel_index].paste(colored, mask=mask)
    return Image.merge("RGB", tuple(channels))


def _render_dense_atlas_page(  # pylint: disable=R0912,R0915,R1702
    lines: list[str],
    profile: _RenderProfile,
    slot_lines: list[str] | None = None,
) -> tuple[Image.Image, int, dict[str, int]]:
    """Render one page with the selected frozen grayscale atlas."""
    atlas = _atlas_for_profile(profile)
    height = max(
        profile.padding * 2 + profile.line_height,
        profile.padding * 2 + len(lines) * profile.line_height,
    )
    framebuffer = bytearray(b"\xff") * (profile.width * height)
    role_mask = (
        bytearray(profile.width * height) if slot_lines is not None else None
    )
    dropped = 0
    dropped_codepoints: dict[str, int] = {}
    scanline_blit_safe = True
    for row, line in enumerate(lines):
        slot_line = (
            slot_lines[row] if slot_lines and row < len(slot_lines) else ""
        )
        col = 0
        base_y = profile.padding + row * profile.line_height
        for char_index, char in enumerate(line):
            codepoint = ord(char)
            rank = atlas.ranks.get(codepoint)
            if rank is None:
                dropped += 1
                key = f"U+{codepoint:04X}"
                dropped_codepoints[key] = dropped_codepoints.get(key, 0) + 1
                col += _char_cells(char)
                continue
            wide = atlas.wide_flags[rank] == 1
            cells = 2 if wide else 1
            src_width = cells * atlas.cell_width
            src_offset = atlas.offsets[rank]
            base_x = profile.padding + col * profile.cell_width
            role_slot = 0
            if role_mask is not None and char_index < len(slot_line):
                mark = slot_line[char_index]
                if mark == ROLE_MARK_USER:
                    role_slot = 1
                elif mark == ROLE_MARK_ASSISTANT:
                    role_slot = 2
            can_blit_scanlines = (
                scanline_blit_safe
                and profile.cell_width >= atlas.cell_width
                and atlas.cell_height <= profile.line_height
                and base_y >= 0
                and (base_y + atlas.cell_height <= height)
                and base_x >= 0
                and base_x + src_width <= profile.width
            )
            if can_blit_scanlines:
                cached_width, pixel_rows = _dense_glyph_scanlines(
                    rank,
                    profile.effort,
                )
                if cached_width != src_width:
                    raise AssertionError("dense glyph width cache mismatch")
                role_rows: tuple[bytes, ...] = (
                    _dense_glyph_role_scanlines(
                        rank,
                        role_slot,
                        profile.effort,
                    )
                    if role_slot
                    else ()
                )
                for glyph_y, pixel_row in enumerate(pixel_rows):
                    dst = (base_y + glyph_y) * profile.width + base_x
                    framebuffer[dst : dst + src_width] = pixel_row
                    if role_mask is not None and role_rows:
                        role_mask[dst : dst + src_width] = role_rows[glyph_y]
            else:
                # A forced narrow canvas can spill into a later scanline.
                # Keep subsequent glyphs on the min-blending path.
                scanline_blit_safe = False
                for glyph_y in range(atlas.cell_height):
                    dst = (base_y + glyph_y) * profile.width + base_x
                    src = src_offset + glyph_y * src_width
                    for glyph_x in range(src_width):
                        coverage = atlas.pixels[src + glyph_x]
                        if coverage:
                            pixel = 255 - coverage
                            index = dst + glyph_x
                            if index >= len(framebuffer):
                                continue
                            if pixel < framebuffer[index]:
                                framebuffer[index] = pixel
                            if role_mask is not None and role_slot:
                                role_mask[index] = role_slot
            col += cells
    image = (
        _role_colored_image(
            framebuffer,
            role_mask,
            profile.width,
            height,
        )
        if role_mask is not None
        else None
    )
    if image is None:
        image = Image.frombytes(
            "L",
            (profile.width, height),
            bytes(framebuffer),
        )
    return (
        image,
        dropped,
        dropped_codepoints,
    )


def _render_text_pages_uncached(  # pylint: disable=R0912
    text: str,
    preset: EffortPreset = LOW_EFFORT_PRESET,
    max_pages: int | None = None,
    slot_text: str | None = None,
    columns: int | None = None,
) -> list[RenderedPage]:
    """Render text into deterministic, content-height PNG pages."""
    profile = _profile_for_preset(preset)
    profile, actual_columns = _profile_with_columns(profile, columns)
    lines = _visual_lines(text, profile, actual_columns)
    slot_lines = (
        _visual_lines(
            slot_text,
            profile,
            actual_columns,
            preserve_role_markers=True,
        )
        if slot_text is not None
        else None
    )
    if slot_lines is not None and len(slot_lines) != len(lines):
        slot_lines = None
    per_page = render_rows_per_page(
        preset,
        actual_columns,
    )
    laid_out_pages = _split_visual_pages(
        lines,
        per_page,
        preset.readable_chars_per_image,
    )
    page_count = len(laid_out_pages)
    if max_pages is not None:
        # Never remove original text unless every rendered row fits. A page
        # cap is a pass-through gate, not a truncation mechanism.
        if page_count > max(0, max_pages):
            return []
    pages: list[RenderedPage] = []
    line_cursor = 0
    for chunk in laid_out_pages:
        initial_slot_chunk = (
            slot_lines[line_cursor : line_cursor + len(chunk)]
            if slot_lines is not None
            else None
        )
        line_cursor += len(chunk)
        render_lines = _page_render_lines(
            chunk,
            profile,
            actual_columns,
            per_page,
        )
        slot_chunk = (
            _page_render_lines(
                initial_slot_chunk,
                profile,
                actual_columns,
                per_page,
                preserve_role_markers=True,
            )
            if initial_slot_chunk is not None
            else None
        )
        if slot_chunk is not None and len(slot_chunk) != len(render_lines):
            slot_chunk = None
        height = max(
            profile.padding * 2 + profile.line_height,
            profile.padding * 2 + len(render_lines) * profile.line_height,
        )
        (
            image,
            dropped_chars,
            dropped_codepoints,
        ) = _render_dense_atlas_page(
            render_lines,
            profile,
            slot_chunk,
        )
        if dropped_chars:
            missing = ", ".join(sorted(dropped_codepoints))
            raise RuntimeError(
                "frozen atlas dropped characters after preprocessing: "
                f"{missing}",
            )
        png = (
            _encode_rgb_png(image.tobytes(), profile.width, height)
            if image.mode == "RGB"
            else _encode_gray_png(image.tobytes(), profile.width, height)
        )
        pages.append(
            RenderedPage(
                png=png,
                width=profile.width,
                height=height,
                dropped_chars=dropped_chars,
                dropped_codepoints=dropped_codepoints,
            ),
        )
    return pages


@lru_cache(maxsize=64)
def _cached_render_text_pages(
    text: str,
    preset: EffortPreset,
    max_pages: int | None,
    slot_text: str | None,
    columns: int | None,
) -> tuple[RenderedPage, ...]:
    return tuple(
        _render_text_pages_uncached(
            text,
            preset,
            max_pages,
            slot_text,
            columns,
        ),
    )


def render_text_pages(
    text: str,
    preset: EffortPreset = LOW_EFFORT_PRESET,
    max_pages: int | None = None,
    slot_text: str | None = None,
    *,
    columns: int | None = None,
) -> list[RenderedPage]:
    """Render through a bounded cross-request cache of immutable PNG pages."""
    return list(
        _cached_render_text_pages(
            text,
            preset,
            max_pages,
            slot_text,
            columns,
        ),
    )


def render_cache_info() -> Any:
    """Return the process-local rendered-page cache counters."""
    # Pylint mistakes the lru wrapper helper for the wrapped render function.
    return _cached_render_text_pages.cache_info()  # pylint: disable=E1120
