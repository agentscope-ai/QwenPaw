# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tests for AgentMdManager."""
from pathlib import Path
from unittest.mock import patch

import pytest

# agent_md_manager.py has no third-party deps — no sys.modules mocks needed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager(tmp_path):
    """Create AgentMdManager with a fresh temp directory."""
    from qwenpaw.agents.memory.agent_md_manager import AgentMdManager

    return AgentMdManager(working_dir=tmp_path)


# ---------------------------------------------------------------------------
# TestAgentMdManagerInit
# ---------------------------------------------------------------------------


class TestAgentMdManagerInit:
    """P0: Initialization tests."""

    def test_working_dir_is_set(self, manager, tmp_path):
        assert manager.working_dir == tmp_path

    def test_memory_dir_is_subdirectory(self, manager, tmp_path):
        assert manager.memory_dir == tmp_path / "memory"

    def test_working_dir_created(self, tmp_path):
        """Constructor creates working_dir if not present."""
        from qwenpaw.agents.memory.agent_md_manager import (
            AgentMdManager,
        )

        new_dir = tmp_path / "new_subdir"
        assert not new_dir.exists()
        AgentMdManager(working_dir=new_dir)
        assert new_dir.exists()

    def test_memory_dir_created(self, tmp_path):
        """Constructor creates working_dir/memory."""
        from qwenpaw.agents.memory.agent_md_manager import (
            AgentMdManager,
        )

        _ = AgentMdManager(working_dir=tmp_path)
        assert (tmp_path / "memory").exists()

    def test_accepts_string_path(self, tmp_path):
        """Constructor accepts a string path."""
        from qwenpaw.agents.memory.agent_md_manager import (
            AgentMdManager,
        )

        mgr = AgentMdManager(working_dir=str(tmp_path))
        assert isinstance(mgr.working_dir, Path)


# ---------------------------------------------------------------------------
# TestAgentMdManagerListWorkingMds
# ---------------------------------------------------------------------------


class TestAgentMdManagerListWorkingMds:
    """P1: list_working_mds behavior."""

    def test_empty_when_no_md_files(self, manager):
        result = manager.list_working_mds()
        assert result == []

    def test_lists_md_files(self, manager, tmp_path):
        (tmp_path / "note.md").write_text("# Hello")
        result = manager.list_working_mds()
        assert len(result) == 1
        assert result[0]["filename"] == "note.md"

    def test_ignores_non_md_files(self, manager, tmp_path):
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "doc.md").write_text("# Doc")
        result = manager.list_working_mds()
        assert len(result) == 1
        assert result[0]["filename"] == "doc.md"

    def test_result_contains_expected_keys(self, manager, tmp_path):
        (tmp_path / "test.md").write_text("content")
        result = manager.list_working_mds()
        keys = result[0].keys()
        assert "filename" in keys
        assert "size" in keys
        assert "path" in keys
        assert "created_time" in keys
        assert "modified_time" in keys

    def test_size_matches_file_size(self, manager, tmp_path):
        content = "# Header\nsome content"
        (tmp_path / "sized.md").write_text(
            content,
            encoding="utf-8",
            newline="\n",
        )
        result = manager.list_working_mds()
        assert result[0]["size"] == len(content.encode("utf-8"))

    def test_multiple_md_files(self, manager, tmp_path):
        for name in ["a.md", "b.md", "c.md"]:
            (tmp_path / name).write_text(f"# {name}")
        result = manager.list_working_mds()
        assert len(result) == 3


# ---------------------------------------------------------------------------
# TestAgentMdManagerReadWorkingMd
# ---------------------------------------------------------------------------


class TestAgentMdManagerReadWorkingMd:
    """P1: read_working_md behavior."""

    def test_reads_existing_file(self, manager, tmp_path):
        (tmp_path / "notes.md").write_text(
            "# My Notes",
            encoding="utf-8",
        )
        result = manager.read_working_md("notes.md")
        assert result == "# My Notes"

    def test_auto_appends_md_extension(self, manager, tmp_path):
        (tmp_path / "notes.md").write_text(
            "content",
            encoding="utf-8",
        )
        result = manager.read_working_md("notes")
        assert result == "content"

    def test_strips_whitespace_from_content(self, manager, tmp_path):
        (tmp_path / "space.md").write_text(
            "  trimmed  \n\n",
            encoding="utf-8",
        )
        result = manager.read_working_md("space.md")
        assert result == "trimmed"

    def test_raises_file_not_found(self, manager):
        with pytest.raises(FileNotFoundError):
            manager.read_working_md("nonexistent.md")

    def test_reads_content_via_encoding_fallback(
        self,
        manager,
        tmp_path,
    ):
        """Patch read_text_file_with_encoding_fallback to verify it's
        called."""
        import sys

        (tmp_path / "enc.md").write_text("hello", encoding="utf-8")
        # Use the already-imported module from sys.modules to avoid
        # patch path resolution issues with qwenpaw.agents.__getattr__
        # on Linux (where the package attr may not yet be set).
        mod = sys.modules["qwenpaw.agents.memory.agent_md_manager"]
        with patch.object(
            mod,
            "read_text_file_with_encoding_fallback",
            return_value="patched",
        ) as mock_fn:
            result = manager.read_working_md("enc.md")
        mock_fn.assert_called_once()
        assert result == "patched"


# ---------------------------------------------------------------------------
# TestAgentMdManagerWriteWorkingMd
# ---------------------------------------------------------------------------


class TestAgentMdManagerWriteWorkingMd:
    """P1: write_working_md behavior."""

    def test_writes_file_to_working_dir(self, manager, tmp_path):
        manager.write_working_md("output.md", "# Content")
        assert (tmp_path / "output.md").exists()

    def test_written_content_matches(self, manager, tmp_path):
        manager.write_working_md("doc.md", "hello world")
        assert (tmp_path / "doc.md").read_text(
            encoding="utf-8",
        ) == "hello world"

    def test_auto_appends_md_extension(self, manager, tmp_path):
        manager.write_working_md("doc", "content")
        assert (tmp_path / "doc.md").exists()

    def test_overwrites_existing_file(self, manager, tmp_path):
        (tmp_path / "over.md").write_text("old", encoding="utf-8")
        manager.write_working_md("over.md", "new")
        assert (tmp_path / "over.md").read_text(encoding="utf-8") == "new"


# ---------------------------------------------------------------------------
# TestAgentMdManagerListMemoryMds
# ---------------------------------------------------------------------------


class TestAgentMdManagerListMemoryMds:
    """P1: list_memory_mds behavior."""

    def test_empty_when_no_memory_files(self, manager):
        result = manager.list_memory_mds()
        assert result == []

    def test_lists_files_in_memory_dir(self, manager, tmp_path):
        mem = tmp_path / "memory"
        (mem / "session.md").write_text("# Session")
        result = manager.list_memory_mds()
        assert len(result) == 1
        assert result[0]["filename"] == "session.md"

    def test_ignores_files_in_working_dir(self, manager, tmp_path):
        (tmp_path / "working.md").write_text("# Working")
        result = manager.list_memory_mds()
        assert result == []

    def test_result_has_all_keys(self, manager, tmp_path):
        mem = tmp_path / "memory"
        (mem / "test.md").write_text("x")
        result = manager.list_memory_mds()
        keys = result[0].keys()
        for k in (
            "filename",
            "size",
            "path",
            "created_time",
            "modified_time",
        ):
            assert k in keys


# ---------------------------------------------------------------------------
# TestAgentMdManagerReadMemoryMd
# ---------------------------------------------------------------------------


class TestAgentMdManagerReadMemoryMd:
    """P1: read_memory_md behavior."""

    def test_reads_existing_memory_file(self, manager, tmp_path):
        mem = tmp_path / "memory"
        (mem / "ctx.md").write_text("context", encoding="utf-8")
        result = manager.read_memory_md("ctx.md")
        assert result == "context"

    def test_auto_appends_md_extension(self, manager, tmp_path):
        mem = tmp_path / "memory"
        (mem / "ctx.md").write_text("data", encoding="utf-8")
        result = manager.read_memory_md("ctx")
        assert result == "data"

    def test_raises_file_not_found(self, manager):
        with pytest.raises(FileNotFoundError):
            manager.read_memory_md("missing.md")

    def test_strips_whitespace(self, manager, tmp_path):
        mem = tmp_path / "memory"
        (mem / "ws.md").write_text(
            "\n\n  trimmed  \n\n",
            encoding="utf-8",
        )
        result = manager.read_memory_md("ws.md")
        assert result == "trimmed"


# ---------------------------------------------------------------------------
# TestAgentMdManagerWriteMemoryMd
# ---------------------------------------------------------------------------


class TestAgentMdManagerWriteMemoryMd:
    """P1: write_memory_md behavior."""

    def test_writes_to_memory_dir(self, manager, tmp_path):
        manager.write_memory_md("mem.md", "# Memory")
        assert (tmp_path / "memory" / "mem.md").exists()

    def test_written_content_matches(self, manager, tmp_path):
        manager.write_memory_md("session.md", "session data")
        assert (tmp_path / "memory" / "session.md").read_text(
            encoding="utf-8",
        ) == "session data"

    def test_auto_appends_md_extension(self, manager, tmp_path):
        manager.write_memory_md("session", "data")
        assert (tmp_path / "memory" / "session.md").exists()

    def test_overwrites_existing_memory_file(
        self,
        manager,
        tmp_path,
    ):
        mem = tmp_path / "memory"
        (mem / "old.md").write_text("old data", encoding="utf-8")
        manager.write_memory_md("old.md", "new data")
        assert (mem / "old.md").read_text(encoding="utf-8") == "new data"
