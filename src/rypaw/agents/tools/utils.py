# -*- coding: utf-8 -*-
"""Shared utilities for file and shell tools."""

# Default truncation limits
DEFAULT_MAX_LINES = 1000
DEFAULT_MAX_BYTES = 30 * 1024  # 30KB


# pylint: disable=too-many-branches
def truncate_output(
    text: str,
    max_lines: int = DEFAULT_MAX_LINES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    keep: str = "head",
) -> tuple[str, bool, int, str]:
    """Smart truncation for large content.

    Args:
        text: Text content to truncate.
        max_lines: Maximum number of lines.
        max_bytes: Maximum size in bytes.
        keep: Which part to keep - "head" (first lines) or "tail" (last lines).

    Returns:
        (truncated_content, was_truncated, output_line_count, truncate_reason)
    """
    if not text:
        return text, False, 0, ""

    lines = text.split("\n")
    total_lines = len(lines)

    # No truncation needed
    if total_lines <= max_lines and len(text.encode("utf-8")) <= max_bytes:
        return text, False, total_lines, ""

    # Apply line limit
    if total_lines > max_lines:
        if keep == "tail":
            lines = lines[-max_lines:]
        else:
            lines = lines[:max_lines]
        reason = "lines"
    else:
        reason = ""

    # Apply byte limit
    if len("\n".join(lines).encode("utf-8")) > max_bytes:
        if keep == "tail":
            while (
                len(lines) > 1
                and len("\n".join(lines).encode("utf-8")) > max_bytes
            ):
                lines.pop(0)
            # Handle single line exceeding byte limit
            if lines and len(lines[0].encode("utf-8")) > max_bytes:
                lines[0] = _truncate_line_by_bytes_tail(lines[0], max_bytes)
        else:
            truncated = []
            current_bytes = 0
            for line in lines:
                line_bytes = len(line.encode("utf-8")) + 1
                if current_bytes + line_bytes > max_bytes:
                    # Truncate single line at byte level if it's the first line
                    if not truncated:
                        remaining = max_bytes - current_bytes
                        truncated.append(
                            _truncate_line_by_bytes(line, remaining),
                        )
                    break
                truncated.append(line)
                current_bytes += line_bytes
            lines = truncated
        reason = "bytes"

    return "\n".join(lines), True, len(lines), reason


def _truncate_line_by_bytes(line: str, max_bytes: int) -> str:
    """Truncate a single line to fit within byte limit (keep head).

    Handles UTF-8 multi-byte characters safely.

    Args:
        line: The line to truncate.
        max_bytes: Maximum bytes allowed.

    Returns:
        Truncated line that fits within byte limit.
    """
    if len(line.encode("utf-8")) <= max_bytes:
        return line

    # Binary search for the right character position
    low, high = 0, len(line)
    while low < high:
        mid = (low + high + 1) // 2
        if len(line[:mid].encode("utf-8")) <= max_bytes:
            low = mid
        else:
            high = mid - 1

    return line[:low]


def _truncate_line_by_bytes_tail(line: str, max_bytes: int) -> str:
    """Truncate a single line to fit within byte limit (keep tail).

    Handles UTF-8 multi-byte characters safely.

    Args:
        line: The line to truncate.
        max_bytes: Maximum bytes allowed.

    Returns:
        Truncated line that fits within byte limit, keeping the tail.
    """
    if len(line.encode("utf-8")) <= max_bytes:
        return line

    # Binary search for the right character position from the end
    low, high = 0, len(line)
    while low < high:
        mid = (low + high) // 2
        if len(line[mid:].encode("utf-8")) <= max_bytes:
            high = mid
        else:
            low = mid + 1

    return line[low:]


def truncate_file_output(
    text: str,
    start_line: int = 1,
    total_lines: int = 0,
) -> str:
    """Truncate file output to first N lines or M bytes.

    Includes a truncation notice with continuation hint when applied.

    Args:
        text: The output text to truncate.
        start_line: The starting line number (1-based).
        total_lines: Total lines in the original file.

    Returns:
        Truncated text with notice if truncated.
    """
    if not text:
        return text

    try:
        truncated, was_truncated, output_lines, reason = truncate_output(
            text,
            keep="head",
        )

        if not was_truncated:
            return text

        end_line = start_line + output_lines - 1
        next_line = end_line + 1

        if reason == "lines":
            notice = (
                f"\n\n[Output truncated: showing lines "
                f"{start_line}-{end_line} of {total_lines} total. "
                f"Use start_line={next_line} to continue.]"
            )
        else:
            notice = (
                f"\n\n[Output truncated: showing lines "
                f"{start_line}-{end_line} of {total_lines} "
                f"({DEFAULT_MAX_BYTES // 1024}KB limit). "
                f"Use start_line={next_line} to continue.]"
            )

        return truncated + notice
    except Exception:
        return text


def truncate_shell_output(text: str) -> str:
    """Truncate shell output to last N lines or M bytes.

    Includes a truncation notice when applied.

    Args:
        text: The output text to truncate.

    Returns:
        Truncated text with notice if truncated.
    """
    if not text:
        return text

    try:
        total_lines = len(text.split("\n"))
        truncated, was_truncated, output_lines, reason = truncate_output(
            text,
            keep="tail",
        )

        if not was_truncated:
            return text

        start_line = total_lines - output_lines + 1
        if reason == "lines":
            notice = (
                "\n\n[Output truncated: showing lines "
                f"{start_line}-{total_lines} of {total_lines} total]"
            )
        else:
            notice = (
                "\n\n[Output truncated: showing lines "
                f"{start_line}-{total_lines} of {total_lines} "
                f"({DEFAULT_MAX_BYTES // 1024}KB limit)]"
            )

        return truncated + notice
    except Exception:
        return text


def read_file_safe(file_path: str) -> str:
    """Read file with Unicode error handling.

    Args:
        file_path: Path to the file.

    Returns:
        File content as string.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
