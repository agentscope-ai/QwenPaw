# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""File search tools: grep (content search) and glob (file discovery)."""

import asyncio
import logging
import re
import shlex
from pathlib import Path
from typing import Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...constant import WORKING_DIR
from ...config.context import get_current_workspace_dir
from ...fs_backend.adapter import get_fs_adapter
from .file_io import _resolve_file_path, _is_cloud_mode

_logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Cloud helpers: execute grep/find via sandbox shell
# ---------------------------------------------------------------------------

async def _grep_cloud(
    pattern: str,
    search_path: str,
    is_regex: bool,
    case_sensitive: bool,
    context_lines: int,
) -> ToolResponse:
    """Execute grep in the OpenSandbox cloud sandbox."""
    adapter = get_fs_adapter()
    sandbox = adapter.sandbox

    # Build grep command flags
    flags = ["-rn"]
    if not case_sensitive:
        flags.append("-i")
    if context_lines > 0:
        flags.append(f"-C {context_lines}")
    if not is_regex:
        flags.append("-F")  # Fixed string matching
    flags.append(f"--max-count={_MAX_MATCHES}")

    grep_flags = " ".join(flags)
    cmd = f"grep {grep_flags} -- {shlex.quote(pattern)} {shlex.quote(search_path)} 2>/dev/null || true"

    try:
        from datetime import timedelta
        from opensandbox.models.execd import RunCommandOpts

        opts = RunCommandOpts(timeout=timedelta(seconds=30))
        result = await asyncio.wait_for(
            sandbox.commands.run(cmd, opts=opts),
            timeout=35,
        )

        stdout_parts = [msg.text for msg in result.logs.stdout]
        output = "".join(stdout_parts).strip()

        if not output:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"No matches found for pattern: {pattern}",
                    ),
                ],
            )

        lines = output.split("\n")
        truncated = len(lines) > _MAX_MATCHES
        if truncated:
            lines = lines[:_MAX_MATCHES]

        text = "\n".join(lines)
        if truncated:
            text += f"\n\n(Results truncated at {_MAX_MATCHES} matches.)"

        return ToolResponse(
            content=[TextBlock(type="text", text=text)],
        )
    except Exception as e:
        _logger.warning("Cloud grep failed, falling back to local: %s", e)
        raise  # Let caller handle fallback


async def _glob_cloud(
    pattern: str,
    search_path: str,
) -> ToolResponse:
    """Execute glob/find in the OpenSandbox cloud sandbox."""
    adapter = get_fs_adapter()
    sandbox = adapter.sandbox

    # Use find command for glob matching in the sandbox
    # Convert glob pattern to find -name or -path patterns
    if "**" in pattern:
        # Recursive pattern: find -path "**/pattern"
        # e.g., "**/*.py" -> find . -name "*.py"
        name_part = pattern.replace("**/", "")
        cmd = (
            f"find {shlex.quote(search_path)} "
            f"-name {shlex.quote(name_part)} "
            f"-maxdepth 20 2>/dev/null "
            f"| head -{_MAX_MATCHES + 1}"
        )
    else:
        cmd = (
            f"find {shlex.quote(search_path)} "
            f"-maxdepth 1 -name {shlex.quote(pattern)} "
            f"2>/dev/null "
            f"| head -{_MAX_MATCHES + 1}"
        )

    try:
        from datetime import timedelta
        from opensandbox.models.execd import RunCommandOpts

        opts = RunCommandOpts(timeout=timedelta(seconds=30))
        result = await asyncio.wait_for(
            sandbox.commands.run(cmd, opts=opts),
            timeout=35,
        )

        stdout_parts = [msg.text for msg in result.logs.stdout]
        output = "".join(stdout_parts).strip()

        if not output:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"No files matched pattern: {pattern}",
                    ),
                ],
            )

        lines = output.split("\n")
        truncated = len(lines) > _MAX_MATCHES
        if truncated:
            lines = lines[:_MAX_MATCHES]

        # Make paths relative to search_path for cleaner output
        results = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith(search_path):
                rel = line[len(search_path):].lstrip("/")
                results.append(rel if rel else ".")
            else:
                results.append(line)

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
            content=[TextBlock(type="text", text=text)],
        )
    except Exception as e:
        _logger.warning("Cloud glob failed, falling back to local: %s", e)
        raise  # Let caller handle fallback


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

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

    # Resolve search path
    if _is_cloud_mode():
        search_root_str = (
            _resolve_file_path(path) if path else _resolve_file_path(".")
        )
        try:
            return await _grep_cloud(
                pattern, search_root_str, is_regex, case_sensitive, context_lines,
            )
        except Exception:
            _logger.warning("Cloud grep failed, falling back to local search")
            # Fall through to local search

    search_root = (
        Path(_resolve_file_path(path))
        if path
        else (get_current_workspace_dir() or WORKING_DIR)
    )

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

    # Cloud mode: use sandbox find command
    if _is_cloud_mode():
        search_root_str = (
            _resolve_file_path(path) if path else _resolve_file_path(".")
        )
        try:
            return await _glob_cloud(pattern, search_root_str)
        except Exception:
            _logger.warning("Cloud glob failed, falling back to local search")
            # Fall through to local search

    search_root = (
        Path(_resolve_file_path(path))
        if path
        else (get_current_workspace_dir() or WORKING_DIR)
    )

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
