# -*- coding: utf-8 -*-
"""Zero-dependency Python code parser using stdlib ``ast``.

Extracts symbols, imports, and call references from Python source files.
Compatible with Python 3.10+.
"""

import ast
import re
from pathlib import Path
from typing import NamedTuple


class Symbol(NamedTuple):
    kind: str  # "class" | "function" | "async_function"
    name: str
    lineno: int
    col_offset: int


class Import(NamedTuple):
    module: str  # full module path, e.g. "os.path"
    alias: str | None  # local alias, e.g. "path" for `import os.path as path`
    names: list[
        str
    ]  # imported names, e.g. ["path", "walk"] for `from os import path, walk`
    lineno: int


class CallRef(NamedTuple):
    name: str  # called name, e.g. "open", "Path.read_text"
    lineno: int
    col_offset: int


class FileSymbols(NamedTuple):
    symbols: list[Symbol]
    imports: list[Import]
    calls: list[CallRef]


# Regex helpers for when ast can't parse (e.g. syntax errors in file)
_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+)?import\s+(.+)$",
    re.MULTILINE,
)
_FUNC_RE = re.compile(
    r"^(?:async\s+)?def\s+(\w+)\s*\(",
    re.MULTILINE,
)
_CLASS_RE = re.compile(
    r"^class\s+(\w+)\s*(?:\(|:|\b)",
    re.MULTILINE,
)


class CodeParser:
    """Parse a Python source file for symbols, imports, and calls."""

    def parse(self, source: str) -> FileSymbols:
        """Return all symbols/imports/calls found in *source*."""
        try:
            tree = ast.parse(source)
            return self._visit(tree)
        except SyntaxError:
            # Fallback to regex when AST parsing fails
            return self._regex_fallback(source)

    def parse_file(self, path: str | Path) -> FileSymbols:
        """Convenience: read file and parse."""
        return self.parse(
            Path(path).read_text(encoding="utf-8", errors="replace"),
        )

    # ── AST visitor ──────────────────────────────────────────────────

    def _visit(self, tree: ast.AST) -> FileSymbols:
        symbols: list[Symbol] = []
        imports: list[Import] = []
        calls: list[CallRef] = []

        for node in ast.walk(tree):
            # ─ symbols ────────────────────────────────────────────
            if isinstance(node, ast.ClassDef):
                symbols.append(
                    Symbol("class", node.name, node.lineno, node.col_offset),
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = (
                    "async_function"
                    if isinstance(node, ast.AsyncFunctionDef)
                    else "function"
                )
                symbols.append(
                    Symbol(kind, node.name, node.lineno, node.col_offset),
                )

            # ─ imports ────────────────────────────────────────────
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        Import(
                            module=alias.name,
                            alias=alias.asname,
                            names=[alias.name],
                            lineno=node.lineno,
                        ),
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.append(
                    Import(
                        module=module,
                        alias=None,
                        names=[a.name for a in node.names],
                        lineno=node.lineno,
                    ),
                )

            # ─ call references (direct only) ──────────────────────
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.append(
                        CallRef(node.func.id, node.lineno, node.col_offset),
                    )
                elif isinstance(node.func, ast.Attribute):
                    # Reconstruct dotted name heuristically
                    parts = []
                    cur = node.func
                    while isinstance(cur, ast.Attribute):
                        parts.append(cur.attr)
                        cur = cur.value
                    if isinstance(cur, ast.Name):
                        parts.append(cur.id)
                    else:
                        parts.append("<expr>")
                    calls.append(
                        CallRef(
                            ".".join(reversed(parts)),
                            node.lineno,
                            node.col_offset,
                        ),
                    )

        return FileSymbols(symbols=symbols, imports=imports, calls=calls)

    # ─ Regex fallback for unparseable files ──────────────────────────

    def _regex_fallback(self, source: str) -> FileSymbols:
        """Extract what we can via regex when AST fails (e.g. partial code)."""
        symbols: list[Symbol] = []
        imports: list[Import] = []
        calls: list[CallRef] = []

        for m in _CLASS_RE.finditer(source):
            lineno = source[: m.start()].count("\n") + 1
            symbols.append(Symbol("class", m.group(1), lineno, 0))

        for m in _FUNC_RE.finditer(source):
            lineno = source[: m.start()].count("\n") + 1
            symbols.append(Symbol("function", m.group(1), lineno, 0))

        for m in _IMPORT_RE.finditer(source):
            lineno = source[: m.start()].count("\n") + 1
            from_mod = m.group(1) or ""
            target = m.group(2).strip()
            names = [n.strip().split(" as ")[0] for n in target.split(",")]
            imports.append(
                Import(
                    module=from_mod if from_mod else names[0],
                    alias=None,
                    names=names,
                    lineno=lineno,
                ),
            )

        return FileSymbols(symbols=symbols, imports=imports, calls=calls)
