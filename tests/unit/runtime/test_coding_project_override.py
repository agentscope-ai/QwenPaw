# -*- coding: utf-8 -*-
"""Session-scoped Coding Mode project overrides."""

from __future__ import annotations

# Tests target request-scope helpers directly.
# pylint: disable=protected-access

import pytest

from qwenpaw.agents.acp.meta import ACP_CODING_PROJECT_META_KEY
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.runtime.prompt_contributors import CodingModeContributor


def test_request_coding_project_enables_clone(tmp_path):
    config = AgentProfileConfig(id="default", name="Default")

    updated = AgentBuilder._apply_request_coding_project(
        config,
        {ACP_CODING_PROJECT_META_KEY: str(tmp_path)},
    )

    assert updated is not config
    assert updated.coding_mode.enabled is True
    assert updated.coding_mode.project_dir == str(tmp_path.resolve())
    assert config.coding_mode.enabled is False
    assert config.coding_mode.project_dir is None


def test_request_coding_project_ignores_non_directory(tmp_path):
    config = AgentProfileConfig(id="default", name="Default")

    updated = AgentBuilder._apply_request_coding_project(
        config,
        {ACP_CODING_PROJECT_META_KEY: str(tmp_path / "missing")},
    )

    assert updated is config
    assert config.coding_mode.enabled is False


@pytest.mark.usefixtures("capture_qwenpaw_logs")
def test_request_coding_project_warns_for_unsupported_config(
    caplog,
    tmp_path,
):
    config = {}

    updated = AgentBuilder._apply_request_coding_project(
        config,
        {ACP_CODING_PROJECT_META_KEY: str(tmp_path)},
    )

    assert updated is config
    assert "unsupported config type: dict" in caplog.text


def test_coding_prompt_prefers_request_project(monkeypatch, tmp_path):
    config = AgentProfileConfig(id="default", name="Default")
    config.coding_mode.enabled = True
    config.coding_mode.project_dir = str(tmp_path)

    def fail_load_agent_config(_agent_id):
        raise AssertionError("request project should be used first")

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        fail_load_agent_config,
    )

    assert CodingModeContributor._resolve_project_dir(config) == str(tmp_path)
