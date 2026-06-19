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


class PathContainmentError(ValueError):
    """Raised when a tool-supplied path resolves outside the workspace."""


# Operators who intentionally need the built-in file tools to reach paths
# outside the agent workspace can opt out of containment by setting this
# env var to a truthy value. Containment is on by default (fail-closed).
_ALLOW_OUTSIDE_WORKSPACE_ENV = "QWENPAW_ALLOW_FILE_TOOLS_OUTSIDE_WORKSPACE"


def _file_tools_allow_outside_workspace() -> bool:
    """Return True when workspace containment for file tools is disabled."""
    value = os.environ.get(_ALLOW_OUTSIDE_WORKSPACE_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path_error_response(error: PathContainmentError) -> ToolResponse:
    """Wrap a containment violation as a fail-closed tool error."""
    return ToolResponse(
        content=[
            TextBlock(type="text", text=str(error)),
        ],
    )


def _resolve_file_path(file_path: str) -> str:
    """Resolve file path: use absolute path as-is,
    resolve relative path from current workspace or WORKING_DIR.

    When an agent workspace directory is set in context (the case for
    model-driven tool calls in a ReAct turn), the resolved path is
    constrained to that workspace so a tool-supplied ``file_path`` cannot
    escape it via ``..`` segments, symlinks, or an absolute path. Set
    ``QWENPAW_ALLOW_FILE_TOOLS_OUTSIDE_WORKSPACE=1`` to opt out. When no
    workspace is configured the legacy behavior (resolve relative to
    ``WORKING_DIR``, absolute paths as-is) is preserved.

    Args:
        file_path: The input file path (absolute or relative).

    Returns:
        The resolved absolute file path as string.

    Raises:
        PathContainmentError: If a workspace is configured and the
            resolved path escapes it (and the opt-out env var is not set).
    """
    # Workspace directory the model-driven agent is confined to, if any.
    workspace_dir = get_current_workspace_dir()
    path = Path(file_path).expanduser()
    if path.is_absolute():
        resolved = path
    else:
        resolved = Path(workspace_dir or WORKING_DIR) / path

    # Only enforce containment when an agent workspace is set. Without one,
    # the caller is the trusted local operator (direct/library use) and the
    # legacy resolution behavior is preserved.
    if workspace_dir is None or _file_tools_allow_outside_workspace():
        return str(resolved)

    # realpath collapses ``..`` and resolves symlinks so containment cannot
    # be defeated by traversal or links pointing outside the workspace.
    real_resolved = os.path.realpath(str(resolved))
    real_root = os.path.realpath(str(workspace_dir))
    if (
        real_resolved != real_root
        and os.path.commonpath([real_root, real_resolved]) != real_root
    ):
        raise PathContainmentError(
            f"Error: file_path {file_path!r} resolves outside the "
            f"workspace directory {real_root!r}.",
        )
    return str(resolved)


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

    try:
        file_path = _resolve_file_path(file_path)
    except PathContainmentError as exc:
        return _path_error_response(exc)

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
        content = await read_file_safe(file_path)
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
        max_bytes = get_current_recent_max_bytes() or DEFAULT_MAX_BYTES
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

    try:
        file_path = _resolve_file_path(file_path)
    except PathContainmentError as exc:
        return _path_error_response(exc)
    encoding = _get_encoding_for_file(file_path)

    try:
        async with aiofiles.open(file_path, "w", encoding=encoding) as file:
            await file.write(content)
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

    try:
        resolved_path = _resolve_file_path(file_path)
    except PathContainmentError as exc:
        return _path_error_response(exc)

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

    try:
        file_path = _resolve_file_path(file_path)
    except PathContainmentError as exc:
        return _path_error_response(exc)
    encoding = _get_encoding_for_file(file_path)

    try:
        async with aiofiles.open(file_path, "a", encoding=encoding) as file:
            await file.write(content)
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
