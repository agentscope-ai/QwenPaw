# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
import os
from pathlib import Path
from typing import Optional

import aiofiles
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from .utils import (
    truncate_text_output,
    read_file_safe,
    DEFAULT_MAX_BYTES,
)
from ...config.context import (
    get_current_workspace_dir,
    get_current_recent_max_bytes,
)
from ...constant import WORKING_DIR, TRUNCATION_NOTICE_MARKER

STREAMING_READ_CHUNK_BYTES = 64 * 1024
STREAMING_READ_MIN_BYTES = 8 * 1024 * 1024


def _resolve_file_path(file_path: str) -> str:
    """Resolve file path: use absolute path as-is,
    resolve relative path from current workspace or WORKING_DIR.

    Args:
        file_path: The input file path (absolute or relative).

    Returns:
        The resolved absolute file path as string.
    """
    path = Path(file_path).expanduser()
    if path.is_absolute():
        return str(path)
    else:
        # Use current workspace_dir from context, fallback to WORKING_DIR
        workspace_dir = get_current_workspace_dir() or WORKING_DIR
        return str(workspace_dir / file_path)


def _get_encoding_for_file(file_path: str) -> str:
    """Determine the appropriate encoding for a file based on its type.

    For cross-platform compatibility, especially with Windows Excel/Notepad:
    - CSV/TSV/TXT files: Use UTF-8-BOM (Windows Excel needs BOM to detect UTF-8)
    - All other files: Use UTF-8 (safer default, no BOM)

    Args:
        file_path: Path to the file

    Returns:
        Encoding string: "utf-8-sig" or "utf-8"
    """
    suffix = Path(file_path).suffix.lower()

    # Files that need BOM for Windows compatibility
    if suffix in {".csv", ".tsv", ".tab", ".txt", ".log"}:
        return "utf-8-sig"

    # Default: UTF-8 without BOM (safe for all other files)
    # This includes: .sh, .yaml, .json, .py, .js, .md, etc.
    return "utf-8"


def _should_stream_read(file_path: str, max_bytes: int) -> bool:
    """Return whether read_file should avoid loading the whole file."""
    try:
        file_size = os.path.getsize(file_path)
    except OSError:
        return False
    return file_size > max(max_bytes * 4, STREAMING_READ_MIN_BYTES)


def _decode_bytes(data: bytes, encoding: str) -> str:
    """Decode bytes for tool output without failing on mixed encodings."""
    return data.decode(encoding, errors="ignore")


def _build_streaming_notice(
    *,
    file_path: str,
    start_line: int,
    read_from: int,
    content_bytes: int,
    file_size: int,
    total_lines: int | None = None,
) -> str:
    """Build a truncation notice for streamed reads."""
    if total_lines is None:
        size_note = (
            f"The file is {file_size} bytes, so the total line count was not "
            "scanned before truncating this excerpt."
        )
    else:
        size_note = (
            "The full content is saved to the file "
            f"and contains {total_lines} lines in total."
        )

    return (
        TRUNCATION_NOTICE_MARKER + "\nThe output above was truncated."
        f"\n{size_note}"
        f"\nThis excerpt starts at line {start_line} and "
        f"covers the next {content_bytes} bytes."
        "\nIf the current content is not enough, "
        f"call `read_file` with file_path={file_path} "
        f"start_line={read_from} to read more."
    )


async def _read_file_streaming(  # pylint: disable=too-many-branches
    file_path: str,
    start_line: int,
    end_line: int | None,
    max_bytes: int,
) -> str:
    """Read large files without holding the full content in memory."""
    encoding = _get_encoding_for_file(file_path)
    file_size = os.path.getsize(file_path)
    selected = bytearray()
    current_line = 1
    saw_bytes = False
    truncated = False
    range_has_more = False

    async with aiofiles.open(file_path, "rb") as file:
        while True:
            chunk = await file.read(STREAMING_READ_CHUNK_BYTES)
            if not chunk:
                break

            saw_bytes = True
            parts = chunk.splitlines(keepends=True)
            for index, part in enumerate(parts):
                if end_line is not None and current_line > end_line:
                    range_has_more = True
                    break

                in_range = current_line >= start_line
                if in_range:
                    remaining = max_bytes - len(selected)
                    if remaining <= 0:
                        truncated = True
                        break

                    if len(part) > remaining:
                        selected.extend(part[:remaining])
                        truncated = True
                        break

                    selected.extend(part)

                if part.endswith((b"\n", b"\r")):
                    current_line += 1

                if (
                    end_line is not None
                    and current_line > end_line
                    and index < len(parts) - 1
                ):
                    range_has_more = True
                    break

            if truncated or range_has_more:
                break

    total_lines = current_line if saw_bytes else 1
    if start_line > total_lines:
        return f"Error: start_line {start_line} exceeds file length ({total_lines} lines)."

    text = _decode_bytes(bytes(selected), encoding)
    if not truncated and not range_has_more:
        return text

    if range_has_more:
        read_from = (end_line or current_line) + 1
    else:
        read_from = current_line
        if read_from <= start_line:
            read_from = start_line + 1

    notice = _build_streaming_notice(
        file_path=file_path,
        start_line=start_line,
        read_from=read_from,
        content_bytes=len(selected),
        file_size=file_size,
        total_lines=None,
    )
    return text + notice


async def read_file(  # pylint: disable=too-many-return-statements
    file_path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> ToolResponse:
    """Read a file. Relative paths resolve from WORKING_DIR.

    Use start_line/end_line to read a specific line range (output includes
    line numbers). Omit both to read the full file.

    Args:
        file_path (`str`):
            Path to the file.
        start_line (`int`, optional):
            First line to read (1-based, inclusive).
        end_line (`int`, optional):
            Last line to read (1-based, inclusive).
    """

    # Convert start_line/end_line to int if they are strings
    if start_line is not None:
        try:
            start_line = int(start_line)
        except (ValueError, TypeError):
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: start_line must be an integer, got {start_line!r}.",
                    ),
                ],
            )

    if end_line is not None:
        try:
            end_line = int(end_line)
        except (ValueError, TypeError):
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: end_line must be an integer, got {end_line!r}.",
                    ),
                ],
            )

    file_path = _resolve_file_path(file_path)

    if not os.path.exists(file_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The file {file_path} does not exist.",
                ),
            ],
        )

    if not os.path.isfile(file_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The path {file_path} is not a file.",
                ),
            ],
        )

    try:
        max_bytes = get_current_recent_max_bytes() or DEFAULT_MAX_BYTES
        s = max(1, start_line if start_line is not None else 1)

        if end_line is not None and s > end_line:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: start_line ({s}) > end_line ({end_line}).",
                    ),
                ],
            )

        if _should_stream_read(file_path, max_bytes):
            text = await _read_file_streaming(
                file_path=file_path,
                start_line=s,
                end_line=end_line,
                max_bytes=max_bytes,
            )
            return ToolResponse(
                content=[TextBlock(type="text", text=text)],
            )

        content = await read_file_safe(file_path)
        all_lines = content.split("\n")
        total = len(all_lines)

        # Determine read range
        e = min(total, end_line if end_line is not None else total)

        if s > total:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: start_line {s} exceeds file length ({total} lines).",
                    ),
                ],
            )

        if s > e:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: start_line ({s}) > end_line ({e}).",
                    ),
                ],
            )

        # Extract selected lines
        selected_content = "\n".join(all_lines[s - 1 : e])

        # Apply smart truncation (consistent with shell output format)
        text = truncate_text_output(
            selected_content,
            start_line=s,
            total_lines=total,
            file_path=file_path,
            max_bytes=max_bytes,
        )

        # Add continuation hint if partial read without truncation.
        # Use TRUNCATION_NOTICE_MARKER format so ToolResultCompactor can
        # re-truncate with the correct start_line when compacting old messages.
        if text == selected_content and e < total:
            content_bytes = len(text.encode("utf-8"))
            notice = (
                TRUNCATION_NOTICE_MARKER + f"\nThe output above was truncated."
                f"\nThe full content is saved to the file "
                f"and contains {total} lines in total."
                f"\nThis excerpt starts at line {s} and "
                f"covers the next {content_bytes} bytes."
                "\nIf the current content is not enough, "
                f"call `read_file` with file_path={file_path} "
                f"start_line={e + 1} to read more."
            )
            text = text + notice

        return ToolResponse(
            content=[TextBlock(type="text", text=text)],
        )

    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Read file failed due to \n{e}",
                ),
            ],
        )


async def write_file(
    file_path: str,
    content: str,
) -> ToolResponse:
    """Create or overwrite a file. Relative paths resolve from WORKING_DIR.

    Args:
        file_path (`str`):
            Path to the file.
        content (`str`):
            Content to write.
    """

    if not file_path:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: No `file_path` provided.",
                ),
            ],
        )

    file_path = _resolve_file_path(file_path)
    encoding = _get_encoding_for_file(file_path)

    try:
        with open(file_path, "w", encoding=encoding) as file:
            file.write(content)
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Wrote {len(content)} bytes to {file_path}.",
                ),
            ],
        )
    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Write file failed due to \n{e}",
                ),
            ],
        )


# pylint: disable=too-many-return-statements
async def edit_file(
    file_path: str,
    old_text: str,
    new_text: str,
) -> ToolResponse:
    """Find-and-replace text in a file. All occurrences of old_text are
    replaced with new_text. Relative paths resolve from WORKING_DIR.

    Args:
        file_path (`str`):
            Path to the file.
        old_text (`str`):
            Exact text to find.
        new_text (`str`):
            Replacement text.
    """

    if not file_path:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: No `file_path` provided.",
                ),
            ],
        )

    resolved_path = _resolve_file_path(file_path)

    if not os.path.exists(resolved_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The file {resolved_path} does not exist.",
                ),
            ],
        )

    if not os.path.isfile(resolved_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The path {resolved_path} is not a file.",
                ),
            ],
        )

    try:
        content = await read_file_safe(resolved_path)
    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Read file failed due to \n{e}",
                ),
            ],
        )

    if old_text not in content:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The text to replace was not found in {file_path}.",
                ),
            ],
        )

    new_content = content.replace(old_text, new_text)
    write_response = await write_file(
        file_path=resolved_path,
        content=new_content,
    )

    if write_response.content and len(write_response.content) > 0:
        write_text = write_response.content[0].get("text", "")
        if write_text.startswith("Error:"):
            return write_response

    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=f"Successfully replaced text in {file_path}.",
            ),
        ],
    )


async def append_file(
    file_path: str,
    content: str,
) -> ToolResponse:
    """Append content to the end of a file. Relative paths resolve from
    WORKING_DIR.

    Args:
        file_path (`str`):
            Path to the file.
        content (`str`):
            Content to append.
    """

    if not file_path:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: No `file_path` provided.",
                ),
            ],
        )

    file_path = _resolve_file_path(file_path)
    encoding = _get_encoding_for_file(file_path)

    try:
        with open(file_path, "a", encoding=encoding) as file:
            file.write(content)
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Appended {len(content)} bytes to {file_path}.",
                ),
            ],
        )
    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Append file failed due to \n{e}",
                ),
            ],
        )
