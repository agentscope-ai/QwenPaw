# -*- coding: utf-8 -*-
"""Tests for the project-directory contextvars in ``config/context.py``.

Covers the three-state semantics of ``current_project_dirs`` (None =
hook never ran, ``()`` = configured nowhere, tuple = effective list)
and the fallback ordering of ``get_tool_base_dir``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.config.context import (
    get_all_project_dir_paths,
    get_current_project_dir_source,
    get_current_project_dirs,
    get_tool_base_dir,
    set_current_project_dir,
    set_current_project_dir_source,
    set_current_project_dirs,
    set_current_workspace_dir,
)
from qwenpaw.services.project_directory import ResolvedProjectDir


@pytest.fixture(autouse=True)
def _reset_contextvars():
    """Isolate each test from contextvar leakage across the suite."""
    set_current_project_dirs(None)
    set_current_project_dir(None)
    set_current_project_dir_source(None)
    set_current_workspace_dir(None)
    yield
    set_current_project_dirs(None)
    set_current_project_dir(None)
    set_current_project_dir_source(None)
    set_current_workspace_dir(None)


def test_project_dirs_default_is_none() -> None:
    assert get_current_project_dirs() is None
    assert get_all_project_dir_paths() == []


def test_empty_tuple_means_configured_nowhere() -> None:
    set_current_project_dirs(())
    assert get_current_project_dirs() == ()
    assert get_all_project_dir_paths() == []


def test_paths_are_returned_primary_first(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    set_current_project_dirs(
        (
            ResolvedProjectDir(path=first),
            ResolvedProjectDir(path=second),
        ),
    )
    assert get_all_project_dir_paths() == [first, second]


def test_source_round_trips() -> None:
    assert get_current_project_dir_source() is None
    set_current_project_dir_source("session")
    assert get_current_project_dir_source() == "session"


def test_tool_base_prefers_project_then_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    project = tmp_path / "proj"
    set_current_workspace_dir(workspace)
    assert get_tool_base_dir() == workspace
    set_current_project_dir(project)
    assert get_tool_base_dir() == project


def test_tool_base_falls_back_to_working_dir() -> None:
    from qwenpaw.constant import WORKING_DIR

    assert get_tool_base_dir() == WORKING_DIR
