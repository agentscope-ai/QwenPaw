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


def test_initialize_agent_workspace_builtin_qa_seed_passes_language_first(
    monkeypatch,
    tmp_path,
):
    """Builtin QA seeding should pass language before workspace."""
    import qwenpaw.config as config_module

    recorded_calls: list[tuple[str, Path]] = []

    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda: _stub_global_config("ru"),
    )
    monkeypatch.setattr(
        agents_router,
        "copy_builtin_qa_md_files",
        lambda language, workspace_dir: recorded_calls.append(
            (language, workspace_dir),
        ),
    )
    monkeypatch.setattr(
        agents_router,
        "_install_initial_skills",
        lambda workspace_dir, skill_names: None,
    )

    agents_router._initialize_agent_workspace(
        tmp_path,
        builtin_qa_md_seed=True,
    )

    assert recorded_calls == [("ru", tmp_path)]
