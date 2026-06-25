# -*- coding: utf-8 -*-
"""AST search tool — multi-language structural pattern matching.

Thin wrapper around the ``ast-grep`` CLI (PyPI distribution
``ast-grep-cli``).  Exposes a single read-only ``ast_search`` function
for use inside Coding Mode.

The tool is strictly read-only by design: when the agent wants to
apply a rewrite it must read matches first and then call ``edit_file``
for each location.  This keeps the diff / approval / undo path on a
single ``edit_file`` entry-point (see PROPOSAL §四 of the design doc).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolChunk
from agentscope.message import ToolResultState

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR
from ...runtime.tool_registry import tool_descriptor
from .file_io import _resolve_file_path

# ---------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------

_AST_GREP_TIMEOUT = 30.0  # seconds for the CLI itself
_DEFAULT_MAX_MATCHES = 200
_MAX_MATCHES_CAP = 1000
_MAX_SNIPPET_CHARS = 400
_MAX_TOTAL_OUTPUT_CHARS = 80_000

# Hide the console window on Windows; no-op on POSIX.
_SUBPROCESS_FLAGS = (
    getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if sys.platform == "win32"
    else 0
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _make_response(text: str) -> ToolChunk:
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text)],
    )


def _ast_grep_binary() -> Optional[str]:
    """Return the path to the ast-grep CLI, or ``None`` if absent.

    The CLI is shipped under two names: ``ast-grep`` (long form) and
    ``sg`` (short form).  We probe both so users do not need to know
    which one their installer dropped on ``PATH``.
    """
    for name in ("ast-grep", "sg"):
        which = shutil.which(name)
        if which:
            return which
    return None


def is_ast_grep_available() -> bool:
    """Public helper used by the Coding Mode toolkit registration."""
    return _ast_grep_binary() is not None


def _resolve_root() -> Path:
    """Resolve the search base directory."""
    workspace = get_current_workspace_dir()
    if workspace is not None:
        return workspace
    return WORKING_DIR


def _resolve_search_path(
    path: str,
    root: Path,
) -> "Path | ToolChunk":
    """Resolve and validate the ``path`` argument.

    Empty string  → return ``root`` (search whole project).
    Anything else → must resolve **inside** ``root`` (anti-escape).
    """
    if not path:
        return root
    candidate = Path(_resolve_file_path(path)).expanduser()
    try:
        candidate_resolved = candidate.resolve()
    except OSError as exc:
        return _make_response(
            f"Error: cannot resolve path {candidate} — {exc}",
        )
    root_resolved = root.resolve()
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError:
        return _make_response(
            f"Error: path {path} is outside the project root "
            f"{root_resolved}.",
        )
    if not candidate_resolved.exists():
        return _make_response(
            f"Error: path {candidate_resolved} does not exist.",
        )
    return candidate_resolved


def _run_ast_grep_sync(
    args: list[str],
    cwd: Path,
) -> tuple[int, str, str]:
    """Spawn ast-grep and collect stdout/stderr.

    Runs inside ``asyncio.to_thread`` so the asyncio loop stays free.
    Returns ``(returncode, stdout, stderr)``; ``returncode`` is ``-1``
    on timeout or spawn failure.
    """
    try:
        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_SUBPROCESS_FLAGS,
        )
    except FileNotFoundError as exc:
        return -1, "", f"ast-grep not found: {exc}"
    except OSError as exc:
        return -1, "", f"failed to spawn ast-grep: {exc}"

    try:
        stdout, stderr = proc.communicate(timeout=_AST_GREP_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", "ast-grep timed out and refused to die"
        return -1, stdout, f"timeout after {_AST_GREP_TIMEOUT}s"

    return proc.returncode, stdout, stderr


def _format_matches(
    raw: list[dict],
    root: Path,
    max_matches: int,
) -> tuple[list[dict], bool]:
    """Convert ast-grep JSON output to the response schema.

    ast-grep emits 0-indexed ``line`` / ``column``; we expose 1-indexed
    numbers so they line up with editor gutters.  File paths are
    rendered relative to ``root`` with forward-slash separators.
    """
    matches: list[dict] = []
    truncated = False
    total_chars = 0
    root_resolved = root.resolve()
    for entry in raw:
        if len(matches) >= max_matches:
            truncated = True
            break
        rng = entry.get("range") or {}
        start = rng.get("start") or {}
        end = rng.get("end") or {}
        file_path = entry.get("file") or ""

        fp = Path(file_path)
        if not fp.is_absolute():
            fp = root / fp
        try:
            display_path = str(
                fp.resolve().relative_to(root_resolved),
            ).replace(os.sep, "/")
        except (ValueError, OSError):
            display_path = file_path.replace(os.sep, "/")

        snippet = (entry.get("lines") or entry.get("text") or "").rstrip()
        if len(snippet) > _MAX_SNIPPET_CHARS:
            snippet = snippet[:_MAX_SNIPPET_CHARS] + "…"

        match = {
            "file": display_path,
            "line": int(start.get("line", 0)) + 1,
            "column": int(start.get("column", 0)) + 1,
            "end_line": int(end.get("line", 0)) + 1,
            "snippet": snippet,
        }
        entry_chars = len(json.dumps(match, ensure_ascii=False))
        if total_chars + entry_chars > _MAX_TOTAL_OUTPUT_CHARS:
            truncated = True
            break
        total_chars += entry_chars
        matches.append(match)

    return matches, truncated


# ---------------------------------------------------------------------
# Public tool
# ---------------------------------------------------------------------


@tool_descriptor(
    requires_modes=("coding",),
    requires_sandbox=("file_read",),
)
async def ast_search(  # pylint: disable=too-many-return-statements
    pattern: str,
    language: str,
    path: str = "",
    max_matches: int = _DEFAULT_MAX_MATCHES,
) -> ToolChunk:
    """Search the project for code matching an AST pattern.

    Backed by the ``ast-grep`` CLI (``ast-grep run -p ... -l ...``).
    **Read-only** — to rewrite matches, call ``edit_file`` separately
    for each location.

    Args:
        pattern (`str`):
            ast-grep pattern.  Use ``$NAME`` for a single-node capture
            and ``$$$NAME`` for a multi-node capture.  Python example:
            ``def $FUNC($$$ARGS): $$$BODY``.
        language (`str`):
            Source language — ``python``, ``typescript``, ``javascript``,
            ``tsx``, ``go``, ``rust``, ``java``, ``c``, ``cpp``,
            ``ruby``, ``php``, ``kotlin``, ``swift``, ...  Validated by
            ast-grep itself; unknown values surface the CLI's error.
        path (`str`, optional):
            File or directory restricting the search, relative to the
            project root.  Empty string searches the whole project.
        max_matches (`int`, optional):
            Hard cap on returned matches.  Defaults to 200; capped at
            1000.
    """
    if not pattern:
        return _make_response("Error: empty `pattern`.")
    if not language:
        return _make_response("Error: missing `language`.")

    binary = _ast_grep_binary()
    if binary is None:
        return _make_response(
            "Error: ast-grep CLI not found on PATH.  Install with "
            "`pip install ast-grep-cli` and retry.",
        )

    max_matches = max(1, min(int(max_matches), _MAX_MATCHES_CAP))

    root = _resolve_root()
    target_or_err = _resolve_search_path(path, root)
    if isinstance(target_or_err, ToolChunk):
        return target_or_err
    target: Path = target_or_err

    args = [
        binary,
        "run",
        "--pattern",
        pattern,
        "--lang",
        language,
        "--json=compact",
        str(target),
    ]

    try:
        from ...tool_calls import cancellable_wait

        returncode, stdout, stderr = await cancellable_wait(
            asyncio.to_thread(_run_ast_grep_sync, args, root),
            fallback_secs=_AST_GREP_TIMEOUT + 5,
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        return _make_response(
            f"Error: ast_search timed out after {_AST_GREP_TIMEOUT}s. "
            f"Try a narrower `path` or a more specific pattern.",
        )

    if returncode != 0:
        msg = (stderr or stdout or "unknown error").strip()
        return _make_response(f"Error: ast-grep failed — {msg}")

    try:
        raw = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError as exc:
        return _make_response(
            f"Error: could not parse ast-grep output — {exc}",
        )

    if not isinstance(raw, list):
        return _make_response(
            "Error: unexpected ast-grep output (expected a JSON list).",
        )

    matches, truncated = _format_matches(raw, root, max_matches)

    if not matches:
        return _make_response(
            f"No matches for pattern in language={language}.",
        )

    payload = {"matches": matches, "truncated": truncated}
    return _make_response(
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
