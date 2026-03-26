# -*- coding: utf-8 -*-
"""Shared utilities for file and shell tools."""

import re

import logging

from ...constant import TRUNCATION_NOTICE_MARKER

logger = logging.getLogger(__name__)


# Default truncation limit
DEFAULT_MAX_BYTES = 50 * 1024

# Maximum file size to read into memory (1GB)
MAX_FILE_READ_BYTES = 1024 * 1024 * 1024


# pylint: disable=too-many-return-statements
def truncate_text_output(
    text: str,
    start_line: int = 1,
    total_lines: int = 0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    file_path: str | None = None,
) -> str:
    """Truncate file output by bytes with line integrity.

    If text is under byte limit, return as-is.
    If over limit, truncate at the last complete line that fits,
    allowing the next read to start from a fresh line.

    If TRUNCATION_NOTICE_MARKER is already in text (previously truncated),
    extract the original content, re-truncate it, and update the
    truncation notice using regex.

    Args:
        text: The output text to truncate.
        start_line: The starting line number (1-based). Ignored when
            text already contains a truncation notice (values are
            parsed from the notice instead).
        total_lines: Total lines in the original file. Ignored when
            text already contains a truncation notice (values are
            parsed from the notice instead).
        max_bytes: Maximum size in bytes.
        file_path: Optional file path to include in the truncation notice.

    Returns:
        Truncated text with notice if truncated.
    """
    if not text:
        return text
    if max_bytes <= 0:
        return text

    try:
        if TRUNCATION_NOTICE_MARKER in text:
            parts = text.split(TRUNCATION_NOTICE_MARKER, 1)
            original_content = parts[0]
            old_notice = parts[1]

            text_bytes = original_content.encode("utf-8")

            # Allow a small slack to avoid re-truncating near-limit content
            if len(text_bytes) <= max_bytes + 100:
                return text

            # Parse start_line and total_lines from notice; return text
            # unchanged if not found
            start_match = re.search(
                r"Starting at start_line=(\d+)",
                old_notice,
            )
            total_match = re.search(r"Total lines: (\d+)", old_notice)
            if not start_match or not total_match:
                return text
            start_line_parsed = int(start_match.group(1))
            total_lines_parsed = int(total_match.group(1))

            truncated_bytes = text_bytes[:max_bytes]
            result = truncated_bytes.decode("utf-8", errors="ignore")
            newline_count = result.count("\n")

            next_line = start_line_parsed + max(1, newline_count)

            if not re.search(r"next \d+ bytes", old_notice):
                return text
            has_continuation = bool(
                re.search(r"Use start_line=\d+", old_notice),
            )
            new_notice = re.sub(
                r"next \d+ bytes",
                f"next {max_bytes} bytes",
                old_notice,
            )
            if has_continuation:
                new_notice = re.sub(
                    r"Use start_line=\d+",
                    f"Use start_line={next_line}",
                    new_notice,
                )
            elif next_line <= total_lines_parsed:
                new_notice = re.sub(
                    r"(Total lines: \d+)",
                    f"\\1\nUse start_line={next_line} to continue.",
                    new_notice,
                )

            return result + TRUNCATION_NOTICE_MARKER + new_notice

        else:
            text_bytes = text.encode("utf-8")

            if len(text_bytes) <= max_bytes:
                return text

            truncated = text_bytes[:max_bytes]
            result = truncated.decode("utf-8", errors="ignore")

            newline_count = result.count("\n")

            next_line = start_line + max(1, newline_count)

            continuation = (
                f"\nUse start_line={next_line} to continue."
                if next_line <= total_lines
                else ""
            )
            notice = (
                TRUNCATION_NOTICE_MARKER + f"\nFile: {file_path or ''}"
                f"\nStarting at start_line={start_line},"
                f" next {max_bytes} bytes."
                f"\nTotal lines: {total_lines}{continuation}"
            )

            return result + notice

    except Exception:
        logger.warning(
            "truncate_text_output failed, returning original text",
            exc_info=True,
        )
        return text


def read_file_safe(
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
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read(max_bytes)
    except UnicodeDecodeError:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(max_bytes)
