# -*- coding: utf-8 -*-
"""Tests for agent-level runtime backend configuration."""

from qwenpaw.config.config import AgentProfileConfig


def test_agent_backend_defaults_to_qwenpaw() -> None:
    config = AgentProfileConfig(id="agent-1", name="Agent")

    assert config.backend == "qwenpaw"
    assert config.backend_project_dir is None


def test_codex_backend_has_an_independent_project_directory() -> None:
    config = AgentProfileConfig(
        id="codex-1",
        name="Codex",
        backend="codex",
        backend_project_dir="/projects/example",
    )

    assert config.backend == "codex"
    assert config.coding_mode.enabled is False
    assert config.backend_project_dir == "/projects/example"
