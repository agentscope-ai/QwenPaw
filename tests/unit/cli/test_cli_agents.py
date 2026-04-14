# -*- coding: utf-8 -*-
"""Tests for the ``qwenpaw agents`` CLI surface."""

from __future__ import annotations

from types import SimpleNamespace

from click.testing import CliRunner

from qwenpaw.cli.main import cli
from qwenpaw.constant import BUILTIN_QA_AGENT_SKILL_NAMES


def test_agents_list_uses_shared_tool_helper(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.list_agents_data",
        lambda _base_url: {
            "agents": [
                {
                    "id": "bot_a",
                    "name": "Bot A",
                    "description": "helper",
                    "workspace_dir": "/tmp/bot_a",
                    "enabled": True,
                },
            ],
        },
    )

    result = CliRunner().invoke(cli, ["agents", "list"])

    assert result.exit_code == 0
    assert '"id": "bot_a"' in result.output


def test_agents_chat_uses_shared_request_builder(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.build_agent_chat_request",
        lambda *_args, **_kwargs: (
            "sid-123",
            {"session_id": "sid-123", "input": []},
            True,
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.collect_final_agent_chat_response",
        lambda *_args, **_kwargs: {
            "output": [
                {
                    "content": [
                        {"type": "text", "text": "tool-backed reply"},
                    ],
                },
            ],
        },
    )

    result = CliRunner().invoke(
        cli,
        [
            "agents",
            "chat",
            "--from-agent",
            "bot_a",
            "--to-agent",
            "bot_b",
            "--text",
            "hello",
        ],
    )

    assert result.exit_code == 0
    assert "[SESSION: sid-123]" in result.output
    assert "tool-backed reply" in result.output


def test_agents_chat_help_no_longer_exposes_new_session_flag() -> None:
    result = CliRunner().invoke(cli, ["agents", "chat", "--help"])

    assert result.exit_code == 0
    assert "--new-session" not in result.output
    assert "--session-id" in result.output


def test_agents_create_uses_explicit_agent_id(monkeypatch, tmp_path) -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={},
            agent_order=[],
            language="zh",
        ),
    )
    saved = {}

    monkeypatch.setattr("qwenpaw.cli.agents_cmd.load_config", lambda: config)
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.save_config",
        lambda updated_config: saved.setdefault("config", updated_config),
    )
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.save_agent_config",
        lambda agent_id, agent_config: saved.setdefault(
            "agent_config",
            (agent_id, agent_config),
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd._initialize_new_agent_workspace",
        lambda
        workspace_dir,
        skill_names,
        md_template_id=None: saved.setdefault(
            "workspace_init",
            (workspace_dir, skill_names, md_template_id),
        ),
    )

    result = CliRunner().invoke(
        cli,
        [
            "agents",
            "create",
            "--name",
            "Research Bot",
            "--agent-id",
            "research",
            "--workspace-dir",
            str(tmp_path / "research"),
            "--skill",
            "calendar",
            "--skill",
            "search",
        ],
    )

    assert result.exit_code == 0
    assert '"id": "research"' in result.output
    assert "research" in config.agents.profiles
    assert config.agents.agent_order == ["research"]
    assert saved["agent_config"][0] == "research"
    assert saved["agent_config"][1].template_id == "default"
    assert saved["agent_config"][1].description == ""
    assert saved["agent_config"][1].language == "zh"
    assert saved["workspace_init"][1] == ["calendar", "search"]
    assert saved["workspace_init"][2] is None


def test_agents_create_rejects_duplicate_explicit_agent_id(
    monkeypatch,
    tmp_path,
) -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "existing": SimpleNamespace(
                    id="existing",
                    workspace_dir=str(tmp_path / "existing"),
                    enabled=True,
                ),
            },
            agent_order=["existing"],
        ),
    )

    monkeypatch.setattr("qwenpaw.cli.agents_cmd.load_config", lambda: config)

    result = CliRunner().invoke(
        cli,
        [
            "agents",
            "create",
            "--name",
            "Research Bot",
            "--agent-id",
            "existing",
        ],
    )

    assert result.exit_code != 0
    assert "Agent 'existing' already exists." in result.output


def test_agents_create_requires_name_without_template(monkeypatch) -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={},
            agent_order=[],
            language="zh",
        ),
    )

    monkeypatch.setattr("qwenpaw.cli.agents_cmd.load_config", lambda: config)

    result = CliRunner().invoke(cli, ["agents", "create"])

    assert result.exit_code != 0
    assert "Missing option '--name'." in result.output


def test_agents_create_requires_name_with_template(monkeypatch) -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={},
            agent_order=[],
            language="zh",
        ),
    )

    monkeypatch.setattr("qwenpaw.cli.agents_cmd.load_config", lambda: config)

    result = CliRunner().invoke(
        cli,
        [
            "agents",
            "create",
            "--template",
            "qa",
        ],
    )

    assert result.exit_code != 0
    assert "Missing option '--name'." in result.output


def test_agents_create_qa_template_uses_template_defaults(
    monkeypatch,
    tmp_path,
) -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={},
            agent_order=[],
            language="zh",
        ),
    )
    saved = {}

    monkeypatch.setattr("qwenpaw.cli.agents_cmd.load_config", lambda: config)
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.save_config",
        lambda updated_config: saved.setdefault("config", updated_config),
    )
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.save_agent_config",
        lambda agent_id, agent_config: saved.setdefault(
            "agent_config",
            (agent_id, agent_config),
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd._initialize_new_agent_workspace",
        lambda
        workspace_dir,
        skill_names,
        md_template_id=None: saved.setdefault(
            "workspace_init",
            (workspace_dir, skill_names, md_template_id),
        ),
    )

    result = CliRunner().invoke(
        cli,
        [
            "agents",
            "create",
            "--name",
            "QA Copy",
            "--template",
            "qa",
            "--agent-id",
            "qa-copy",
            "--workspace-dir",
            str(tmp_path / "qa-copy"),
            "--skill",
            "extra-skill",
        ],
    )

    assert result.exit_code == 0
    assert '"id": "qa-copy"' in result.output
    assert saved["agent_config"][1].name == "QA Copy"
    assert saved["agent_config"][1].language == "zh"
    assert saved["workspace_init"][1] == [
        *BUILTIN_QA_AGENT_SKILL_NAMES,
        "extra-skill",
    ]
    assert saved["workspace_init"][2] == "qa"
