# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
import logging
import os
from pathlib import Path
from typing import Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...constant import WORKING_DIR
from ...config.context import get_current_workspace_dir
from ...fs_backend.adapter import get_fs_adapter
from .utils import truncate_file_output, read_file_safe

_logger = logging.getLogger(__name__)


def _is_cloud_mode() -> bool:
    """Check if the cloud file system backend is active."""
    try:
        adapter = get_fs_adapter()
        return adapter.is_cloud and adapter._backend is not None
    except Exception:
        return False


def _resolve_file_path(file_path: str) -> str:
    """Resolve file path: use absolute path as-is,
    resolve relative path from current workspace or WORKING_DIR.
    In cloud mode, resolve relative paths from the cloud working directory.

    Args:
        file_path: The input file path (absolute or relative).

    Returns:
        The resolved absolute file path as string.
    """
    if _is_cloud_mode():
        # In cloud mode, do string-based path resolution
        # (no local filesystem access for path resolution)
        path = file_path.strip()
        if path.startswith("/") or path.startswith("~"):
            return path
        from .shell import get_cloud_working_dir  # avoid circular import
        cloud_dir = get_cloud_working_dir()
        return f"{cloud_dir.rstrip('/')}/{path}"

    path = Path(file_path).expanduser()
    if path.is_absolute():
        return str(path)
    else:
        # Use current workspace_dir from context, fallback to WORKING_DIR
        workspace_dir = get_current_workspace_dir() or WORKING_DIR
        return str(workspace_dir / file_path)


# ---------------------------------------------------------------------------
# Cloud-aware I/O helpers
# ---------------------------------------------------------------------------

async def _file_exists(file_path: str) -> bool:
    """Check if file exists (cloud-aware)."""
    if _is_cloud_mode():
        adapter = get_fs_adapter()
        result = await adapter.exists(file_path)
        return result.success and result.data
    return os.path.exists(file_path)


async def _is_file(file_path: str) -> bool:
    """Check if path is a file (cloud-aware)."""
    if _is_cloud_mode():
        adapter = get_fs_adapter()
        result = await adapter.get_file_info(file_path)
        if result.success and result.data:
            return result.data.exists and not result.data.is_directory
        return False
    return os.path.isfile(file_path)


async def _read_content(file_path: str) -> str:
    """Read file content (cloud-aware)."""
    if _is_cloud_mode():
        adapter = get_fs_adapter()
        result = await adapter.read_file(file_path)
        if not result.success:
            raise IOError(result.error_message)
        return result.data
    return read_file_safe(file_path)


async def _write_content(file_path: str, content: str) -> None:
    """Write file content (cloud-aware)."""
    if _is_cloud_mode():
        adapter = get_fs_adapter()
        result = await adapter.write_file(file_path, content)
        if not result.success:
            raise IOError(result.error_message)
        return
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)


async def _append_content(file_path: str, content: str) -> None:
    """Append content to file (cloud-aware)."""
    if _is_cloud_mode():
        adapter = get_fs_adapter()
        # Cloud: read existing + write concatenated
        read_result = await adapter.read_file(file_path)
        existing = read_result.data if read_result.success else ""
        result = await adapter.write_file(file_path, existing + content)
        if not result.success:
            raise IOError(result.error_message)
        return
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

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

    if not await _file_exists(file_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The file {file_path} does not exist.",
                ),
            ],
        )

    if not await _is_file(file_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The path {file_path} is not a file.",
                ),
            ],
        )

    try:
        content = await _read_content(file_path)
        all_lines = content.split("\n")
        total = len(all_lines)

        # Determine read range
        s = max(1, start_line if start_line is not None else 1)
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
        text = truncate_file_output(
            selected_content,
            start_line=s,
            total_lines=total,
        )

        # Add continuation hint if partial read without truncation
        if text == selected_content and e < total:
            remaining = total - e
            text = (
                f"{file_path}  (lines {s}-{e} of {total})\n{text}\n\n"
                f"[{remaining} more lines. Use start_line={e + 1} to continue.]"
            )

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

    try:
        await _write_content(file_path, content)
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

    if not await _file_exists(resolved_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The file {resolved_path} does not exist.",
                ),
            ],
        )

    if not await _is_file(resolved_path):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The path {resolved_path} is not a file.",
                ),
            ],
        )

    try:
        content = await _read_content(resolved_path)
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

    try:
        await _append_content(file_path, content)
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
