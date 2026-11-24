# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression tests for agent workspace initialization."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.services import agent_setup


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
        agent_setup,
        "_install_initial_skills",
        lambda workspace_dir, skill_names: None,
    )

    agent_setup.initialize_agent_workspace(tmp_path)

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


@pytest.mark.parametrize("language", ["en", "zh", "ru"])
def test_initialize_agent_workspace_applies_md_template_with_language(
    monkeypatch,
    tmp_path,
    language,
):
    """Workspace initialization should pass language and md_template_id."""
    import qwenpaw.config as config_module

    recorded_calls: list[tuple[str, Path, str | None]] = []

    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda: _stub_global_config(language),
    )
    monkeypatch.setattr(
        agent_setup,
        "copy_workspace_md_files",
        lambda language, workspace_dir, md_template_id=None: (
            recorded_calls.append(
                (language, workspace_dir, md_template_id),
            )
        ),
    )
    monkeypatch.setattr(
        agent_setup,
        "_install_initial_skills",
        lambda workspace_dir, skill_names: None,
    )

    agent_setup.initialize_agent_workspace(
        tmp_path,
        md_template_id="qa",
    )

    assert recorded_calls == [(language, tmp_path, "qa")]
    heartbeat_lines = (
        (tmp_path / "HEARTBEAT.md").read_text(encoding="utf-8").splitlines()
    )
    assert heartbeat_lines[0] == "# Heartbeat checklist"
    assert all(line.startswith("- ") for line in heartbeat_lines[1:])


def test_agent_registration_persists_profile_and_rejects_duplicate(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.config import utils as config_utils
    from qwenpaw.config.config import AgentProfileConfig, AgentProfileRef

    monkeypatch.setattr(config_utils, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(config_utils, "_config_cache", None)
    config = config_utils.load_config()
    config.agents.profiles = {}
    config.agents.agent_order = []
    config_utils.save_config(config)
    workspace = tmp_path / "workspace"
    profile = AgentProfileRef(id="example", workspace_dir=str(workspace))
    agent = AgentProfileConfig(id="example", name="Example")

    agent_setup.register_agent("example", profile, agent)

    saved = config_utils.load_config()
    assert saved.agents.agent_order == ["example"]
    assert saved.agents.profiles["example"] == profile
    agent_file = workspace / "agent.json"
    original = agent_file.read_bytes()
    assert json.loads(original)["name"] == "Example"
    with pytest.raises(ValueError, match="already exists"):
        agent_setup.register_agent("example", profile, agent)
    assert agent_file.read_bytes() == original
