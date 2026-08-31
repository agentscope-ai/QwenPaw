# -*- coding: utf-8 -*-
"""Tests for the ADBPG memory manager local-file search fallback.

Covers _search_local_memory_files paragraph scoring, token filtering,
snippet bounding, and MEMORY.md + memory/*.md candidate discovery,
which previously had no coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.agents.memory.adbpg_memory_manager import ADBPGMemoryManager


@pytest.fixture
def workspace(tmp_path) -> Path:
    return tmp_path / "ws"


@pytest.fixture
def manager(workspace) -> ADBPGMemoryManager:
    workspace.mkdir(parents=True, exist_ok=True)
    return ADBPGMemoryManager(str(workspace), "agent-1")


class TestSearchLocalMemoryFiles:
    def test_no_memory_files_returns_empty(self, manager):
        assert manager._search_local_memory_files("anything") == []

    def test_memory_md_searched(self, manager, workspace):
        (workspace / "MEMORY.md").write_text(
            "User prefers dark mode.\n\nServer runs on port 8080.",
            encoding="utf-8",
        )
        results = manager._search_local_memory_files("dark mode")
        assert len(results) == 1
        path, snippet = results[0]
        assert path == "MEMORY.md"
        assert "dark mode" in snippet

    def test_memory_dir_files_searched(self, manager, workspace):
        memory_dir = workspace / "memory"
        memory_dir.mkdir()
        (memory_dir / "notes.md").write_text(
            "Deployment checklist includes rollback plan.",
            encoding="utf-8",
        )
        results = manager._search_local_memory_files("rollback")
        assert len(results) == 1
        assert results[0][0] == str(Path("memory") / "notes.md")

    def test_short_tokens_ignored(self, manager, workspace):
        (workspace / "MEMORY.md").write_text("abc def", encoding="utf-8")
        # single-char tokens are filtered out -> no search terms
        assert manager._search_local_memory_files("a b") == []

    def test_no_match_returns_empty(self, manager, workspace):
        (workspace / "MEMORY.md").write_text(
            "unrelated content",
            encoding="utf-8",
        )
        assert manager._search_local_memory_files("zebra") == []

    def test_score_ordering(self, manager, workspace):
        (workspace / "MEMORY.md").write_text(
            "alpha only\n\nalpha and beta together",
            encoding="utf-8",
        )
        results = manager._search_local_memory_files("alpha beta")
        assert len(results) == 2
        # paragraph containing both tokens scores higher and comes first
        assert "alpha and beta" in results[0][1]

    def test_max_results_respected(self, manager, workspace):
        paragraphs = "\n\n".join(f"keyword paragraph {i}" for i in range(10))
        (workspace / "MEMORY.md").write_text(paragraphs, encoding="utf-8")
        results = manager._search_local_memory_files("keyword", max_results=2)
        assert len(results) == 2

    def test_long_snippet_truncated(self, manager, workspace):
        long_para = "keyword " + "x" * 1000
        (workspace / "MEMORY.md").write_text(long_para, encoding="utf-8")
        results = manager._search_local_memory_files("keyword")
        assert results[0][1].endswith("...")
        assert len(results[0][1]) <= 504

    def test_case_insensitive_matching(self, manager, workspace):
        (workspace / "MEMORY.md").write_text(
            "Python is used for testing.",
            encoding="utf-8",
        )
        results = manager._search_local_memory_files("python")
        assert len(results) == 1

    def test_unreadable_file_skipped(self, manager, workspace, monkeypatch):
        (workspace / "MEMORY.md").write_text("keyword", encoding="utf-8")

        real_read = Path.read_text

        def broken_read(self, *args, **kwargs):
            raise OSError("unreadable")

        monkeypatch.setattr(Path, "read_text", broken_read)
        assert manager._search_local_memory_files("keyword") == []

    def test_non_md_files_ignored(self, manager, workspace):
        memory_dir = workspace / "memory"
        memory_dir.mkdir()
        (memory_dir / "data.txt").write_text("keyword", encoding="utf-8")
        assert manager._search_local_memory_files("keyword") == []
