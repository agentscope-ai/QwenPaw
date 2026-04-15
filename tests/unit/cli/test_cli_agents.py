# -*- coding: utf-8 -*-
"""Tests for the ``qwenpaw agents`` CLI surface."""

from __future__ import annotations

from click.testing import CliRunner

from qwenpaw.cli.main import cli


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
