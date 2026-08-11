# -*- coding: utf-8 -*-
"""Trusted request-scoped project directory overrides."""

from __future__ import annotations

# Tests target request-scope helpers directly.
# pylint: disable=protected-access

from types import SimpleNamespace

import pytest

from qwenpaw.agents.acp.meta import ACP_PROJECT_DIR_META_KEY
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.runtime.builder import AgentBuilder


def test_request_project_override_does_not_enable_coding_tools(tmp_path):
    config = AgentProfileConfig(id="default", name="Default")

    updated = AgentBuilder._apply_request_project(
        config,
        {ACP_PROJECT_DIR_META_KEY: str(tmp_path)},
    )

    assert updated is not config
    assert updated.coding_mode.enabled is False
    assert updated.project_dir == str(tmp_path.resolve())
    assert config.coding_mode.enabled is False
    assert config.project_dir is None


def test_session_project_override_uses_canonical_request_key(tmp_path):
    config = AgentProfileConfig(id="default", name="Default")

    updated = AgentBuilder._apply_request_project(
        config,
        {"project_dir": str(tmp_path)},
    )

    assert updated is not config
    assert updated.project_dir == str(tmp_path.resolve())
    assert updated.coding_mode.enabled is False


def test_active_mode_project_precedes_session_project(tmp_path):
    active_dir = tmp_path / "active"
    session_dir = tmp_path / "session"
    active_dir.mkdir()
    session_dir.mkdir()
    config = AgentProfileConfig(id="default", name="Default")

    updated = AgentBuilder._apply_request_project(
        config,
        {
            "active_mode_project_dir": str(active_dir),
            "project_dir": str(session_dir),
        },
    )

    assert updated.project_dir == str(active_dir.resolve())


def test_request_project_ignores_non_directory(tmp_path):
    config = AgentProfileConfig(id="default", name="Default")

    updated = AgentBuilder._apply_request_project(
        config,
        {ACP_PROJECT_DIR_META_KEY: str(tmp_path / "missing")},
    )

    assert updated is config
    assert config.coding_mode.enabled is False


@pytest.mark.usefixtures("capture_qwenpaw_logs")
def test_request_project_warns_for_unsupported_config(
    caplog,
    tmp_path,
):
    config = {}

    updated = AgentBuilder._apply_request_project(
        config,
        {ACP_PROJECT_DIR_META_KEY: str(tmp_path)},
    )

    assert updated is config
    assert "unsupported config type: dict" in caplog.text


def test_directory_prompt_prefers_resolved_contextvar(tmp_path):
    """The prompt shows the value resolved in PRE_DISPATCH, never a
    re-derived one from the config."""
    from qwenpaw.config.context import set_current_project_dir
    from qwenpaw.runtime.prompt_contributors import (
        DirectoryContextContributor,
    )

    config = AgentProfileConfig(id="default", name="Default")
    config.project_dir = str(tmp_path / "from-config")
    ctx = SimpleNamespace(
        workspace_dir=tmp_path / "workspace",
        extras={"agent_config": config},
    )
    set_current_project_dir(tmp_path / "resolved")
    try:
        block = DirectoryContextContributor().contribute_sync(ctx)
        assert str(tmp_path / "resolved") in block
        assert "from-config" not in block
    finally:
        set_current_project_dir(None)


def test_directory_prompt_lists_all_roots_with_primary(tmp_path):
    from qwenpaw.config.context import (
        set_current_project_dir,
        set_current_project_dirs,
    )
    from qwenpaw.runtime.prompt_contributors import (
        DirectoryContextContributor,
    )
    from qwenpaw.services.project_directory import ResolvedProjectDir

    primary = tmp_path / "backend"
    extra = tmp_path / "docs"
    config = AgentProfileConfig(id="default", name="Default")
    ctx = SimpleNamespace(
        workspace_dir=tmp_path / "workspace",
        extras={"agent_config": config},
    )
    set_current_project_dir(primary)
    set_current_project_dirs(
        (
            ResolvedProjectDir(path=primary, label="api", exists=True),
            ResolvedProjectDir(path=extra, label=None, exists=True),
        ),
    )
    try:
        block = DirectoryContextContributor().contribute_sync(ctx)
        assert f"1. {primary} (primary) — api" in block
        assert f"2. {extra}" in block
        # Extra-root guidance only appears with more than one root.
        assert "ABSOLUTE path" in block
    finally:
        set_current_project_dir(None)
        set_current_project_dirs(None)


def test_normal_prompt_workspace_fallback_shows_working_directory(tmp_path):
    """Nothing configured: the workspace appears once, as the working
    directory — never re-labelled as a project."""
    config = AgentProfileConfig(id="default", name="Default")
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        agent_id="default",
        session_id="session-1",
        request=SimpleNamespace(
            user_id="user-1",
            channel="console",
            request_context={},
        ),
        workspace=None,
    )

    prompt = AgentBuilder().build_prompt(ctx, config)

    assert f"Working directory: {tmp_path}" in prompt
    assert str(tmp_path) in prompt


def test_normal_prompt_uses_session_project_snapshot(tmp_path):
    workspace_dir = tmp_path / "workspace"
    project_dir = tmp_path / "project"
    workspace_dir.mkdir()
    project_dir.mkdir()
    config = AgentProfileConfig(id="default", name="Default")
    config = AgentBuilder._apply_request_project(
        config,
        {"project_dir": str(project_dir)},
    )
    ctx = SimpleNamespace(
        workspace_dir=workspace_dir,
        agent_id="default",
        session_id="session-1",
        request=SimpleNamespace(
            user_id="user-1",
            channel="console",
            request_context={"project_dir": str(project_dir)},
        ),
        workspace=None,
    )

    prompt = AgentBuilder().build_prompt(ctx, config)

    assert str(project_dir) in prompt
    assert str(workspace_dir) in prompt
    assert "Agent workspace (internal" in prompt
