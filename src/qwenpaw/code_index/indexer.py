# -*- coding: utf-8 -*-
"""Zero-dependency SQLite code indexer.

Indexes Python source files: symbols, imports, call references.
Auto-invalidates on file modification time change.
"""

import os
import sqlite3
from pathlib import Path
from typing import Generator

from .parser import CodeParser


class CodeIndexer:
    """Build and query a SQLite-backed code index.

    Usage::

        idx = CodeIndexer("/tmp/code_index.db", "/path/to/project")
        idx.build_index()          # scan all .py files
        idx.update_index()         # incremental: only changed files

        results = idx.search("def foo")
        syms = idx.lookup_symbol("MyClass")
        callers = idx.who_calls("some_function")
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS files (
        path TEXT PRIMARY KEY,
        mtime REAL NOT NULL,
        size INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS symbols (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
        kind TEXT NOT NULL,      -- "class" | "function" | "async_function"
        name TEXT NOT NULL,
        lineno INTEGER NOT NULL,
        col_offset INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
    CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path);
    CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind);

    CREATE TABLE IF NOT EXISTS imports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
        module TEXT NOT NULL,
        alias TEXT,
        lineno INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_imports_module ON imports(module);

    CREATE TABLE IF NOT EXISTS calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
        name TEXT NOT NULL,
        lineno INTEGER NOT NULL,
        col_offset INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_calls_name ON calls(name);
    """

    def __init__(self, db_path: str | Path, project_root: str | Path):
        self.db_path = Path(db_path)
        self.project_root = Path(project_root).resolve()
        self.parser = CodeParser()
        self._conn: sqlite3.Connection | None = None

    # ── Connection management ────────────────────────────────────────

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                "PRAGMA synchronous=OFF",
            )  # safe for single-user
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(self.SCHEMA)
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Index build / update ─────────────────────────────────────────

    def iter_py_files(self) -> Generator[Path, None, None]:
        """Yield all ``.py`` files under *project_root*.
        Respects ``.gitignore``."""
        # ponytail: ceiling=5000 files, upgrade=use .gitignore-aware walk
        gitignore = self.project_root / ".gitignore"
        ignored_dirs: set[str] = {
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "node_modules",
            ".tox",
            ".eggs",
            "build",
            "dist",
            ".qwenpaw",
        }

        if gitignore.exists():
            for line in gitignore.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    ignored_dirs.add(line.rstrip("/"))

        for root, dirs, files in os.walk(self.project_root):
            # Skip ignored dirs
            dirs[:] = [
                d
                for d in dirs
                if d not in ignored_dirs and not d.startswith(".")
            ]
            for f in files:
                if f.endswith(".py"):
                    yield Path(root) / f

    def build_index(self) -> int:
        """Full rebuild: drop and re-index all files.

        Returns file count.
        """
        self.conn.executescript(
            """
            DELETE FROM calls;
            DELETE FROM imports;
            DELETE FROM symbols;
            DELETE FROM files;
        """,
        )
        count = 0
        for pyfile in self.iter_py_files():
            self._index_file(pyfile)
            count += 1
        self.conn.commit()
        return count

    def update_index(self) -> int:
        """Incremental update: re-index changed/new files.

        Returns updated file count.
        """
        count = 0
        for pyfile in self.iter_py_files():
            stat = pyfile.stat()
            mtime = stat.st_mtime
            row = self.conn.execute(
                "SELECT mtime, size FROM files WHERE path = ?",
                (str(pyfile),),
            ).fetchone()
            if row and row["mtime"] == mtime and row["size"] == stat.st_size:
                continue  # unchanged
            self._index_file(pyfile)
            count += 1
        self.conn.commit()
        return count

    def _index_file(self, path: Path) -> None:
        """Parse and store one file's symbols/imports/calls."""
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return  # skip unreadable files

        stat = path.stat()
        rel = str(path.resolve())

        # Upsert file record
        self.conn.execute(
            "INSERT OR REPLACE INTO files "
            "(path, mtime, size) VALUES (?, ?, ?)",
            (rel, stat.st_mtime, stat.st_size),
        )

        # Delete stale entries
        self.conn.execute("DELETE FROM symbols WHERE file_path = ?", (rel,))
        self.conn.execute("DELETE FROM imports WHERE file_path = ?", (rel,))
        self.conn.execute("DELETE FROM calls WHERE file_path = ?", (rel,))

        symbols = self.parser.parse(source)

        for sym in symbols.symbols:
            self.conn.execute(
                "INSERT INTO symbols "
                "(file_path, kind, name, lineno, col_offset) "
                "VALUES (?, ?, ?, ?, ?)",
                (rel, sym.kind, sym.name, sym.lineno, sym.col_offset),
            )
        for imp in symbols.imports:
            self.conn.execute(
                "INSERT INTO imports (file_path, module, alias, lineno) "
                "VALUES (?, ?, ?, ?)",
                (rel, imp.module, imp.alias, imp.lineno),
            )
        for call in symbols.calls:
            self.conn.execute(
                "INSERT INTO calls (file_path, name, lineno, col_offset) "
                "VALUES (?, ?, ?, ?)",
                (rel, call.name, call.lineno, call.col_offset),
            )

    # ── Queries ──────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search symbols by name (basic prefix/suffix/substring match)."""
        rows = self.conn.execute(
            """
            SELECT s.name, s.kind, s.file_path, s.lineno
            FROM symbols s
            WHERE s.name LIKE ? OR s.name LIKE ? OR s.name LIKE ?
            ORDER BY s.name
            LIMIT ?
            """,
            (f"{query}%", f"%{query}", f"%{query}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def lookup_symbol(self, name: str) -> list[dict]:
        """Find all definitions of a symbol by exact name."""
        rows = self.conn.execute(
            """
            SELECT s.name, s.kind, s.file_path, s.lineno,
                   f.mtime
            FROM symbols s
            JOIN files f ON f.path = s.file_path
            WHERE s.name = ?
            ORDER BY s.file_path, s.lineno
            """,
            (name,),
        ).fetchall()
        return [dict(r) for r in rows]

    def who_calls(self, name: str, limit: int = 50) -> list[dict]:
        """Find all call sites of a function/method by name."""
        rows = self.conn.execute(
            """
            SELECT c.name AS callee, c.file_path, c.lineno,
                   c.col_offset
            FROM calls c
            WHERE c.name = ?
            ORDER BY c.file_path, c.lineno
            LIMIT ?
            """,
            (name, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def file_deps(self, file_path: str) -> list[dict]:
        """List all modules imported by a file."""
        rows = self.conn.execute(
            """
            SELECT module, alias, lineno
            FROM imports
            WHERE file_path = ?
            ORDER BY lineno
            """,
            (file_path,),
        ).fetchall()
        return [dict(r) for r in rows]

    def module_importers(self, module: str) -> list[dict]:
        """Find all files that import a given module."""
        rows = self.conn.execute(
            """
            SELECT file_path, lineno
            FROM imports
            WHERE module = ? OR module LIKE ? || '.%'
            ORDER BY file_path, lineno
            """,
            (module, module),
        ).fetchall()
        return [dict(r) for r in rows]

    def symbols_in_file(self, file_path: str) -> list[dict]:
        """List all symbols defined in a file."""
        rows = self.conn.execute(
            """
            SELECT name, kind, lineno
            FROM symbols
            WHERE file_path = ?
            ORDER BY lineno
            """,
            (file_path,),
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        """Return index statistics."""
        return dict(
            self.conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM files) AS files,
                    (SELECT COUNT(*) FROM symbols) AS symbols,
                    (SELECT COUNT(*) FROM imports) AS imports,
                    (SELECT COUNT(*) FROM calls) AS calls
                """,
            ).fetchone(),
        )
