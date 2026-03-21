# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""File search tools: grep (content search) and glob (file discovery)."""

import re
from pathlib import Path
from typing import Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...constant import WORKING_DIR
from .file_io import _resolve_file_path

# Skip binary / large files
_BINARY_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".svg",
        ".mp3",
        ".mp4",
        ".avi",
        ".mov",
        ".mkv",
        ".flac",
        ".wav",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
        ".rar",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        ".dat",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".pyc",
        ".pyo",
        ".class",
        ".o",
        ".a",
    },
)

_MAX_MATCHES = 200
_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB


def _is_text_file(path: Path) -> bool:
    """Heuristic check: skip known binary extensions and large files."""
    if path.suffix.lower() in _BINARY_EXTENSIONS:
        return False
    try:
        if path.stat().st_size > _MAX_FILE_SIZE:
            return False
    except OSError:
        return False
    return True


async def grep_search(  # pylint: disable=too-many-branches
    pattern: str,
    path: Optional[str] = None,
    is_regex: bool = False,
    case_sensitive: bool = True,
    context_lines: int = 0,
) -> ToolResponse:
    """Search file contents by pattern, recursively. Relative paths resolve
    from WORKING_DIR. Output format: ``path:line_number: content``.

    Args:
        pattern (`str`):
            Search string (or regex when is_regex=True).
        path (`str`, optional):
            File or directory to search in. Defaults to WORKING_DIR.
        is_regex (`bool`, optional):
            Treat pattern as a regular expression. Defaults to False.
        case_sensitive (`bool`, optional):
            Case-sensitive matching. Defaults to True.
        context_lines (`int`, optional):
            Context lines before and after each match (like grep -C).
            Defaults to 0.
    """
    if not pattern:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: No search `pattern` provided.",
                ),
            ],
        )

    search_root = Path(_resolve_file_path(path)) if path else WORKING_DIR

    if not search_root.exists():
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The path {search_root} does not exist.",
                ),
            ],
        )

    # Compile regex
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        if is_regex:
            regex = re.compile(pattern, flags)
        else:
            regex = re.compile(re.escape(pattern), flags)
    except re.error as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Invalid regex pattern — {e}",
                ),
            ],
        )

    matches: list[str] = []
    truncated = False

    # Collect files to search
    single_file = search_root.is_file()
    if single_file:
        files = [search_root]
    else:
        files = sorted(
            f
            for f in search_root.rglob("*")
            if f.is_file() and _is_text_file(f)
        )

    for file_path in files:
        if truncated:
            break
        try:
            lines = file_path.read_text(
                encoding="utf-8",
                errors="ignore",
            ).splitlines()
        except OSError:
            continue

        for line_no, line in enumerate(lines, start=1):
            if regex.search(line):
                if len(matches) >= _MAX_MATCHES:
                    truncated = True
                    break

                # Context window
                start = max(0, line_no - 1 - context_lines)
                end = min(len(lines), line_no + context_lines)

                # For single-file search show the filename, not '.'
                if single_file:
                    rel = file_path.name
                else:
                    rel = _relative_display(file_path, search_root)
                for ctx_idx in range(start, end):
                    prefix = ">" if ctx_idx == line_no - 1 else " "
                    matches.append(
                        f"{rel}:{ctx_idx + 1}:{prefix} {lines[ctx_idx]}",
                    )
                if context_lines > 0:
                    matches.append("---")

    if not matches:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"No matches found for pattern: {pattern}",
                ),
            ],
        )

    result = "\n".join(matches)
    if truncated:
        result += f"\n\n(Results truncated at {_MAX_MATCHES} matches.)"

    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=result,
            ),
        ],
    )


async def glob_search(
    pattern: str,
    path: Optional[str] = None,
) -> ToolResponse:
    """Find files matching a glob pattern (e.g. ``"*.py"``, ``"**/*.json"``).
    Relative paths resolve from WORKING_DIR.

    Args:
        pattern (`str`):
            Glob pattern to match.
        path (`str`, optional):
            Root directory to search from. Defaults to WORKING_DIR.
    """
    if not pattern:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: No glob `pattern` provided.",
                ),
            ],
        )

    search_root = Path(_resolve_file_path(path)) if path else WORKING_DIR

    if not search_root.exists():
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The path {search_root} does not exist.",
                ),
            ],
        )

    if not search_root.is_dir():
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: The path {search_root} is not a directory.",
                ),
            ],
        )

    try:
        results: list[str] = []
        truncated = False
        for entry in sorted(search_root.glob(pattern)):
            rel = _relative_display(entry, search_root)
            suffix = "/" if entry.is_dir() else ""
            results.append(f"{rel}{suffix}")
            if len(results) >= _MAX_MATCHES:
                truncated = True
                break

        if not results:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"No files matched pattern: {pattern}",
                    ),
                ],
            )

        text = "\n".join(results)
        if truncated:
            text += f"\n\n(Results truncated at {_MAX_MATCHES} entries.)"

        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=text,
                ),
            ],
        )
    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Glob search failed due to\n{e}",
                ),
            ],
        )


def _relative_display(target: Path, root: Path) -> str:
    """Return a relative path string if possible, otherwise absolute."""
    try:
        return str(target.relative_to(root))
    except ValueError:
        return str(target)
