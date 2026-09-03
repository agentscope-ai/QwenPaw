# -*- coding: utf-8 -*-
"""Tests for runtime prompt contributors."""

from types import SimpleNamespace

import pytest

from qwenpaw.runtime.prompt_contributors import (
    WorkspacePromptFilesContributor,
    build_default_prompt_manager,
)


def _ctx(tmp_path, system_prompt_files):
    return SimpleNamespace(
        workspace_dir=str(tmp_path),
        agent_id="test_agent",
        extras={
            "agent_config": SimpleNamespace(
                system_prompt_files=system_prompt_files,
                language="en",
            ),
            "heartbeat_enabled": False,
            "language": "en",
            "memory_manager": None,
        },
    )


def test_workspace_prompt_files_respects_disabled_files(tmp_path):
    """Configured prompt file list gates SOUL.md and PROFILE.md."""
    (tmp_path / "AGENTS.md").write_text("agents body", encoding="utf-8")
    (tmp_path / "SOUL.md").write_text("soul body", encoding="utf-8")
    (tmp_path / "PROFILE.md").write_text("profile body", encoding="utf-8")

    prompt = build_default_prompt_manager().build_sync(
        _ctx(tmp_path, ["AGENTS.md"]),
    )

    assert "# AGENTS.md" in prompt
    assert "agents body" in prompt
    assert "# SOUL.md" not in prompt
    assert "soul body" not in prompt
    assert "# PROFILE.md" not in prompt
    assert "profile body" not in prompt


def test_workspace_prompt_files_empty_list_disables_workspace_markdown(
    tmp_path,
):
    """An empty configured list is meaningful and disables markdown files."""
    (tmp_path / "AGENTS.md").write_text("agents body", encoding="utf-8")
    (tmp_path / "SOUL.md").write_text("soul body", encoding="utf-8")
    (tmp_path / "PROFILE.md").write_text("profile body", encoding="utf-8")

    fragment = WorkspacePromptFilesContributor().contribute_sync(
        _ctx(tmp_path, []),
    )

    assert fragment is None


def test_workspace_prompt_files_preserves_configured_order_and_custom_files(
    tmp_path,
):
    """Configured file order is the rendered prompt order."""
    (tmp_path / "AGENTS.md").write_text("agents body", encoding="utf-8")
    (tmp_path / "PROFILE.md").write_text("profile body", encoding="utf-8")
    (tmp_path / "CUSTOM.md").write_text("custom body", encoding="utf-8")

    fragment = WorkspacePromptFilesContributor().contribute_sync(
        _ctx(tmp_path, ["PROFILE.md", "CUSTOM.md", "AGENTS.md"]),
    )

    assert fragment is not None
    assert fragment.index("# PROFILE.md") < fragment.index("# CUSTOM.md")
    assert fragment.index("# CUSTOM.md") < fragment.index("# AGENTS.md")


def test_workspace_prompt_files_skips_parent_traversal(tmp_path):
    """Configured prompt files cannot escape the workspace via ``..``."""
    outside = tmp_path.parent / f"{tmp_path.name}_secret.md"
    outside.write_text("secret body", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("agents body", encoding="utf-8")

    fragment = WorkspacePromptFilesContributor().contribute_sync(
        _ctx(tmp_path, [f"../{outside.name}", "AGENTS.md"]),
    )

    assert fragment is not None
    body = str(fragment)
    assert "secret body" not in body
    assert "agents body" in body


def test_workspace_prompt_files_skips_symlink_escape(tmp_path):
    """Configured prompt files cannot escape through symlinks."""
    outside = tmp_path.parent / f"{tmp_path.name}_symlink_secret.md"
    outside.write_text("secret body", encoding="utf-8")
    link = tmp_path / "LINK.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")

    fragment = WorkspacePromptFilesContributor().contribute_sync(
        _ctx(tmp_path, ["LINK.md"]),
    )

    assert fragment is None
