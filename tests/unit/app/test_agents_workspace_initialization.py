# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression tests for agent workspace initialization."""

import json
from pathlib import Path
from types import SimpleNamespace

from qwenpaw.app.routers import agents as agents_router


def _stub_global_config(language: str = "en") -> SimpleNamespace:
    return SimpleNamespace(
        agents=SimpleNamespace(language=language),
    )


def test_initialize_agent_workspace_creates_runtime_compatible_files(
    monkeypatch,
    tmp_path,
):
    """New workspaces should match the runtime file contract."""
    import qwenpaw.config as config_module

    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda: _stub_global_config("en"),
    )
    monkeypatch.setattr(
        agents_router,
        "_install_initial_skills",
        lambda workspace_dir, skill_names: None,
    )

    agents_router._initialize_agent_workspace(tmp_path)

    assert (tmp_path / "sessions").is_dir()
    assert (tmp_path / "memory").is_dir()
    assert (tmp_path / "skills").is_dir()
    assert (tmp_path / "media").is_dir()
    assert (tmp_path / "artifacts").is_dir()
    assert not (tmp_path / "资料").exists()
    assert not (tmp_path / "产物").exists()
    assert not (tmp_path / "active_skills").exists()
    assert not (tmp_path / "customized_skills").exists()
    assert json.loads(
        (tmp_path / "jobs.json").read_text(encoding="utf-8"),
    ) == {
        "version": 1,
        "jobs": [],
    }
    assert json.loads(
        (tmp_path / "chats.json").read_text(encoding="utf-8"),
    ) == {
        "version": 1,
        "chats": [],
    }


def test_initialize_agent_workspace_applies_md_template_with_language(
    monkeypatch,
    tmp_path,
):
    """Workspace initialization should pass language and md_template_id."""
    import qwenpaw.config as config_module

    recorded_calls: list[tuple[str, Path, str | None]] = []

    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda: _stub_global_config("ru"),
    )
    monkeypatch.setattr(
        agents_router,
        "copy_workspace_md_files",
        lambda language, workspace_dir, md_template_id=None: (
            recorded_calls.append(
                (language, workspace_dir, md_template_id),
            )
        ),
    )
    monkeypatch.setattr(
        agents_router,
        "_install_initial_skills",
        lambda workspace_dir, skill_names: None,
    )

    agents_router._initialize_agent_workspace(
        tmp_path,
        md_template_id="qa",
    )

    assert recorded_calls == [("ru", tmp_path, "qa")]


def test_backfill_agent_workspace_md_files_only_adds_missing_files(
    monkeypatch,
    tmp_path,
):
    """切换工作目录后应补齐旧 Agent 档案，但不得覆盖现有内容。"""
    existing = tmp_path / "SOUL.md"
    existing.write_text("custom soul", encoding="utf-8")

    monkeypatch.setattr(
        agents_router,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(language="zh"),
    )

    copied = agents_router.ensure_agent_workspace_md_files(
        "legacy-agent",
        tmp_path,
    )

    assert existing.read_text(encoding="utf-8") == "custom soul"
    assert set(copied) == {
        "AGENTS.md",
        "HEARTBEAT.md",
        "MEMORY.md",
        "PROFILE.md",
    }
    assert not (tmp_path / "BOOTSTRAP.md").exists()


def test_backfill_all_agent_workspaces_uses_configured_directories(
    monkeypatch,
    tmp_path,
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "a": SimpleNamespace(workspace_dir=str(first)),
                "b": SimpleNamespace(workspace_dir=str(second)),
            },
        ),
    )
    calls: list[tuple[str, Path]] = []
    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(
        agents_router,
        "ensure_agent_workspace_md_files",
        lambda agent_id, workspace: calls.append((agent_id, Path(workspace)))
        or ["MEMORY.md"],
    )

    assert agents_router.ensure_all_agent_workspace_md_files() == 2
    assert calls == [("a", first), ("b", second)]
