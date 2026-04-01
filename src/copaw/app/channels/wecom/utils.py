# -*- coding: utf-8 -*-
"""WeCom channel utilities."""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

# WeCom image upload limit (2MB), use 1.9MB as safe threshold
_WECOM_IMAGE_MAX_SIZE = 1.9 * 1024 * 1024  # 1.9 MB


def format_markdown_tables(text: str) -> str:
    """Format GFM markdown tables for WeCom compatibility.

    WeCom requires table columns to be properly aligned.
    This function normalizes table formatting.

    Args:
        text: Input markdown text possibly containing tables.

    Returns:
        Text with formatted tables.
    """
    lines = text.split("\n")
    result: List[str] = []
    i = 0
    in_code_fence = False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # Track fenced code blocks (```), pass through inside lines unchanged.
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            result.append(line)
            i += 1
            continue
        if in_code_fence:
            result.append(line)
            i += 1
            continue
        # Detect table start (line with |) when not inside a code fence
        if "|" in line:
            # Collect table lines
            table_lines: List[str] = []
            while (
                i < len(lines)
                and "|" in lines[i]
                and not lines[i].strip().startswith("```")
            ):
                table_lines.append(lines[i])
                i += 1
            # Format and add table
            if table_lines:
                result.extend(_format_table(table_lines))
            continue
        result.append(line)
        i += 1
    return "\n".join(result)


def _format_table(lines: List[str]) -> List[str]:
    """Format a single markdown table."""
    if not lines:
        return lines

    # Check if second row is separator (contains only -, :, |, spaces)
    sep_pattern = re.compile(r"^[\s\-:|]+$")
    has_separator = len(lines) >= 2 and sep_pattern.match(lines[1]) is not None

    # Parse cells, skipping the separator row (it will be rebuilt)
    rows: List[List[str]] = []
    for idx, line in enumerate(lines):
        if has_separator and idx == 1:
            continue  # Skip separator row; rebuild it from column widths
        cells = [c.strip() for c in line.split("|")]
        # Remove empty first/last cells from leading/trailing |
        if cells and not cells[0]:
            cells = cells[1:]
        if cells and not cells[-1]:
            cells = cells[:-1]
        if cells:
            rows.append(cells)

    if not rows:
        return lines

    # Calculate column widths
    col_count = max(len(r) for r in rows)
    widths: List[int] = [0] * col_count
    for row in rows:
        for j in range(col_count):
            cell = row[j] if j < len(row) else ""
            widths[j] = max(widths[j], len(cell))

    # Format rows with proper padding, inserting separator after header
    formatted: List[str] = []
    for idx, row in enumerate(rows):
        padded = [
            (row[j] if j < len(row) else "").ljust(widths[j])
            for j in range(col_count)
        ]
        formatted.append("| " + " | ".join(padded) + " |")
        if idx == 0:
            sep = (
                "| "
                + " | ".join("-" * max(3, widths[j]) for j in range(col_count))
                + " |"
            )
            formatted.append(sep)

    return formatted


def compress_image_for_wecom(
    image_path: str,
    max_size: float = _WECOM_IMAGE_MAX_SIZE,
) -> Tuple[bytes, str]:
    """Compress image to fit WeCom upload size limit.

    Strategy:
    1. Convert PNG/other formats to JPEG (usually much smaller)
    2. Progressively reduce JPEG quality if still too large
    3. Resize image if quality reduction is not enough

    Args:
        image_path: Path to the image file.
        max_size: Maximum file size in bytes (default 1.9MB).

    Returns:
        Tuple of (compressed image bytes, new filename).
        Returns original bytes if already under limit or compression fails.
    """
    path = Path(image_path)
    try:
        from PIL import Image
    except ImportError:
        logger.warning("PIL not available, skipping image compression")
        return path.read_bytes(), path.name

    original_data = path.read_bytes()
    original_size = len(original_data)

    # If already under limit, return as-is
    if original_size <= max_size:
        return original_data, path.name

    logger.info(
        "wecom compress_image: original size %.2fMB > limit %.2fMB",
        original_size / 1024 / 1024,
        max_size / 1024 / 1024,
    )

    try:
        img = Image.open(io.BytesIO(original_data))

        # Convert to RGB if necessary (PNG with transparency, etc.)
        if img.mode in ("RGBA", "LA", "P"):
            # Create white background for transparent images
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(
                img,
                mask=img.split()[-1] if "A" in img.mode else None,
            )
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        new_filename = path.stem + ".jpg"

        # Try different quality levels
        for quality in (85, 70, 50, 30):
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
            if len(data) <= max_size:
                logger.info(
                    "wecom compress_image: compressed to %.2fMB (quality=%d)",
                    len(data) / 1024 / 1024,
                    quality,
                )
                return data, new_filename

        # If still too large, resize the image
        width, height = img.size
        for scale in (0.75, 0.5, 0.25):
            new_width = int(width * scale)
            new_height = int(height * scale)
            resized = img.resize(
                (new_width, new_height),
                Image.Resampling.LANCZOS,
            )
            buffer = io.BytesIO()
            resized.save(buffer, format="JPEG", quality=70, optimize=True)
            data = buffer.getvalue()
            if len(data) <= max_size:
                logger.info(
                    "wecom compress_image: resized to %dx%d, %.2fMB",
                    new_width,
                    new_height,
                    len(data) / 1024 / 1024,
                )
                return data, new_filename

        # Return the smallest we got
        logger.warning(
            "wecom compress_image: could not compress below limit, "
            "returning smallest version (%.2fMB)",
            len(data) / 1024 / 1024,
        )
        return data, new_filename

    except Exception:
        logger.exception("wecom compress_image failed, using original")
        return original_data, path.name