# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Shared utilities for file and shell tools."""

import re

import logging

import aiofiles

from ...constant import TRUNCATION_NOTICE_MARKER

logger = logging.getLogger(__name__)


# Default truncation limit
DEFAULT_MAX_BYTES = 50 * 1024

# Maximum file size to read into memory (1GB)
MAX_FILE_READ_BYTES = 1024 * 1024 * 1024


# pylint: disable=too-many-return-statements
def _truncate_fresh(
    text: str,
    start_line: int,
    total_lines: int,
    max_bytes: int,
    file_path: str | None,
    encoding: str,
) -> str:
    """Truncate fresh text (no prior truncation marker) by bytes with line integrity.

    Slices at the byte boundary and appends a truncation notice with a continuation
    hint so callers know which line to read next.

    Returns the original text unchanged when it fits within max_bytes, or when the
    last line itself exceeds max_bytes (unhandled edge case).
    """
    text_bytes = text.encode(encoding)

    # Under the byte limit — return as-is without any modification.
    if len(text_bytes) <= max_bytes:
        return text

    # Slice at the byte boundary.
    # Assuming every single line is shorter than DEFAULT_MAX_BYTES, this cut always
    # lands mid-line, guaranteeing at least one complete line before the boundary.
    # Lines that exceed DEFAULT_MAX_BYTES are not handled and may be skipped entirely.
    truncated = text_bytes[:max_bytes]
    # Decode back to str; errors="ignore" drops any split multi-byte character
    # at the cut boundary without raising an exception.
    result = truncated.decode(encoding, errors="ignore")

    # Count '\n' characters to determine how many complete lines are included.
    # The tail after the final '\n' is a partial line that will be covered by
    # the next read starting at next_line.
    newline_count = result.count("\n")

    # Compute the first line number not yet fully included in this chunk.
    # max(1, ...) prevents next_line from equaling start_line when a single line
    # exceeds max_bytes (newline_count == 0), which would make the caller retry
    # the same range indefinitely.
    next_line = start_line + max(1, newline_count)

    if next_line <= total_lines:
        # Truncation fell before the last line — continue reading from next_line.
        read_from = next_line
    elif start_line < total_lines:
        # next_line overshot total_lines, meaning the cut landed inside the last line.
        # Re-read from the start of the last line so the caller gets it in full.
        read_from = total_lines
    else:
        # start_line == total_lines: the last line itself exceeds DEFAULT_MAX_BYTES.
        # This case is outside our handled range — return without a truncation notice.
        return result

    notice = (
        TRUNCATION_NOTICE_MARKER + f"\nThe output above was truncated."
        f"\nThe full content is saved to the file and contains {total_lines} lines in total."
        f"\nThis excerpt starts at line {start_line} and covers the next {max_bytes} bytes."
        f"\nIf the current content is not enough, call `read_file` with file_path={file_path or ''} "
        f"start_line={read_from} to read more."
    )

    return result + notice


def _retruncate(
    text: str,
    max_bytes: int,
    encoding: str,
) -> str:
    """Re-truncate text that was previously truncated (contains TRUNCATION_NOTICE_MARKER).

    Extracts the original content before the marker, applies the new byte limit, and
    updates the embedded notice (byte count and continuation line number) via regex.

    Returns the original text unchanged when:
    - the content already fits within max_bytes (with a small slack);
    - required metadata fields cannot be parsed from the existing notice.
    """
    parts = text.split(TRUNCATION_NOTICE_MARKER, 1)
    original_content = parts[0]
    old_notice = parts[1]

    text_bytes = original_content.encode(encoding)

    # Allow a small slack to avoid unnecessary re-truncation when content is just
    # barely over the limit (e.g. due to minor encoding differences).
    if len(text_bytes) <= max_bytes + 100:
        return text

    # Parse start_line from notice; return text unchanged if not found
    start_match = re.search(r"starts at line (\d+)", old_notice)
    if not start_match:
        return text
    start_line_parsed = int(start_match.group(1))

    # Re-slice to the new byte limit.
    # Because every line is assumed to be shorter than DEFAULT_MAX_BYTES, the cut
    # always falls somewhere mid-line, so at least one complete line is preserved.
    truncated_bytes = text_bytes[:max_bytes]
    # errors="ignore" silently drops any incomplete multi-byte character at the cut boundary.
    result = truncated_bytes.decode(encoding, errors="ignore")
    # Each '\n' in result corresponds to one fully-included line;
    # anything after the last '\n' is a partial line that was cut off.
    newline_count = result.count("\n")

    # The next read should start at the line immediately after all complete lines.
    # max(1, ...) guards against the theoretical zero-newline case
    # (impossible when every line is shorter than DEFAULT_MAX_BYTES).
    next_line = start_line_parsed + max(1, newline_count)

    if not re.search(r"covers the next \d+ bytes", old_notice):
        return text
    # _truncate_fresh always includes a continuation hint, so both fields are always present.
    new_notice = re.sub(
        r"covers the next \d+ bytes",
        f"covers the next {max_bytes} bytes",
        old_notice,
    )
    new_notice = re.sub(
        r"start_line=\d+ to read more",
        f"start_line={next_line} to read more",
        new_notice,
    )

    return result + TRUNCATION_NOTICE_MARKER + new_notice


def truncate_text_output(
    text: str,
    start_line: int = 1,
    total_lines: int = 0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    file_path: str | None = None,
    encoding: str = "utf-8",
) -> str:
    """Truncate file output by bytes with line integrity.

    If text is under byte limit, return as-is.
    If over limit, truncate at the last complete line that fits,
    allowing the next read to start from a fresh line.

    Dispatches to :func:`_truncate_fresh` for text seen for the first time, or to
    :func:`_retruncate` when the text already contains a TRUNCATION_NOTICE_MARKER
    from a previous pass.

    Args:
        text: The output text to truncate.
        start_line: The starting line number (1-based). Ignored when text already
            contains a truncation notice (values are parsed from the notice instead).
        total_lines: Total lines in the original file. Ignored when text already
            contains a truncation notice (values are parsed from the notice instead).
        max_bytes: Maximum size in bytes.
        file_path: Optional file path to include in the truncation notice.
        encoding: Character encoding used for byte-length calculation and decoding.

    Returns:
        Truncated text with notice if truncated.
    """
    if not text:
        return text
    if max_bytes <= 0:
        return text

    try:
        if TRUNCATION_NOTICE_MARKER in text:
            return _retruncate(text, max_bytes=max_bytes, encoding=encoding)
        else:
            return _truncate_fresh(
                text,
                start_line=start_line,
                total_lines=total_lines,
                max_bytes=max_bytes,
                file_path=file_path,
                encoding=encoding,
            )
    except Exception:
        logger.warning(
            "truncate_text_output failed, returning original text",
            exc_info=True,
        )
        return text


async def read_file_safe(
    file_path: str,
    max_bytes: int = MAX_FILE_READ_BYTES,
) -> str:
    """Read file with Unicode error handling and memory protection.

    Args:
        file_path: Path to the file.
        max_bytes: Maximum bytes to read into memory (default 1GB).

    Returns:
        File content as string (up to max_bytes).
    """
    # Use utf-8-sig to auto-remove BOM if present, compatible with plain utf-8
    try:
        async with aiofiles.open(
            file_path,
            "r",
            encoding="utf-8-sig",
        ) as f:
            return await f.read(max_bytes)
    except UnicodeDecodeError:
        async with aiofiles.open(
            file_path,
            "r",
            encoding="utf-8-sig",
            errors="ignore",
        ) as f:
            return await f.read(max_bytes)
