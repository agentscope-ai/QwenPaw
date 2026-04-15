# -*- coding: utf-8 -*-
"""Tests for the ``qwenpaw agents`` CLI surface."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from click.testing import CliRunner

from qwenpaw.cli.main import cli
from qwenpaw.constant import BUILTIN_QA_AGENT_SKILL_NAMES
from qwenpaw.providers.models import ModelSlotConfig


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
        lambda workspace_dir, skill_names, md_template_id=None: saved.setdefault(  # noqa: E501
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
        lambda workspace_dir, skill_names, md_template_id=None: saved.setdefault(  # noqa: E501
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


def test_agents_create_local_template_uses_local_md_template(
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
        lambda workspace_dir, skill_names, md_template_id=None: saved.setdefault(  # noqa: E501
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
            "Local Copy",
            "--template",
            "local",
            "--agent-id",
            "local-copy",
            "--workspace-dir",
            str(tmp_path / "local-copy"),
            "--skill",
            "extra-skill",
        ],
    )

    assert result.exit_code == 0
    assert '"id": "local-copy"' in result.output
    assert saved["agent_config"][1].name == "Local Copy"
    assert saved["agent_config"][1].template_id == "local"
    assert saved["workspace_init"][1] == ["make_plan", "extra-skill"]
    assert saved["workspace_init"][2] == "local"
    builtin_tools = saved["agent_config"][1].tools.builtin_tools
    assert builtin_tools["list_agents"].enabled is True
    assert builtin_tools["chat_with_agent"].enabled is True
    assert builtin_tools["read_file"].enabled is True
    assert builtin_tools["write_file"].enabled is True
    assert builtin_tools["edit_file"].enabled is True
    assert builtin_tools["execute_shell_command"].enabled is True


def test_agents_create_sets_active_model_when_requested(
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
        lambda workspace_dir, skill_names, md_template_id=None: saved.setdefault(  # noqa: E501
            "workspace_init",
            (workspace_dir, skill_names, md_template_id),
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd._build_active_model_config",
        lambda provider_id, model_id: ModelSlotConfig(
            provider_id=provider_id,
            model=model_id,
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
            "--provider-id",
            "openai",
            "--model-id",
            "gpt-4.1",
        ],
    )

    assert result.exit_code == 0
    assert saved["agent_config"][1].active_model == ModelSlotConfig(
        provider_id="openai",
        model="gpt-4.1",
    )


def test_agents_create_requires_provider_and_model_together(
    monkeypatch,
) -> None:
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
            "--name",
            "Research Bot",
            "--provider-id",
            "openai",
        ],
    )

    assert result.exit_code != 0
    assert (
        "--provider-id and --model-id must be provided together."
        in result.output
    )


def test_agents_delete_calls_local_api(monkeypatch) -> None:
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "success": True,
        "agent_id": "research",
    }
    response.raise_for_status = Mock()

    client = Mock()
    client.delete.return_value = response

    class _ClientContext:
        def __enter__(self):
            return client

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.create_agent_api_client",
        lambda _base_url: _ClientContext(),
    )

    result = CliRunner().invoke(
        cli,
        ["agents", "delete", "research"],
        input="y\n",
    )

    assert result.exit_code == 0
    client.delete.assert_called_once_with("/agents/research")
    assert (
        "WARNING: You are about to delete agent 'research'." in result.output
    )
    assert "Continue with deletion? [y/N]: y" in result.output
    assert '"agent_id": "research"' in result.output


def test_agents_delete_yes_skips_confirmation(monkeypatch) -> None:
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "success": True,
        "agent_id": "research",
    }
    response.raise_for_status = Mock()

    client = Mock()
    client.delete.return_value = response

    class _ClientContext:
        def __enter__(self):
            return client

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.create_agent_api_client",
        lambda _base_url: _ClientContext(),
    )

    result = CliRunner().invoke(
        cli,
        ["agents", "delete", "research", "--yes"],
    )

    assert result.exit_code == 0
    client.delete.assert_called_once_with("/agents/research")
    assert "Continue with deletion?" not in result.output


def test_agents_delete_remove_workspace_deletes_directory(
    monkeypatch,
    tmp_path,
) -> None:
    workspace_dir = tmp_path / "research"
    workspace_dir.mkdir()
    (workspace_dir / "agent.json").write_text("{}", encoding="utf-8")

    get_response = Mock()
    get_response.status_code = 200
    get_response.json.return_value = {
        "workspace_dir": str(workspace_dir),
    }
    get_response.raise_for_status = Mock()

    delete_response = Mock()
    delete_response.status_code = 200
    delete_response.json.return_value = {
        "success": True,
        "agent_id": "research",
    }
    delete_response.raise_for_status = Mock()

    client = Mock()
    client.get.return_value = get_response
    client.delete.return_value = delete_response

    class _ClientContext:
        def __enter__(self):
            return client

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.create_agent_api_client",
        lambda _base_url: _ClientContext(),
    )

    result = CliRunner().invoke(
        cli,
        ["agents", "delete", "research", "--remove-workspace", "--yes"],
    )

    assert result.exit_code == 0
    client.get.assert_called_once_with("/agents/research")
    client.delete.assert_called_once_with("/agents/research")
    assert not workspace_dir.exists()
    assert '"workspace_removed": true' in result.output
    assert f'"workspace_dir": "{workspace_dir}"' in result.output


def test_agents_delete_rejects_remove_workspace_for_remote_api(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.resolve_base_url",
        lambda _ctx, _base_url: "http://192.168.1.20:8088",
    )

    result = CliRunner().invoke(
        cli,
        ["agents", "delete", "research", "--remove-workspace", "--yes"],
    )

    assert result.exit_code != 0
    assert (
        "--remove-workspace is only supported when targeting a local API."
        in result.output
    )


def test_agents_delete_cancelled_before_api_call(monkeypatch) -> None:
    client = Mock()

    class _ClientContext:
        def __enter__(self):
            return client

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.create_agent_api_client",
        lambda _base_url: _ClientContext(),
    )

    result = CliRunner().invoke(
        cli,
        ["agents", "delete", "research"],
        input="n\n",
    )

    assert result.exit_code != 0
    client.delete.assert_not_called()


def test_agents_delete_surfaces_not_found(monkeypatch) -> None:
    response = Mock()
    response.status_code = 404

    client = Mock()
    client.delete.return_value = response

    class _ClientContext:
        def __enter__(self):
            return client

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.create_agent_api_client",
        lambda _base_url: _ClientContext(),
    )

    result = CliRunner().invoke(
        cli,
        ["agents", "delete", "missing", "--yes"],
    )

    assert result.exit_code != 0
    assert "Agent 'missing' not found." in result.output


def test_agents_delete_surfaces_api_detail(monkeypatch) -> None:
    response = Mock()
    response.status_code = 400
    response.json.return_value = {
        "detail": "Cannot delete the default agent",
    }

    client = Mock()
    client.delete.return_value = response

    class _ClientContext:
        def __enter__(self):
            return client

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.create_agent_api_client",
        lambda _base_url: _ClientContext(),
    )

    result = CliRunner().invoke(
        cli,
        ["agents", "delete", "default", "--yes"],
    )

    assert result.exit_code != 0
    assert "Cannot delete the default agent" in result.output
