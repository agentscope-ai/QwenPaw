"""Bootstrap for the sandboxed ``execute_python`` REPL (stdlib only).

Runs *inside* the sandbox subprocess. ``bootstrap(...)`` builds the names the
model's recall code expects — ``ms`` (the read-only history attach + scratch),
``SCRATCH`` (a working dir), ``grep``, ``days_between`` — and returns them as a
dict the cell merges into its globals.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Callable


def bootstrap(
    *,
    history_db_path: str,
    session_id: str | None,
    task_id: str | None,
    scratch_dir: str,
    scratch_db_path: str | None,
) -> dict[str, Any]:
    # Imported here, not at module top: ``memoryspace`` resolves only once the
    # cell has added this dir to sys.path (inside the sandbox subprocess).
    from memoryspace import MemorySpace

    scratch = Path(scratch_dir)
    scratch.mkdir(parents=True, exist_ok=True)
    ms = MemorySpace(
        history_db_path=history_db_path,
        session_id=session_id,
        task_id=task_id,
        scratch_db_path=scratch_db_path,
    )
    return {
        "ms": ms,
        "SCRATCH": scratch,
        "grep": _make_grep(scratch),
        "days_between": _days_between,
    }


def _make_grep(default_root: Path) -> Callable[..., list[str]]:
    """Recursive ``grep(pattern, path=SCRATCH)`` -> ``relpath:lineno:line``."""
    def grep(
        pattern: str,
        path: str | Path | None = None,
        *,
        max_matches: int = 200,
    ) -> list[str]:
        root = Path(path) if path is not None else default_root
        regex = re.compile(pattern)
        if root.is_file():
            files = [root]
            base = root.parent
        else:
            files = [p for p in root.rglob("*") if p.is_file()]
            base = root
        out: list[str] = []
        for fp in files:
            try:
                text = fp.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            name = str(fp.relative_to(base))
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    out.append(f"{name}:{lineno}:{line}")
                    if len(out) >= max_matches:
                        return out
        return out

    return grep


_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def _parse_date(value: Any) -> date:
    m = _DATE_RE.search(str(value))
    if not m:
        raise ValueError(f"days_between: no YYYY-MM-DD date in {value!r}")
    y, mo, d = (int(g) for g in m.groups())
    return date(y, mo, d)


def _days_between(d1: str, d2: str, inclusive: bool = False) -> int:
    """Absolute number of days between two dates (LLM calendar math is flaky)."""
    n = abs((_parse_date(d2) - _parse_date(d1)).days)
    return n + 1 if inclusive else n
