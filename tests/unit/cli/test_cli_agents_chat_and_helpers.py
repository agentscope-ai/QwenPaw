# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Unit tests for ``agents`` CLI chat plumbing and module-level helpers.

The existing ``test_cli_agents.py`` covers ``list`` / ``create`` /
``delete`` happy paths.  This file covers the background-task surface
(``_validate_chat_parameters`` / ``_submit_background_task`` /
``_check_task_status``), the response-mode helpers and the remaining
pure module-level helpers of ``qwenpaw.cli.agents_cmd``.

Every test stubs the HTTP boundary (``agent_tools`` / ``httpx.Client``)
so no local API server is started.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import click
import httpx
import pytest
from click.testing import CliRunner

from qwenpaw.cli import agents_cmd as mod
from qwenpaw.cli.main import cli
from qwenpaw.config.config import ModelSlotConfig

# --------------------------------------------------------------------- #
# shared stubs
# --------------------------------------------------------------------- #


def _stub_chat_request(monkeypatch, session_id="sid-1"):
    """Stub ``build_agent_chat_request`` so no payload building happens."""
    calls: dict = {}
    wanted = session_id

    def _fake(to_agent, text, session_id=None, from_agent=None):
        calls["args"] = (to_agent, text, session_id, from_agent)
        return (
            wanted,
            {"session_id": wanted, "input": [{"type": "text"}]},
            False,
        )

    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.build_agent_chat_request",
        _fake,
    )
    return calls


def _chat_args(*extra: str) -> list[str]:
    """Minimal foreground chat invocation plus extra flags."""
    return [
        "agents",
        "chat",
        "--from-agent",
        "bot_a",
        "--to-agent",
        "bot_b",
        "--text",
        "hello",
        *extra,
    ]


# --------------------------------------------------------------------- #
# _extract_and_print_text
# --------------------------------------------------------------------- #


def test_extract_and_print_text_reports_missing_text_to_stderr() -> None:
    """An empty text payload must be reported on stderr, not stdout."""
    out, err = _capture_streams(
        mod._extract_and_print_text,
        {"output": [{"content": [{"type": "image"}]}]},
        session_id=None,
    )

    assert out == ""
    assert "(No text content in response)" in err


def test_extract_and_print_text_prints_session_header_and_text() -> None:
    out, err = _capture_streams(
        mod._extract_and_print_text,
        {
            "output": [
                {
                    "content": [
                        {"type": "text", "text": "first"},
                        {"type": "text", "text": "second"},
                    ],
                },
            ],
        },
        session_id="sid-9",
    )

    assert out.splitlines() == ["[SESSION: sid-9]", "", "first", "second"]
    assert err == ""


def _capture_streams(func, *args, **kwargs):
    """Return (stdout_text, stderr_text) produced by *func*."""
    runner = CliRunner()
    with runner.isolation() as streams:
        func(*args, **kwargs)
    stdout = streams[0].getvalue().decode("utf-8")
    stderr = streams[1].getvalue().decode("utf-8")
    return stdout, stderr


# --------------------------------------------------------------------- #
# _handle_stream_mode / _handle_final_mode
# --------------------------------------------------------------------- #


def test_handle_stream_mode_delegates_to_shared_streamer(
    monkeypatch,
) -> None:
    seen: dict = {}

    def _fake(base_url, payload, to_agent, timeout, line_handler=None):
        seen["call"] = (base_url, payload, to_agent, timeout)
        seen["handler"] = line_handler
        line_handler("chunk-1")
        return ["chunk-1"]

    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.stream_agent_chat",
        _fake,
    )
    _stub_chat_request(monkeypatch)

    result = CliRunner().invoke(cli, _chat_args("--mode", "stream"))

    assert result.exit_code == 0
    assert "chunk-1" in result.output
    assert seen["call"][0] == "http://127.0.0.1:8088"
    assert seen["call"][2] == "bot_b"
    assert seen["call"][3] == 300
    assert seen["handler"] is not None


def test_handle_final_mode_without_response_warns(monkeypatch) -> None:
    _stub_chat_request(monkeypatch)
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools."
        "collect_final_agent_chat_response",
        lambda *a, **k: None,
    )

    result = CliRunner().invoke(cli, _chat_args())

    assert result.exit_code == 0
    assert "(No response received)" in result.stderr


def test_handle_final_mode_json_output_injects_session_id(
    monkeypatch,
) -> None:
    _stub_chat_request(monkeypatch, session_id="sid-json")
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools."
        "collect_final_agent_chat_response",
        lambda *a, **k: {"output": [{"content": []}]},
    )

    result = CliRunner().invoke(cli, _chat_args("--json-output"))

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["session_id"] == "sid-json"


def test_handle_final_mode_json_output_keeps_existing_session_id(
    monkeypatch,
) -> None:
    _stub_chat_request(monkeypatch, session_id="sid-json")
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools."
        "collect_final_agent_chat_response",
        lambda *a, **k: {"session_id": "server-side", "output": []},
    )

    result = CliRunner().invoke(cli, _chat_args("--json-output"))

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["session_id"] == "server-side"


def test_handle_final_mode_text_output_prints_reply(monkeypatch) -> None:
    _stub_chat_request(monkeypatch, session_id="sid-text")
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools."
        "collect_final_agent_chat_response",
        lambda *a, **k: {
            "output": [
                {"content": [{"type": "text", "text": "the answer"}]},
            ],
        },
    )

    result = CliRunner().invoke(cli, _chat_args())

    assert result.exit_code == 0
    assert "[SESSION: sid-text]" in result.stdout
    assert "the answer" in result.stdout


# --------------------------------------------------------------------- #
# _validate_chat_parameters
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ["agents", "chat", "--to-agent", "b", "--text", "t"],
            "--from-agent is required",
        ),
        (
            ["agents", "chat", "--from-agent", "a", "--text", "t"],
            "--to-agent is required",
        ),
        (
            ["agents", "chat", "--from-agent", "a", "--to-agent", "b"],
            "--text is required",
        ),
    ],
)
def test_validate_chat_parameters_requires_triplet(argv, expected) -> None:
    result = CliRunner().invoke(cli, argv)

    assert result.exit_code == 1
    assert expected in result.stderr


def test_validate_chat_parameters_rejects_task_id_without_background() -> None:
    result = CliRunner().invoke(
        cli,
        _chat_args("--task-id", "t-1"),
    )

    assert result.exit_code == 1
    assert "--task-id requires --background flag" in result.stderr


def test_validate_chat_parameters_rejects_background_with_stream() -> None:
    result = CliRunner().invoke(
        cli,
        _chat_args("--background", "--mode", "stream"),
    )

    assert result.exit_code == 1
    assert (
        "--background and --mode stream are mutually exclusive"
        in result.stderr
    )


def test_validate_chat_parameters_rejects_missing_triplet() -> None:
    """Without ``--background --task-id`` all three inputs are mandatory."""
    ctx = click.Context(click.Command("chat"))

    with pytest.raises(click.exceptions.Exit) as excinfo:
        mod._validate_chat_parameters(
            ctx,
            background=False,
            task_id=None,
            from_agent=None,
            to_agent=None,
            text=None,
            mode="final",
        )

    assert excinfo.value.exit_code == 1


def test_validate_chat_parameters_accepts_status_probe() -> None:
    ctx = click.Context(click.Command("chat"))

    mod._validate_chat_parameters(
        ctx,
        background=True,
        task_id="t-1",
        from_agent=None,
        to_agent=None,
        text=None,
        mode="final",
    )


# --------------------------------------------------------------------- #
# _submit_background_task
# --------------------------------------------------------------------- #


def _run_background(monkeypatch, submit_result, submit_error=None):
    _stub_chat_request(monkeypatch, session_id="sid-bg")
    calls: dict = {}

    def _fake(base_url, payload, to_agent, timeout, task_timeout=None):
        calls["args"] = (base_url, to_agent, timeout, task_timeout)
        if submit_error is not None:
            raise submit_error
        return submit_result

    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.submit_agent_chat_task",
        _fake,
    )
    result = CliRunner().invoke(
        cli,
        _chat_args("--background", "--task-timeout", "90"),
    )
    return result, calls


def test_submit_background_task_prints_task_and_session_ids(
    monkeypatch,
) -> None:
    result, calls = _run_background(
        monkeypatch,
        {"task_id": "task-42"},
    )

    assert result.exit_code == 0
    assert "[TASK_ID: task-42]" in result.stdout
    assert "[SESSION: sid-bg]" in result.stdout
    assert "Task submitted successfully" in result.stdout
    assert (
        "qwenpaw agents chat --background --task-id task-42" in result.stdout
    )
    assert calls["args"][3] == 90.0


def test_submit_background_task_sets_headless_tool_guard(
    monkeypatch,
) -> None:
    _stub_chat_request(monkeypatch, session_id="sid-bg")
    seen: dict = {}

    def _fake(base_url, payload, to_agent, timeout, task_timeout=None):
        seen["payload"] = payload
        return {"task_id": "task-1"}

    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.submit_agent_chat_task",
        _fake,
    )

    result = CliRunner().invoke(cli, _chat_args("--background"))

    assert result.exit_code == 0
    assert seen["payload"]["request_context"] == {
        "_headless_tool_guard": "false",
    }


def test_submit_background_task_surfaces_server_error(monkeypatch) -> None:
    result, _calls = _run_background(
        monkeypatch,
        {"error": "A task is already running for this chat"},
    )

    assert result.exit_code == 0
    assert "ERROR: A task is already running for this chat" in result.stderr
    assert "[TASK_ID:" not in result.stdout


def test_submit_background_task_rejects_missing_task_id(monkeypatch) -> None:
    result, _calls = _run_background(monkeypatch, {})

    assert result.exit_code == 0
    assert "ERROR: No task_id returned from server" in result.stderr


def test_submit_background_task_aborts_on_transport_error(
    monkeypatch,
) -> None:
    result, _calls = _run_background(
        monkeypatch,
        {},
        submit_error=RuntimeError("connection refused"),
    )

    assert result.exit_code == 1
    assert "ERROR: Failed to submit task: connection refused" in result.stderr


# --------------------------------------------------------------------- #
# _check_task_status
# --------------------------------------------------------------------- #


def _run_status(monkeypatch, status_result, status_error=None):
    calls: dict = {}

    def _fake(base_url, task_id, to_agent=None, timeout=10):
        calls["args"] = (base_url, task_id, to_agent, timeout)
        if status_error is not None:
            raise status_error
        return status_result

    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.get_agent_chat_task_status",
        _fake,
    )
    result = CliRunner().invoke(
        cli,
        ["agents", "chat", "--background", "--task-id", "task-7"],
    )
    return result, calls


def test_check_task_status_json_output_prints_raw_payload(
    monkeypatch,
) -> None:
    payload = {"status": "running", "started_at": "now"}
    calls = _stub_status(monkeypatch, payload)

    result = CliRunner().invoke(
        cli,
        [
            "agents",
            "chat",
            "--background",
            "--task-id",
            "task-7",
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == payload
    assert calls.seen[1] == "task-7"
    assert calls.seen[3] == 10


def test_check_task_status_finished_completed_prints_text(
    monkeypatch,
) -> None:
    result, _calls = _run_status(
        monkeypatch,
        {
            "status": "finished",
            "result": {
                "status": "completed",
                "session_id": "sid-done",
                "output": [
                    {"content": [{"type": "text", "text": "all good"}]},
                ],
            },
        },
    )

    assert result.exit_code == 0
    assert "[STATUS: finished]" in result.stdout
    assert "Task completed" in result.stdout
    assert "[SESSION: sid-done]" in result.stdout
    assert "all good" in result.stdout


def test_check_task_status_finished_failed_prints_error(monkeypatch) -> None:
    result, _calls = _run_status(
        monkeypatch,
        {
            "status": "finished",
            "result": {
                "status": "failed",
                "error": {"message": "boom"},
            },
        },
    )

    assert result.exit_code == 0
    assert "Task failed" in result.stdout
    assert "Error: boom" in result.stdout


def test_check_task_status_finished_failed_defaults_error_text(
    monkeypatch,
) -> None:
    result, _calls = _run_status(
        monkeypatch,
        {"status": "finished", "result": {"status": "failed"}},
    )

    assert result.exit_code == 0
    assert "Error: Unknown error" in result.stdout


def test_check_task_status_finished_other_dumps_payload(monkeypatch) -> None:
    payload = {
        "status": "finished",
        "result": {"status": "cancelled"},
    }
    result, _calls = _run_status(monkeypatch, payload)

    assert result.exit_code == 0
    assert "Status: cancelled" in result.stdout
    assert json.loads(result.stdout.split("Status: cancelled\n", 1)[1]) == (
        payload
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("running", "Task is still running..."),
        ("pending", "Task is pending in queue..."),
        ("submitted", "Task submitted, waiting to start..."),
    ],
)
def test_check_task_status_in_flight_states(status, expected, monkeypatch):
    result, _calls = _run_status(
        monkeypatch,
        {"status": status, "started_at": "2026-09-20T12:00:00"},
    )

    assert result.exit_code == 0
    assert expected in result.stdout
    assert "qwenpaw agents chat --background --task-id task-7" in result.stdout


def test_check_task_status_running_defaults_started_at(monkeypatch) -> None:
    result, _calls = _run_status(monkeypatch, {"status": "running"})

    assert result.exit_code == 0
    assert "Started at: N/A" in result.stdout


def test_check_task_status_unknown_status_dumps_payload(monkeypatch) -> None:
    payload = {"status": "weird"}
    result, _calls = _run_status(monkeypatch, payload)

    assert result.exit_code == 0
    assert "Unknown status: weird" in result.stdout
    assert json.loads(
        result.stdout.split("Unknown status: weird\n", 1)[1],
    ) == (payload)


def test_check_task_status_missing_status_reports_unknown(
    monkeypatch,
) -> None:
    result, _calls = _run_status(monkeypatch, {})

    assert result.exit_code == 0
    assert "[STATUS: unknown]" in result.stdout
    assert "Unknown status: unknown" in result.stdout


def test_check_task_status_forwards_to_agent_and_base_url(
    monkeypatch,
) -> None:
    stub = _stub_status(monkeypatch, {"status": "running"})

    result = CliRunner().invoke(
        cli,
        [
            "agents",
            "chat",
            "--background",
            "--task-id",
            "task-7",
            "--to-agent",
            "bot_b",
            "--base-url",
            "http://example.test:9999/",
        ],
    )

    assert result.exit_code == 0
    assert stub.seen == (
        "http://example.test:9999",
        "task-7",
        "bot_b",
        10,
    )


def _stub_status(monkeypatch, status_result):
    def _fake(base_url, task_id, to_agent=None, timeout=10):
        _fake.seen = (base_url, task_id, to_agent, timeout)
        return status_result

    _fake.seen = None
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.agent_tools.get_agent_chat_task_status",
        _fake,
    )
    return _fake


def test_check_task_status_http_404_reports_expiry(monkeypatch) -> None:
    request = httpx.Request("GET", "http://x/console/chat/task/task-7")
    response = httpx.Response(404, request=request)
    error = httpx.HTTPStatusError(
        "not found",
        request=request,
        response=response,
    )

    result, _calls = _run_status(monkeypatch, {}, status_error=error)

    assert result.exit_code == 1
    assert "Task not found: task-7" in result.stderr
    assert "Task may have expired or never existed" in result.stderr


def test_check_task_status_http_500_reports_error(monkeypatch) -> None:
    request = httpx.Request("GET", "http://x/console/chat/task/task-7")
    response = httpx.Response(500, request=request)
    error = httpx.HTTPStatusError(
        "server blew up",
        request=request,
        response=response,
    )

    result, _calls = _run_status(monkeypatch, {}, status_error=error)

    assert result.exit_code == 1
    assert "ERROR: server blew up" in result.stderr


def test_check_task_status_http_error_without_response(monkeypatch) -> None:
    request = httpx.Request("GET", "http://x/console/chat/task/task-7")
    error = httpx.HTTPStatusError(
        "no response attached",
        request=request,
        response=None,
    )

    result, _calls = _run_status(monkeypatch, {}, status_error=error)

    assert result.exit_code == 1
    assert "ERROR: no response attached" in result.stderr


def test_check_task_status_generic_error_aborts(monkeypatch) -> None:
    result, _calls = _run_status(
        monkeypatch,
        {},
        status_error=RuntimeError("socket closed"),
    )

    assert result.exit_code == 1
    assert "ERROR: socket closed" in result.stderr


# --------------------------------------------------------------------- #
# _normalized_agent_order
# --------------------------------------------------------------------- #


def test_normalized_agent_order_dedupes_and_appends_missing() -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "a": object(),
                "b": object(),
                "ghost": object(),
            },
            agent_order=["b", "b", "ghost-not-in-profiles", "a"],
        ),
    )

    assert mod._normalized_agent_order(config) == ["b", "a", "ghost"]


def test_normalized_agent_order_ignores_unknown_ordered_ids() -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={"only": object()},
            agent_order=["removed"],
        ),
    )

    assert mod._normalized_agent_order(config) == ["only"]


# --------------------------------------------------------------------- #
# _generate_agent_id
# --------------------------------------------------------------------- #


def _config_with(profile_ids):
    return SimpleNamespace(
        agents=SimpleNamespace(
            profiles={name: object() for name in profile_ids},
            agent_order=list(profile_ids),
        ),
    )


def test_generate_agent_id_returns_explicit_id() -> None:
    config = _config_with(["existing"])

    assert mod._generate_agent_id(config, "fresh") == "fresh"


def test_generate_agent_id_rejects_duplicate_explicit_id() -> None:
    config = _config_with(["existing"])

    with pytest.raises(click.ClickException) as excinfo:
        mod._generate_agent_id(config, "existing")

    assert "Agent 'existing' already exists." in excinfo.value.message


def test_generate_agent_id_creates_unique_id(monkeypatch) -> None:
    config = _config_with(["taken"])
    generated = iter(["taken", "fresh"])
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.generate_short_agent_id",
        lambda: next(generated),
    )

    assert mod._generate_agent_id(config, None) == "fresh"


def test_generate_agent_id_gives_up_after_ten_attempts(monkeypatch) -> None:
    config = _config_with(["taken"])
    attempts: list[int] = []

    def _always_taken():
        attempts.append(1)
        return "taken"

    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.generate_short_agent_id",
        _always_taken,
    )

    with pytest.raises(click.ClickException) as excinfo:
        mod._generate_agent_id(config, None)

    assert (
        "Failed to generate unique agent ID after 10 attempts."
        in excinfo.value.message
    )
    assert len(attempts) == 10


# --------------------------------------------------------------------- #
# _build_agent_workspace_dir
# --------------------------------------------------------------------- #


def test_build_agent_workspace_dir_honours_explicit_value(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("qwenpaw.cli.agents_cmd.WORKING_DIR", tmp_path)
    explicit = tmp_path / "explicit"

    assert mod._build_agent_workspace_dir("a1", str(explicit)) == explicit


def test_build_agent_workspace_dir_treats_blank_as_unset(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("qwenpaw.cli.agents_cmd.WORKING_DIR", tmp_path)

    resolved = mod._build_agent_workspace_dir("a1", "   ")

    assert resolved == (tmp_path / "workspaces" / "a1").expanduser()


def test_build_agent_workspace_dir_defaults_under_working_dir(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("qwenpaw.cli.agents_cmd.WORKING_DIR", tmp_path)

    resolved = mod._build_agent_workspace_dir("a2", None)

    assert resolved == tmp_path / "workspaces" / "a2"


# --------------------------------------------------------------------- #
# _initialize_new_agent_workspace
# --------------------------------------------------------------------- #


def test_initialize_new_agent_workspace_delegates(monkeypatch) -> None:
    seen: dict = {}

    def _fake(workspace_dir, skill_names=None, md_template_id=None):
        seen["call"] = (workspace_dir, skill_names, md_template_id)

    monkeypatch.setattr(
        "qwenpaw.app.routers.agents._initialize_agent_workspace",
        _fake,
    )
    target = Path("/tmp/ws-target")

    mod._initialize_new_agent_workspace(
        target,
        ["skill-a"],
        md_template_id="qa",
    )

    assert seen["call"] == (target, ["skill-a"], "qa")


# --------------------------------------------------------------------- #
# _build_active_model_config
# --------------------------------------------------------------------- #


def test_build_active_model_config_returns_none_without_inputs() -> None:
    assert mod._build_active_model_config(None, None) is None


def test_build_active_model_config_normalizes_blank_inputs() -> None:
    assert mod._build_active_model_config("  ", None) is None


@pytest.mark.parametrize(
    ("provider_id", "model_id"),
    [("openai", None), (None, "gpt-4.1"), ("  ", "gpt-4.1")],
)
def test_build_active_model_config_requires_pair(
    provider_id,
    model_id,
) -> None:
    with pytest.raises(click.ClickException) as excinfo:
        mod._build_active_model_config(provider_id, model_id)

    assert (
        "--provider-id and --model-id must be provided together."
        in excinfo.value.message
    )


def _stub_provider(monkeypatch, provider):
    manager = Mock()
    manager.get_provider.return_value = provider
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.ProviderManager.get_instance",
        staticmethod(lambda: manager),
    )
    return manager


def test_build_active_model_config_rejects_unknown_provider(
    monkeypatch,
) -> None:
    _stub_provider(monkeypatch, None)

    with pytest.raises(click.ClickException) as excinfo:
        mod._build_active_model_config("nope", "gpt-4.1")

    assert "Provider 'nope' not found." in excinfo.value.message


def test_build_active_model_config_rejects_unknown_model(monkeypatch) -> None:
    provider = SimpleNamespace(id="openai", has_model=lambda _m: False)
    _stub_provider(monkeypatch, provider)

    with pytest.raises(click.ClickException) as excinfo:
        mod._build_active_model_config("openai", "gpt-9")

    assert (
        "Model 'gpt-9' not found in provider 'openai'."
        in excinfo.value.message
    )


def test_build_active_model_config_builds_slot(monkeypatch) -> None:
    provider = SimpleNamespace(id="openai", has_model=lambda m: m == "gpt-4")
    manager = _stub_provider(monkeypatch, provider)

    slot = mod._build_active_model_config("openai", "gpt-4")

    assert slot == ModelSlotConfig(provider_id="openai", model="gpt-4")
    manager.get_provider.assert_called_once_with("openai")


# --------------------------------------------------------------------- #
# _fetch_agent_workspace_dir
# --------------------------------------------------------------------- #


def test_fetch_agent_workspace_dir_raises_on_404() -> None:
    client = Mock()
    response = Mock()
    response.status_code = 404
    client.get.return_value = response

    with pytest.raises(click.ClickException) as excinfo:
        mod._fetch_agent_workspace_dir(client, "ghost")

    assert "Agent 'ghost' not found." in excinfo.value.message
    response.raise_for_status.assert_not_called()


def test_fetch_agent_workspace_dir_returns_none_when_unset() -> None:
    client = Mock()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"workspace_dir": ""}
    client.get.return_value = response

    assert mod._fetch_agent_workspace_dir(client, "a1") is None
    response.raise_for_status.assert_called_once_with()


def test_fetch_agent_workspace_dir_expands_user(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/home-under-test")
    client = Mock()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"workspace_dir": "~/agents/a1"}
    client.get.return_value = response

    resolved = mod._fetch_agent_workspace_dir(client, "a1")

    assert resolved == Path("/tmp/home-under-test/agents/a1")
    client.get.assert_called_once_with("/agents/a1")


# --------------------------------------------------------------------- #
# _remove_agent_workspace
# --------------------------------------------------------------------- #


def test_remove_agent_workspace_returns_false_when_absent(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("qwenpaw.cli.agents_cmd.WORKING_DIR", tmp_path)

    assert mod._remove_agent_workspace(tmp_path / "missing") is False


def test_remove_agent_workspace_deletes_directory(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("qwenpaw.cli.agents_cmd.WORKING_DIR", tmp_path)
    target = tmp_path / "workspaces" / "a1"
    target.mkdir(parents=True)
    (target / "agent.json").write_text("{}", encoding="utf-8")

    assert mod._remove_agent_workspace(target) is True
    assert not target.exists()


def test_remove_agent_workspace_rejects_path_outside_working_dir(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("qwenpaw.cli.agents_cmd.WORKING_DIR", tmp_path / "in")
    (tmp_path / "in").mkdir()

    with pytest.raises(click.ClickException) as excinfo:
        mod._remove_agent_workspace(tmp_path / "outside")

    assert "Cannot delete workspace outside WORKING_DIR" in (
        excinfo.value.message
    )


def test_remove_agent_workspace_surfaces_oserror(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("qwenpaw.cli.agents_cmd.WORKING_DIR", tmp_path)
    target = tmp_path / "workspaces" / "a1"
    target.mkdir(parents=True)

    def _boom(_path):
        raise OSError("device or resource busy")

    monkeypatch.setattr("qwenpaw.cli.agents_cmd.shutil.rmtree", _boom)

    with pytest.raises(click.ClickException) as excinfo:
        mod._remove_agent_workspace(target)

    assert "Failed to delete workspace" in excinfo.value.message
    assert "device or resource busy" in excinfo.value.message


# --------------------------------------------------------------------- #
# create_cmd remaining branches
# --------------------------------------------------------------------- #


def test_create_cmd_rejects_whitespace_only_name(monkeypatch) -> None:
    config = _config_with([])
    config.agents.language = "zh"
    monkeypatch.setattr("qwenpaw.cli.agents_cmd.load_config", lambda: config)

    result = CliRunner().invoke(
        cli,
        ["agents", "create", "--name", "   "],
    )

    assert result.exit_code != 0
    assert "--name is required." in result.output


def test_create_cmd_wraps_template_value_error(
    monkeypatch,
    tmp_path,
) -> None:
    config = _config_with([])
    config.agents.language = "zh"
    monkeypatch.setattr("qwenpaw.cli.agents_cmd.load_config", lambda: config)

    def _boom(*_args, **_kwargs):
        raise ValueError("template exploded")

    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.build_agent_template",
        _boom,
    )

    result = CliRunner().invoke(
        cli,
        [
            "agents",
            "create",
            "--name",
            "Bot",
            "--agent-id",
            "bot-x",
            "--workspace-dir",
            str(tmp_path / "bot-x"),
        ],
    )

    assert result.exit_code != 0
    assert "template exploded" in result.output


def test_create_cmd_default_workspace_lands_under_working_dir(
    monkeypatch,
    tmp_path,
) -> None:
    config = _config_with([])
    config.agents.language = "zh"
    saved: dict = {}

    monkeypatch.setattr("qwenpaw.cli.agents_cmd.load_config", lambda: config)
    monkeypatch.setattr("qwenpaw.cli.agents_cmd.WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        "qwenpaw.cli.agents_cmd.save_config",
        lambda updated: saved.setdefault("config", updated),
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
        lambda workspace_dir, skill_names, md_template_id=None: (
            saved.setdefault("workspace_init", workspace_dir)
        ),
    )

    result = CliRunner().invoke(
        cli,
        ["agents", "create", "--name", "Bot", "--agent-id", "bot-y"],
    )

    assert result.exit_code == 0, result.output
    assert saved["workspace_init"] == tmp_path / "workspaces" / "bot-y"
    assert saved["workspace_init"].is_dir()
    assert config.agents.agent_order == ["bot-y"]
