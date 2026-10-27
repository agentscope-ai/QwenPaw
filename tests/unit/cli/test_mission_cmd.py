# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""Unit tests for the `qwenpaw mission` CLI group.

All three subcommands build a /mission query and POST it to /api/chat/send,
so the tests pin the payload contract the server relies on.
"""

import pytest
from click.testing import CliRunner

from qwenpaw.cli import mission_cmd as mission_mod


class _Response:
    pass


@pytest.fixture()
def http_env(monkeypatch):
    """Capture what the CLI posts instead of opening a socket.

    mission_cmd does `from .http import client, ...`, so the names are bound in
    its own namespace and must be patched there.
    """
    calls = {"posts": [], "urls": [], "printed": []}

    class _Client:
        def __init__(self, url):
            calls["urls"].append(url)

        def post(self, path, json=None):
            calls["posts"].append((path, json))
            return _Response()

    monkeypatch.setattr(mission_mod, "client", _Client)
    monkeypatch.setattr(
        mission_mod,
        "resolve_base_url",
        lambda ctx, base_url: base_url or "http://test",
    )
    monkeypatch.setattr(mission_mod, "print_json", calls["printed"].append)
    return calls


class TestStartBuildsTheQuery:
    def test_single_word_task(self, http_env):
        result = CliRunner().invoke(
            mission_mod.mission_group,
            ["start", "hello", "--base-url", "http://x"],
        )

        assert result.exit_code == 0, result.output
        assert http_env["posts"][0][1]["text"] == "/mission hello"

    def test_joins_a_multi_word_task(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            ["start", "add", "auth", "to", "api", "--base-url", "http://x"],
        )

        assert http_env["posts"][0][1]["text"] == "/mission add auth to api"

    def test_task_is_required(self, http_env):
        result = CliRunner().invoke(
            mission_mod.mission_group,
            ["start", "--base-url", "http://x"],
        )

        assert result.exit_code != 0
        assert http_env["posts"] == []

    def test_verify_flag_is_appended(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            [
                "start",
                "fix",
                "bug",
                "--verify",
                "pytest",
                "--base-url",
                "http://x",
            ],
        )

        assert (
            http_env["posts"][0][1]["text"]
            == "/mission fix bug --verify pytest"
        )

    def test_empty_verify_is_omitted(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            ["start", "fix", "--verify", "", "--base-url", "http://x"],
        )

        assert "--verify" not in http_env["posts"][0][1]["text"]

    def test_default_max_iterations_is_omitted(self, http_env):
        """20 means 'not overridden', so it stays out of the query."""
        CliRunner().invoke(
            mission_mod.mission_group,
            ["start", "fix", "--base-url", "http://x"],
        )

        assert "--max-iterations" not in http_env["posts"][0][1]["text"]

    def test_explicit_max_iterations_is_appended(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            [
                "start",
                "fix",
                "--max-iterations",
                "5",
                "--base-url",
                "http://x",
            ],
        )

        assert "--max-iterations 5" in http_env["posts"][0][1]["text"]

    def test_explicit_twenty_is_also_omitted(self, http_env):
        """The comparison is on value: passing 20 matches the default."""
        CliRunner().invoke(
            mission_mod.mission_group,
            [
                "start",
                "fix",
                "--max-iterations",
                "20",
                "--base-url",
                "http://x",
            ],
        )

        assert "--max-iterations" not in http_env["posts"][0][1]["text"]

    def test_all_three_parts_are_ordered(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            [
                "start",
                "do",
                "work",
                "--verify",
                "pytest",
                "--max-iterations",
                "7",
                "--base-url",
                "http://x",
            ],
        )

        assert (
            http_env["posts"][0][1]["text"]
            == "/mission do work --verify pytest --max-iterations 7"
        )


class TestPayloadContract:
    def test_posts_to_the_chat_send_endpoint(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            ["start", "hi", "--base-url", "http://x"],
        )

        assert http_env["posts"][0][0] == "/api/chat/send"

    def test_defaults_agent_and_session(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            ["start", "hi", "--base-url", "http://x"],
        )

        payload = http_env["posts"][0][1]
        assert payload["agent_id"] == "default"
        assert payload["session_id"] == "mission:default"
        assert payload["user_id"] == "cli"

    def test_agent_option_shapes_the_session_id(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            ["start", "hi", "--agent", "worker", "--base-url", "http://x"],
        )

        payload = http_env["posts"][0][1]
        assert payload["agent_id"] == "worker"
        assert payload["session_id"] == "mission:worker"

    def test_resolved_base_url_is_used_for_the_client(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            ["start", "hi", "--base-url", "http://resolved"],
        )

        assert http_env["urls"] == ["http://resolved"]

    def test_base_url_defaults_when_not_given(self, http_env):
        CliRunner().invoke(mission_mod.mission_group, ["start", "hi"])

        assert http_env["urls"] == ["http://test"]

    def test_response_is_printed(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            ["start", "hi", "--base-url", "http://x"],
        )

        assert len(http_env["printed"]) == 1


class TestStatus:
    def test_sends_the_status_query(self, http_env):
        result = CliRunner().invoke(
            mission_mod.mission_group,
            ["status", "--base-url", "http://x"],
        )

        assert result.exit_code == 0, result.output
        assert http_env["posts"][0][1]["text"] == "/mission status"

    def test_defaults_to_the_default_agent(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            ["status", "--base-url", "http://x"],
        )

        payload = http_env["posts"][0][1]
        assert payload["session_id"] == "mission:default"
        assert payload["user_id"] == "cli"

    def test_honours_the_agent_option(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            ["status", "--agent", "a2", "--base-url", "http://x"],
        )

        assert http_env["posts"][0][1]["session_id"] == "mission:a2"

    def test_posts_to_chat_send_and_prints(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            ["status", "--base-url", "http://x"],
        )

        assert http_env["posts"][0][0] == "/api/chat/send"
        assert len(http_env["printed"]) == 1


class TestList:
    def test_sends_the_list_query(self, http_env):
        result = CliRunner().invoke(
            mission_mod.mission_group,
            ["list", "--base-url", "http://x"],
        )

        assert result.exit_code == 0, result.output
        assert http_env["posts"][0][1]["text"] == "/mission list"

    def test_defaults_to_the_default_agent(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            ["list", "--base-url", "http://x"],
        )

        assert http_env["posts"][0][1]["session_id"] == "mission:default"

    def test_honours_the_agent_option(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            ["list", "--agent", "a3", "--base-url", "http://x"],
        )

        assert http_env["posts"][0][1]["session_id"] == "mission:a3"

    def test_posts_to_chat_send_and_prints(self, http_env):
        CliRunner().invoke(
            mission_mod.mission_group,
            ["list", "--base-url", "http://x"],
        )

        assert http_env["posts"][0][0] == "/api/chat/send"
        assert len(http_env["printed"]) == 1


class TestGroupStructure:
    def test_all_three_subcommands_are_registered(self):
        assert set(mission_mod.mission_group.commands) == {
            "start",
            "status",
            "list",
        }

    def test_group_help_mentions_mission_mode(self):
        result = CliRunner().invoke(mission_mod.mission_group, ["--help"])

        assert result.exit_code == 0
        assert "Mission Mode" in result.output
