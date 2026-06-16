# -*- coding: utf-8 -*-
"""Code index tools — zero-dependency code understanding for Coding Mode.

Lazily builds a SQLite-backed symbol index on first call, then provides:
  - ``code_search(query, limit)`` — find symbols by name
  - ``symbol_context(name)``      — definition + callers
  - ``code_trace(name, depth)``   — trace call chains

All tools are **read-only** and use only stdlib (``ast`` + ``sqlite3``).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...code_index import CodeIndexer
from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR

logger = logging.getLogger(__name__)

# ── Singleton ────────────────────────────────────────────────────────
_indexer: CodeIndexer | None = None
_DB_NAME = ".code_index.db"
# project_root override — set from coding_mode_mixin at registration time
_PROJECT_ROOT: str | None = None


def set_project_root(path: str) -> None:
    """Set the project root override (called from coding_mode_mixin)."""
    global _PROJECT_ROOT  # noqa: PLW0603
    _PROJECT_ROOT = path


def _get_or_init_indexer(rebuild: bool = False) -> CodeIndexer:
    """Return the global ``CodeIndexer``, initialising it if needed."""
    global _indexer  # noqa: PLW0603
    if _indexer is not None:
        return _indexer

    workspace = get_current_workspace_dir() or WORKING_DIR
    project_root = Path(_PROJECT_ROOT or workspace).resolve()
    db_path = workspace / _DB_NAME
    _indexer = CodeIndexer(
        db_path=str(db_path),
        project_root=str(project_root),
    )

    try:
        count = _indexer.build_index() if rebuild else _indexer.update_index()
        logger.info(
            "Code index initialised: %s files indexed at %s",
            count,
            db_path,
        )
    except Exception as exc:
        logger.warning("Code index warm-up failed (will retry): %s", exc)

    return _indexer


def _make_response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _get_indexer_or_error() -> CodeIndexer | ToolResponse:
    """Return indexer or an error ``ToolResponse``."""
    try:
        idx = _get_or_init_indexer()
        return idx
    except Exception as exc:
        return _make_response(f"Error: code index unavailable — {exc}")


# ── Tool functions ───────────────────────────────────────────────────


async def code_search(
    query: str,
    limit: int = 20,
) -> ToolResponse:
    """Search the code index for symbols matching *query*.

    Use this instead of ``grep_search`` when you know (or suspect) the
    name of a class, function, or variable and need to find where it is
    defined.  Results are ranked by string similarity (prefix / substring
    / suffix match).

    Args:
        query: Name or partial name to search for (case-sensitive).
        limit: Max results (default 20, max 100).

    Returns:
        JSON with symbol name, kind, file, and line number.
    """
    if not query:
        return _make_response("Error: `query` is required.")

    idx_or_err = _get_indexer_or_error()
    if isinstance(idx_or_err, ToolResponse):
        return idx_or_err
    idx: CodeIndexer = idx_or_err

    limit = max(1, min(int(limit), 100))
    results = idx.search(query, limit=limit)
    if not results:
        return _make_response(
            json.dumps({"query": query, "results": []}),
        )

    return _make_response(
        json.dumps(
            {"query": query, "count": len(results), "results": results},
            indent=2,
            ensure_ascii=False,
        ),
    )


async def symbol_context(name: str) -> ToolResponse:
    """Show full context for a symbol: definitions + callers.

    Use this before modifying a function or class to understand who
    defines it and who calls it — without grep-searching the entire
    codebase.

    Args:
        name: Exact symbol name (case-sensitive).

    Returns:
        JSON with definitions and callers.
    """
    if not name:
        return _make_response("Error: `name` is required.")

    idx_or_err = _get_indexer_or_error()
    if isinstance(idx_or_err, ToolResponse):
        return idx_or_err
    idx: CodeIndexer = idx_or_err

    defs = idx.lookup_symbol(name)
    callers = idx.who_calls(name)

    return _make_response(
        json.dumps(
            {
                "symbol": name,
                "definitions": defs,
                "callers": callers,
                "total_definitions": len(defs),
                "total_callers": len(callers),
            },
            indent=2,
            ensure_ascii=False,
        ),
    )


async def code_trace(
    name: str,
    direction: str = "down",
    depth: int = 2,
) -> ToolResponse:
    """Trace function call chains starting from *name*.

    Use this to understand the call graph around a function before
    refactoring or fixing bugs.

    Args:
        name: Function name to trace from.
        direction: ``"down"`` (who this calls) or ``"up"`` (who calls this).
        depth: Recursion depth (1-5, default 2).

    Returns:
        Indented text showing the call chain.
    """
    if not name:
        return _make_response("Error: `name` is required.")
    if direction not in ("up", "down"):
        return _make_response(
            f"Error: direction must be 'up' or 'down', got '{direction}'.",
        )

    idx_or_err = _get_indexer_or_error()
    if isinstance(idx_or_err, ToolResponse):
        return idx_or_err
    idx: CodeIndexer = idx_or_err

    depth = max(1, min(int(depth), 5))
    visited: set[tuple[str, int, str]] = set()

    def _trace_down(fn: str, d: int, indent: str = "") -> list[str]:
        if d <= 0 or len(visited) > 200:
            return []
        calls = idx.who_calls(fn, limit=50)
        lines: list[str] = []
        for c in calls:
            key = (c["file_path"], c["lineno"], fn)
            if key in visited:
                continue
            visited.add(key)
            lines.append(f"{indent}  ↳ {c['file_path']}:{c['lineno']}")
            if d > 1:
                syms = idx.symbols_in_file(c["file_path"])
                nearby = [
                    s for s in syms if abs(s["lineno"] - c["lineno"]) < 20
                ]
                for s in nearby[:3]:
                    if s["name"] != fn:
                        sym_loc = f"{s['name']}:{s['lineno']}"
                        lines.append(f"{indent}    · {s['kind']} {sym_loc}")
        return lines

    def _trace_up(fn: str, d: int, indent: str = "") -> list[str]:
        if d <= 0 or len(visited) > 200:
            return []
        lines: list[str] = []
        for sym in idx.lookup_symbol(fn):
            key = (sym["file_path"], sym["lineno"], fn)
            if key in visited:
                continue
            visited.add(key)
            loc = f"{sym['file_path']}:{sym['lineno']}"
            lines.append(f"{indent}┌ {sym['kind']} {fn} at {loc}")
        callers = idx.who_calls(fn, limit=50)
        for c in callers:
            key = (c["file_path"], c["lineno"], fn)
            if key in visited:
                continue
            visited.add(key)
            lines.append(
                f"{indent}↑ {c['file_path']}:{c['lineno']} calls {fn}",
            )
        return lines

    lines = [f"◈ code_trace '{name}' ({direction}, depth={depth})"]
    if direction == "down":
        lines.extend(_trace_down(name, depth))
    else:
        lines.extend(_trace_up(name, depth))
    if len(visited) == 0:
        lines.append("  ✗ No trace found.")

    return _make_response("\n".join(lines))
