# -*- coding: utf-8 -*-
"""Tests for ``build_env_context`` Coding Mode rendering."""
from __future__ import annotations

from qwenpaw.app.runner.utils import build_env_context


def test_no_project_dir_renders_legacy_working_directory_line() -> None:
    ctx = build_env_context(
        working_dir="/Users/x/.copaw/workspaces/default",
        add_hint=False,
    )
    assert "- Working directory: /Users/x/.copaw/workspaces/default" in ctx
    assert "Project directory" not in ctx
    assert "Agent workspace" not in ctx


def test_project_dir_replaces_working_directory_with_two_explicit_lines() -> (
    None
):
    ctx = build_env_context(
        working_dir="/Users/x/.copaw/workspaces/default",
        project_dir="/Users/x/code/agentscope-runtime",
        add_hint=False,
    )
    # New primary line — labelled so the LLM understands it's the
    # active project, not just some working directory.
    assert "- Project directory" in ctx
    assert "Coding Mode" in ctx
    assert "/Users/x/code/agentscope-runtime" in ctx

    # Workspace still surfaced but explicitly labelled internal so the
    # LLM doesn't reach for it by default.
    assert "Agent workspace (internal" in ctx
    assert "/Users/x/.copaw/workspaces/default" in ctx

    # Legacy line must NOT appear — that's the bug we're fixing.
    assert "- Working directory: " not in ctx


def test_project_dir_equal_to_workspace_skips_redundant_workspace_line() -> (
    None
):
    same = "/Users/x/.copaw/workspaces/default"
    ctx = build_env_context(
        working_dir=same,
        project_dir=same,
        add_hint=False,
    )
    # Don't double-print the same path.
    assert ctx.count(same) == 1
    assert "- Project directory" in ctx
    assert "Agent workspace" not in ctx


def test_empty_string_project_dir_treated_as_unset() -> None:
    ctx = build_env_context(
        working_dir="/w",
        project_dir="",
        add_hint=False,
    )
    assert "- Working directory: /w" in ctx
    assert "Project directory" not in ctx
