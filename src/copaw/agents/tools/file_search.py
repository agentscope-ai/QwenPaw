# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""File search tools: grep (content search) and glob (file discovery)."""

import asyncio
import fnmatch
import os
import re
import threading
from collections import deque
from pathlib import Path
from typing import Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR
from .file_io import _resolve_file_path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "__pycache__",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        ".eggs",
        "dist",
        "build",
        ".next",
        ".nuxt",
    },
)

_MAX_MATCHES = 200
_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB
_MAX_CONTEXT_LINES = 5
_MAX_OUTPUT_CHARS = 50_000  # ~50 KB
_MAX_FILES_SCANNED = 10_000
_GREP_TIMEOUT = 30  # seconds
_GLOB_TIMEOUT = 15  # seconds

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_text_file(path: Path) -> bool:
    """Heuristic: skip known binary extensions and files > 2 MB."""
    if path.suffix.lower() in _BINARY_EXTENSIONS:
        return False
    try:
        if path.stat().st_size > _MAX_FILE_SIZE:
            return False
    except OSError:
        return False
    return True


def _relative_display(target: Path, root: Path) -> str:
    """Relative path with forward slashes (even on Windows)."""
    try:
        return str(target.relative_to(root)).replace(os.sep, "/")
    except ValueError:
        return str(target).replace(os.sep, "/")


def _make_response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _resolve_search_root(
    path: Optional[str],
    require_dir: bool = False,
) -> "Path | ToolResponse":
    """Resolve and validate a search root path.

    Returns a ``Path`` on success or a ``ToolResponse`` error.
    """
    search_root = (
        Path(_resolve_file_path(path))
        if path
        else (get_current_workspace_dir() or WORKING_DIR)
    )
    try:
        exists = search_root.exists()
    except OSError as e:
        return _make_response(
            f"Error: Cannot access path {search_root} — {e}",
        )
    if not exists:
        return _make_response(
            f"Error: The path {search_root} does not exist.",
        )
    if require_dir and not search_root.is_dir():
        return _make_response(
            f"Error: The path {search_root} is not a directory.",
        )
    return search_root


def _emit_match_entries(
    entries: list[tuple[int, str, bool]],
    disp_path: str,
    matches: list[str],
    total_chars: int,
) -> tuple[bool, int]:
    """Append a batch of context entries to matches.

    Each entry is a tuple of (line_no, content, is_hit).
    The is_hit flag determines the prefix ('>' for hit, ' ' for context).
    Empty entries list is allowed and will be a no-op.

    Args:
        entries: List of (line_no, content, is_hit) tuples.
        disp_path: Display path for the file.
        matches: List to append formatted entries to (modified in place).
        total_chars: Current character count.

    Returns:
        Tuple of (success, new_total_chars). Success is True if all entries
        were appended, False if limits were reached.
    """
    for ln, content, is_hit in entries:
        if len(matches) >= _MAX_MATCHES:
            return False, total_chars
        prefix = ">" if is_hit else " "
        entry = f"{disp_path}:{ln}:{prefix} {content}"
        projected_total = total_chars + len(entry) + 1
        if projected_total > _MAX_OUTPUT_CHARS:
            return False, total_chars
        total_chars = projected_total
        matches.append(entry)

    return True, total_chars


def _output_context_for_hit(
    hit_line_no: int,
    line_buffer: deque[tuple[int, str]],
    display_path: str,
    context_lines: int,
    matches: list[str],
    total_chars: int,
) -> tuple[bool, int]:
    """Output context lines around a hit.

    For each hit, we output lines from (hit - context_lines) to
    (hit + context_lines), clamped to file boundaries. The hit line
    is marked with '>' prefix, others with ' '.

    Uses fast path when hit is found in buffer: direct slice indexing.
    Falls back to range scan for edge cases (e.g., file start/end).

    Args:
        hit_line_no: Line number of the hit.
        line_buffer: Deque of (line_no, content) tuples.
        display_path: Display path for the file.
        context_lines: Number of context lines before/after hit.
        matches: List to append formatted entries to (modified in place).
        total_chars: Current character count.

    Returns:
        Tuple of (success, new_total_chars). Success is False if limits
        were reached during output.
    """
    # Find the index of hit_line_no in the buffer for fast slicing
    # hit_idx is always found since hit_line_no was taken from the buffer
    hit_idx = next(
        idx
        for idx, (line_no, _) in enumerate(line_buffer)
        if line_no == hit_line_no
    )

    slice_start = max(0, hit_idx - context_lines)
    slice_end = min(len(line_buffer), hit_idx + context_lines + 1)

    buffer_slice = list(line_buffer)[slice_start:slice_end]
    entries: list[tuple[int, str, bool]] = [
        (line_no, line_content, line_no == hit_line_no)
        for line_no, line_content in buffer_slice
    ]

    # Batch append all collected entries
    success, total_chars = _emit_match_entries(
        entries,
        display_path,
        matches,
        total_chars,
    )
    if not success:
        return False, total_chars

    # Append separator if needed
    if context_lines > 0:
        if len(matches) >= _MAX_MATCHES:
            return False, total_chars
        projected_total = total_chars + 4
        if projected_total > _MAX_OUTPUT_CHARS:
            return False, total_chars
        matches.append("---")
        total_chars = projected_total

    return True, total_chars


# ---------------------------------------------------------------------------
# Synchronous workers (run inside asyncio.to_thread)
# ---------------------------------------------------------------------------


def _walk_and_grep(  # noqa: C901  pylint: disable=too-many-branches,too-many-locals,too-many-statements
    search_root: Path,
    regex: "re.Pattern[str]",
    context_lines: int,
    cancel: threading.Event,
    include_pattern: "str | None",
) -> tuple[list[str], str]:
    """Walk *search_root*, grep every text file, return ``(lines, status)``.

    *cancel* is checked frequently; when set the worker stops and returns
    whatever it has so far.  *status* is one of ``"ok"``, ``"truncated:…"``
    or ``"timeout"``.
    """
    context_lines = min(max(context_lines, 0), _MAX_CONTEXT_LINES)
    single_file = search_root.is_file()

    matches: list[str] = []
    total_chars = 0
    status = "ok"

    if single_file:
        file_iter: list[Path] = [search_root]
    else:
        file_iter = []
        for dirpath, dirnames, filenames in os.walk(
            search_root,
            followlinks=False,
        ):
            if cancel.is_set():
                status = "timeout"
                break
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for fname in filenames:
                fp = Path(dirpath) / fname
                if not _is_text_file(fp):
                    continue
                if include_pattern and not fnmatch.fnmatch(
                    fname,
                    include_pattern,
                ):
                    continue
                file_iter.append(fp)
                if len(file_iter) >= _MAX_FILES_SCANNED:
                    break
            if len(file_iter) >= _MAX_FILES_SCANNED:
                break
        file_iter.sort()

    # Sliding window size: context_lines before + hit + context_lines after
    window_size = context_lines * 2 + 1
    middle_idx = context_lines

    for file_path in file_iter:
        if cancel.is_set():
            status = "timeout"
            break

        display_path = (
            file_path.name
            if single_file
            else _relative_display(file_path, search_root)
        )

        # Sliding window holds (line_no, line_content) tuples
        sliding_window: deque[tuple[int, str]] = deque(maxlen=window_size)
        # Indices in window where matches occurred, ordered by position
        hit_indices: list[int] = []

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                line_no = 0
                for line in f:
                    if line_no % 1000 == 0 and cancel.is_set():
                        status = "timeout"
                        break

                    line_no = line_no + 1
                    line_content = line.rstrip("\n").rstrip("\r")
                    is_match = bool(regex.search(line_content))

                    sliding_window.append((line_no, line_content))
                    if is_match:
                        hit_indices.append(len(sliding_window) - 1)

                    if len(sliding_window) == window_size:
                        # Process hits that are before the middle of the window.
                        # These hits have collected their full context (context_lines after).
                        while hit_indices and hit_indices[0] < middle_idx:
                            hit_line = sliding_window[hit_indices.pop(0)][0]
                            success, total_chars = _output_context_for_hit(
                                hit_line,
                                sliding_window,
                                display_path,
                                context_lines,
                                matches,
                                total_chars,
                            )
                            if not success:
                                status = (
                                    f"truncated: match limit ({_MAX_MATCHES})"
                                    if len(matches) >= _MAX_MATCHES
                                    else f"truncated: output size limit (~{_MAX_OUTPUT_CHARS // 1000}KB)"
                                )
                                break

                        if status != "ok":
                            break
                        # Process the middle position hit if any.
                        # At this point, the hit has context_lines before and after.
                        if hit_indices and hit_indices[0] == middle_idx:
                            hit_line = sliding_window[hit_indices.pop(0)][0]
                            success, total_chars = _output_context_for_hit(
                                hit_line,
                                sliding_window,
                                display_path,
                                context_lines,
                                matches,
                                total_chars,
                            )
                            if not success:
                                status = (
                                    f"truncated: match limit ({_MAX_MATCHES})"
                                    if len(matches) >= _MAX_MATCHES
                                    else f"truncated: output size limit (~{_MAX_OUTPUT_CHARS // 1000}KB)"
                                )
                                break
                        # Slide the window forward by removing the oldest line.
                        # Adjust remaining hit indices to match new positions.
                        sliding_window.popleft()
                        hit_indices = [i - 1 for i in hit_indices if i > 0]

                if status != "ok":
                    break

                # Process any remaining hits in the buffer after EOF.
                # These are hits that never became the middle of a full window
                # (e.g., hits near file start or end).
                for hit_idx in hit_indices:
                    hit_line_no = sliding_window[hit_idx][0]
                    success, total_chars = _output_context_for_hit(
                        hit_line_no,
                        sliding_window,
                        display_path,
                        context_lines,
                        matches,
                        total_chars,
                    )
                    if not success:
                        status = (
                            f"truncated: match limit ({_MAX_MATCHES})"
                            if len(matches) >= _MAX_MATCHES
                            else f"truncated: output size limit (~{_MAX_OUTPUT_CHARS // 1000}KB)"
                        )
                        break

        except OSError:
            continue

        if status != "ok":
            break

    return matches, status


def _walk_and_glob(
    search_root: Path,
    pattern: str,
    cancel: threading.Event,
) -> tuple[list[str], bool]:
    """Iterate ``search_root.glob(pattern)`` with cancellation support.

    Returns ``(result_lines, truncated)``.
    """
    results: list[str] = []
    truncated = False

    try:
        for entry in search_root.glob(pattern):
            if cancel.is_set():
                break
            try:
                parts = entry.relative_to(search_root).parts
            except ValueError:
                parts = ()
            if any(p in _SKIP_DIRS for p in parts):
                continue
            display_path = _relative_display(entry, search_root)
            suffix = "/" if entry.is_dir() else ""
            results.append(f"{display_path}{suffix}")
            if len(results) >= _MAX_MATCHES:
                truncated = True
                break
    except OSError:
        pass

    results.sort()
    return results, truncated


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def grep_search(
    pattern: str,
    path: Optional[str] = None,
    is_regex: bool = False,
    case_sensitive: bool = True,
    context_lines: int = 0,
    include_pattern: Optional[str] = None,
) -> ToolResponse:
    """Search file contents by pattern, recursively. Relative paths resolve
    from WORKING_DIR. Output format: ``path:line_number: content``.

    Args:
        pattern (`str`):
            Search string (or regex when *is_regex* is True).
        path (`str`, optional):
            File or directory to search in.  Defaults to WORKING_DIR.
        is_regex (`bool`, optional):
            Treat *pattern* as a regular expression.  Defaults to False.
        case_sensitive (`bool`, optional):
            Case-sensitive matching.  Defaults to True.
        context_lines (`int`, optional):
            Context lines before and after each match (like grep -C).
            Defaults to 0.  Capped at 5.
        include_pattern (`str`, optional):
            Only search files whose **name** matches this glob
            (e.g. ``"*.py"``).  Defaults to None (all text files).
    """
    if not pattern:
        return _make_response("Error: No search `pattern` provided.")

    root_or_err = _resolve_search_root(path)
    if isinstance(root_or_err, ToolResponse):
        return root_or_err
    search_root: Path = root_or_err

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(
            pattern if is_regex else re.escape(pattern),
            flags,
        )
    except re.error as e:
        return _make_response(f"Error: Invalid regex pattern — {e}")

    cancel = threading.Event()

    def _worker() -> tuple[list[str], str]:
        try:
            return _walk_and_grep(
                search_root,
                regex,
                context_lines,
                cancel,
                include_pattern,
            )
        except Exception as exc:
            return [], f"error: {exc}"

    try:
        match_lines, status = await asyncio.wait_for(
            asyncio.to_thread(_worker),
            timeout=_GREP_TIMEOUT,
        )
    except asyncio.TimeoutError:
        cancel.set()
        await asyncio.sleep(0.05)
        return _make_response(
            f"Error: Search timed out after {_GREP_TIMEOUT}s. "
            f"Try narrowing the search path or using a more specific pattern.",
        )

    if status.startswith("error:"):
        result = f"Error: grep failed — {status}"
    elif status.startswith("truncated:"):
        # Even if no matches were appended (e.g., first match exceeded limit),
        # we should report truncation, not "No matches found"
        reason = status.split(":", 1)[1].strip()
        if match_lines:
            result = "\n".join(match_lines)
            result += (
                f"\n\n(Results truncated due to {reason}. "
                f"Try narrowing the search path or using a more specific pattern.)"
            )
        else:
            result = (
                f"Results truncated due to {reason}. "
                f"Try narrowing the search path or using a more specific pattern."
            )
    elif not match_lines:
        result = f"No matches found for pattern: {pattern}"
    else:
        result = "\n".join(match_lines)
        if status == "timeout":
            result += (
                f"\n\n(Partial results — search timed out after {_GREP_TIMEOUT}s. "
                f"Try narrowing the search scope.)"
            )

    return _make_response(result)


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
            Root directory to search from.  Defaults to WORKING_DIR.
    """
    if not pattern:
        return _make_response("Error: No glob `pattern` provided.")

    root_or_err = _resolve_search_root(path, require_dir=True)
    if isinstance(root_or_err, ToolResponse):
        return root_or_err
    search_root: Path = root_or_err

    cancel = threading.Event()

    def _worker() -> tuple[list[str], bool]:
        try:
            return _walk_and_glob(search_root, pattern, cancel)
        except Exception:
            return [], False

    try:
        results, truncated = await asyncio.wait_for(
            asyncio.to_thread(_worker),
            timeout=_GLOB_TIMEOUT,
        )
    except asyncio.TimeoutError:
        cancel.set()
        await asyncio.sleep(0.05)
        return _make_response(
            f"Error: Glob search timed out after {_GLOB_TIMEOUT}s. "
            f"Try a more specific pattern or narrower search path.",
        )

    if not results:
        return _make_response(f"No files matched pattern: {pattern}")

    text = "\n".join(results)
    if truncated:
        text += f"\n\n(Results truncated at {_MAX_MATCHES} entries.)"

    return _make_response(text)
