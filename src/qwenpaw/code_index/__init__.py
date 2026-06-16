# -*- coding: utf-8 -*-
"""Code index subsystem — zero-dependency Python code understanding.

Uses stdlib ``ast`` (parser) + ``sqlite3`` (index) + ``os`` (scanner).
No tree-sitter, no watchdog, no external deps.

Auto-builds a SQLite index of:
  - File paths + modtimes (invalidation)
  - Symbol definitions (classes, functions, async functions)
  - Call references (basic static analysis)
  - Import graph (file → imported modules)
"""

from .indexer import CodeIndexer

__all__ = ["CodeIndexer"]
