# -*- coding: utf-8 -*-
"""Tests for agent workspace setup utilities."""

from qwenpaw.agents.utils.setup_utils import copy_workspace_md_files


def test_copy_workspace_md_files_copies_bootstrap_for_new_workspace(
    tmp_path,
):
    """New workspaces should still receive bootstrap guidance."""
    copied_files = copy_workspace_md_files("zh", tmp_path)

    assert "BOOTSTRAP.md" in copied_files
    assert (tmp_path / "BOOTSTRAP.md").exists()


def test_copy_workspace_md_files_skips_bootstrap_when_completed(
    tmp_path,
):
    """Completed bootstrap workspaces should not recreate BOOTSTRAP.md."""
    (tmp_path / ".bootstrap_completed").touch()

    copied_files = copy_workspace_md_files("zh", tmp_path)

    assert "BOOTSTRAP.md" not in copied_files
    assert not (tmp_path / "BOOTSTRAP.md").exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "PROFILE.md").exists()
    assert (tmp_path / "MEMORY.md").exists()


def test_copy_workspace_md_files_skips_bootstrap_for_initialized_workspace(
    tmp_path,
):
    """Core md files are enough to treat the workspace as initialized."""
    for filename in ("AGENTS.md", "PROFILE.md", "MEMORY.md"):
        (tmp_path / filename).write_text("custom", encoding="utf-8")

    copied_files = copy_workspace_md_files("zh", tmp_path)

    assert "BOOTSTRAP.md" not in copied_files
    assert not (tmp_path / "BOOTSTRAP.md").exists()
    assert (tmp_path / "HEARTBEAT.md").exists()
