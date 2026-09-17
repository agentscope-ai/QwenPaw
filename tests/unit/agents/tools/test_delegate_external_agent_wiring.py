# -*- coding: utf-8 -*-
"""Tests for the external-agent delegation tool's service wiring.

Covers the parts that talk to the ACP service: runner discovery, session
state probing, input validation, the action dispatcher, the streaming
loop's interrupt / cancellation paths, and the public
``delegate_external_agent`` entry point.

The pure formatters over already-collected state live in
``test_delegate_external_agent_state.py``; the dynamic kill-deadline
interaction lives in ``test_delegate_external_agent_timeout.py``.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.agents import acp as acp_pkg
from qwenpaw.app import agent_context
from qwenpaw.config import config as config_mod

# Package ``tools.__init__`` re-exports the tool function under the same
# name as the module, so resolve the real module object via importlib.
dea = importlib.import_module("qwenpaw.agents.tools.delegate_external_agent")


def _chunk_text(chunk: Any) -> str:
    """Join every text block of a ToolChunk into a single string."""
    return "".join(
        str(getattr(block, "text", "") or "")
        for block in (getattr(chunk, "content", None) or [])
    )


def _profile(*runners: str) -> SimpleNamespace:
    """Build an agent-profile double whose ACP config enables *runners*."""
    return SimpleNamespace(
        acp=SimpleNamespace(
            agents={name: SimpleNamespace(enabled=True) for name in runners},
        ),
    )


def _service(**overrides: Any) -> MagicMock:
    """Build an ACP service double whose coroutine methods are AsyncMock."""
    svc = MagicMock(name="service")
    svc.get_session = AsyncMock(return_value=None)
    svc.get_pending_permission = AsyncMock(return_value=None)
    svc.close_chat_session = AsyncMock(return_value=None)
    svc.cancel_turn = AsyncMock(return_value=True)
    svc.run_turn = AsyncMock(return_value={})
    svc.resume_permission = AsyncMock(return_value={})
    for name, value in overrides.items():
        setattr(svc, name, value)
    return svc


def _session(returncode: Optional[int] = None) -> SimpleNamespace:
    """Build a bound ACP session double."""
    return SimpleNamespace(
        process=SimpleNamespace(returncode=returncode),
        acp_session_id="acp-session-1",
    )


def _runner_state(
    *,
    agent_id: str = "agent-1",
    chat_id: str = "chat-1",
    runner: str = "codex",
    status: str = "running",
    action: str = "start",
) -> Any:
    """Build a runner-state record for the module-level store."""
    return dea._RunnerState(
        agent_id=agent_id,
        chat_id=chat_id,
        runner=runner,
        action=action,
        status=status,
        created_at=1700000000.0,
        updated_at=1700000001.0,
    )


@pytest.fixture(autouse=True)
def _clear_runner_states():
    """Keep the module-level runner-state store isolated per test."""
    dea._runner_states.clear()
    yield
    dea._runner_states.clear()


@pytest.fixture(name="env")
def _env_fixture():
    """Patch the four imports the delegation tool resolves at call time.

    ``_get_acp_service`` / ``_get_available_acp_runners`` /
    ``_request_context_chat_id`` / ``_current_agent_id`` all do
    function-local imports, so the doubles have to be installed on the
    *source* modules.
    """
    state = SimpleNamespace(
        agent_id="agent-1",
        session_id="chat-1",
        runners={"codex": True, "opencode": True, "zeta": False},
        profile=None,
        existing_service=None,
        new_service=MagicMock(name="init-service"),
        init_calls=[],
    )

    def _load_agent_config(agent_id: str) -> Any:
        if state.profile is not None:
            return state.profile
        acp_config = SimpleNamespace(
            agents={
                name: SimpleNamespace(enabled=flag)
                for name, flag in state.runners.items()
            },
        )
        return SimpleNamespace(acp=acp_config)

    def _get_service(agent_id: str) -> Any:
        return state.existing_service

    def _init_service(agent_id: str, acp_config: Any) -> Any:
        state.init_calls.append((agent_id, acp_config))
        return state.new_service

    with (
        patch.object(
            agent_context,
            "get_current_agent_id",
            lambda: state.agent_id,
        ),
        patch.object(
            agent_context,
            "get_current_session_id",
            lambda: state.session_id,
        ),
        patch.object(
            config_mod,
            "load_agent_config",
            _load_agent_config,
        ),
        patch.object(acp_pkg, "get_acp_service", _get_service),
        patch.object(acp_pkg, "init_acp_service", _init_service),
    ):
        yield state


# ---------------------------------------------------------------------------
# _current_workspace_dir / _current_agent_id
# ---------------------------------------------------------------------------


class TestContextHelpers:
    def test_workspace_dir_uses_context_when_set(self, tmp_path):
        with patch.object(
            dea,
            "get_current_workspace_dir",
            return_value=tmp_path,
        ):
            assert dea._current_workspace_dir() == tmp_path

    def test_workspace_dir_falls_back_to_working_dir(self):
        with patch.object(dea, "get_current_workspace_dir", return_value=None):
            resolved = dea._current_workspace_dir()
        assert resolved == Path(dea.WORKING_DIR).expanduser()
        assert resolved.is_absolute()

    def test_agent_id_reads_context(self, env):
        assert dea._current_agent_id() == "agent-1"
        env.agent_id = "other-agent"
        assert dea._current_agent_id() == "other-agent"


# ---------------------------------------------------------------------------
# _get_acp_service
# ---------------------------------------------------------------------------


class TestGetAcpService:
    def test_reuses_service_with_matching_config(self, env):
        shared = SimpleNamespace(agents={})
        env.profile = SimpleNamespace(acp=shared)
        env.existing_service = SimpleNamespace(config=shared)

        assert dea._get_acp_service() is env.existing_service
        assert env.init_calls == []

    def test_initialises_when_no_service_yet(self, env):
        env.existing_service = None

        assert dea._get_acp_service() is env.new_service
        assert env.init_calls[0][0] == "agent-1"

    def test_reinitialises_when_config_changed(self, env):
        env.profile = _profile("codex")
        env.existing_service = SimpleNamespace(
            config=SimpleNamespace(agents={"stale": object()}),
        )

        assert dea._get_acp_service() is env.new_service
        assert len(env.init_calls) == 1

    def test_falls_back_to_default_acp_config(self, env):
        env.profile = SimpleNamespace(acp=None)
        env.existing_service = None

        dea._get_acp_service()

        assert len(env.init_calls) == 1
        assert isinstance(env.init_calls[0][1], config_mod.ACPConfig)


# ---------------------------------------------------------------------------
# _get_available_acp_runners / _format_available_runners_text
# ---------------------------------------------------------------------------


class TestRunnerDiscovery:
    def test_returns_only_enabled_runners_sorted(self, env):
        assert dea._get_available_acp_runners() == ["codex", "opencode"]

    def test_empty_when_nothing_enabled(self, env):
        env.runners = {"codex": False, "opencode": False}
        assert dea._get_available_acp_runners() == []

    def test_runners_without_enabled_flag_are_skipped(self, env):
        env.runners = {"legacy": False}
        env.profile = SimpleNamespace(
            acp=SimpleNamespace(agents={"legacy": object()}),
        )
        assert dea._get_available_acp_runners() == []

    def test_text_lists_runners(self, env):
        text = dea._format_available_runners_text()
        assert text == "Available ACP runners: codex, opencode."

    def test_text_reports_absence(self, env):
        env.runners = {"codex": False}
        assert (
            dea._format_available_runners_text()
            == "No enabled ACP runners are currently configured."
        )


# ---------------------------------------------------------------------------
# _request_context_chat_id
# ---------------------------------------------------------------------------


class TestRequestContextChatId:
    def test_returns_session_id(self, env):
        assert dea._request_context_chat_id() == "chat-1"

    def test_raises_without_session(self, env):
        env.session_id = None
        with pytest.raises(ValueError) as excinfo:
            dea._request_context_chat_id()
        assert "session_id" in str(excinfo.value)

    def test_empty_session_id_also_raises(self, env):
        env.session_id = ""
        with pytest.raises(ValueError):
            dea._request_context_chat_id()


# ---------------------------------------------------------------------------
# _validate_action_inputs
# ---------------------------------------------------------------------------


class TestValidateActionInputs:
    def test_rejects_unknown_action(self):
        error = dea._validate_action_inputs(
            action_name="restart",
            runner_name="codex",
            message_text="hi",
        )
        assert error is not None
        assert "action must be one of" in error

    def test_rejects_empty_action(self):
        error = dea._validate_action_inputs(
            action_name="",
            runner_name="codex",
            message_text="hi",
        )
        assert "action must be one of" in (error or "")

    @pytest.mark.parametrize(
        "action",
        ["start", "message", "respond", "close"],
    )
    def test_runner_required_outside_list_and_status(self, action):
        error = dea._validate_action_inputs(
            action_name=action,
            runner_name="",
            message_text="payload",
        )
        assert error == "Error: runner is empty."

    @pytest.mark.parametrize("action", ["list", "status"])
    def test_runner_optional_for_list_and_status(self, action):
        assert (
            dea._validate_action_inputs(
                action_name=action,
                runner_name="",
                message_text="",
            )
            is None
        )

    def test_message_action_needs_text(self):
        error = dea._validate_action_inputs(
            action_name="message",
            runner_name="codex",
            message_text="",
        )
        assert error is not None
        assert "Use action='start'" in error

    def test_respond_action_needs_option_id(self):
        error = dea._validate_action_inputs(
            action_name="respond",
            runner_name="codex",
            message_text="",
        )
        assert error is not None
        assert "permission option id" in error

    @pytest.mark.parametrize(
        "action",
        ["list", "status", "start", "close"],
    )
    def test_accepts_valid_combinations(self, action):
        assert (
            dea._validate_action_inputs(
                action_name=action,
                runner_name="codex",
                message_text="",
            )
            is None
        )

    def test_accepts_message_with_text(self):
        assert (
            dea._validate_action_inputs(
                action_name="message",
                runner_name="codex",
                message_text="continue",
            )
            is None
        )


# ---------------------------------------------------------------------------
# _parse_timeout
# ---------------------------------------------------------------------------


class TestParseTimeout:
    def test_none_means_no_timeout(self):
        assert dea._parse_timeout(None) == (None, None)

    def test_numeric_string_is_coerced(self):
        assert dea._parse_timeout("2.5") == (2.5, None)

    def test_int_passthrough(self):
        assert dea._parse_timeout(300) == (300.0, None)

    @pytest.mark.parametrize("value", ["abc", [], object()])
    def test_non_numeric_reports_error(self, value):
        seconds, error = dea._parse_timeout(value)
        assert seconds is None
        assert error == "Error: max_runtime must be a number in seconds."

    @pytest.mark.parametrize("value", [0, -1, -0.5])
    def test_non_positive_reports_error(self, value):
        seconds, error = dea._parse_timeout(value)
        assert seconds is None
        assert error == "Error: max_runtime must be greater than 0."


# ---------------------------------------------------------------------------
# _text_already_streamed
# ---------------------------------------------------------------------------


class TestTextAlreadyStreamed:
    def test_suppresses_when_text_was_streamed_in_fragments(self):
        event = {"type": "text", "text": "hello world"}
        assert dea._text_already_streamed(event, ["hello ", "world"]) is True

    def test_keeps_text_when_only_partially_streamed(self):
        event = {"type": "text", "text": "hello world"}
        assert dea._text_already_streamed(event, ["hello"]) is False

    def test_keeps_text_when_nothing_streamed(self):
        event = {"type": "text", "text": "answer"}
        assert dea._text_already_streamed(event, []) is False

    @pytest.mark.parametrize(
        "event",
        [None, "not-a-dict", 42, {"type": "tool_call", "text": "x"}],
    )
    def test_non_text_events_never_suppress(self, event):
        assert dea._text_already_streamed(event, ["x"]) is False

    def test_event_type_is_case_insensitive(self):
        assert dea._text_already_streamed({"type": "TEXT", "text": "a"}, ["a"])

    def test_blank_body_never_suppresses(self):
        assert (
            dea._text_already_streamed({"type": "text", "text": "   "}, [""])
            is False
        )


# ---------------------------------------------------------------------------
# _get_runner_session_state / _get_bound_session
# ---------------------------------------------------------------------------


class TestSessionStateProbing:
    async def test_no_session_is_closed(self):
        svc = _service(get_session=AsyncMock(return_value=None))
        state = await dea._get_runner_session_state(
            svc,
            chat_id="chat-1",
            runner_name="codex",
        )
        assert state == "closed"
        svc.get_pending_permission.assert_not_awaited()

    async def test_exited_process_reports_exited(self):
        svc = _service(get_session=AsyncMock(return_value=_session(1)))
        state = await dea._get_runner_session_state(
            svc,
            chat_id="chat-1",
            runner_name="codex",
        )
        assert state == "exited"
        svc.get_pending_permission.assert_not_awaited()

    async def test_pending_permission_reports_waiting(self):
        svc = _service(
            get_session=AsyncMock(return_value=_session(None)),
            get_pending_permission=AsyncMock(return_value=object()),
        )
        state = await dea._get_runner_session_state(
            svc,
            chat_id="chat-1",
            runner_name="codex",
        )
        assert state == "waiting_for_permission"

    async def test_live_session_without_permission_is_open(self):
        svc = _service(get_session=AsyncMock(return_value=_session(None)))
        state = await dea._get_runner_session_state(
            svc,
            chat_id="chat-1",
            runner_name="codex",
        )
        assert state == "open"

    async def test_session_lookup_passes_chat_and_runner(self):
        svc = _service(get_session=AsyncMock(return_value=None))
        await dea._get_runner_session_state(
            svc,
            chat_id="chat-42",
            runner_name="opencode",
        )
        svc.get_session.assert_awaited_once_with(
            chat_id="chat-42",
            agent="opencode",
        )

    async def test_bound_session_helper_delegates_to_service(self):
        bound = _session(None)
        svc = _service(get_session=AsyncMock(return_value=bound))
        assert (
            await dea._get_bound_session(
                svc,
                chat_id="chat-1",
                runner_name="codex",
            )
            is bound
        )


# ---------------------------------------------------------------------------
# _format_acp_runner_states_response
# ---------------------------------------------------------------------------


class TestRunnerStatesResponse:
    async def test_reports_absence_of_runners(self, env):
        env.runners = {"codex": False}
        chunk = await dea._format_acp_runner_states_response()
        assert _chunk_text(chunk) == (
            "No enabled ACP runners are currently configured."
        )

    async def test_without_session_context_lists_bare_names(self, env):
        env.session_id = None
        chunk = await dea._format_acp_runner_states_response()
        text = _chunk_text(chunk)
        assert text.startswith("Available external ACP runners and states:")
        assert "- codex" in text
        assert "- opencode" in text
        assert "session:" not in text

    async def test_lists_session_and_task_state(self, env):
        await dea._set_runner_state(_runner_state(runner="codex"))

        async def _get_session(*, chat_id, agent):
            # Only ``codex`` has a live ACP session bound to this chat.
            return _session(None) if agent == "codex" else None

        svc = _service(get_session=AsyncMock(side_effect=_get_session))
        env.existing_service = svc
        env.profile = _profile("codex", "opencode")
        svc.config = env.profile.acp

        text = _chunk_text(await dea._format_acp_runner_states_response())

        assert "- codex (session: open, task: running)" in text
        # The second runner has neither session nor recorded task.
        assert "- opencode (session: closed)" in text

    async def test_all_runner_status_response_reuses_the_same_text(self, env):
        env.session_id = None
        expected = _chunk_text(await dea._format_acp_runner_states_response())
        actual = _chunk_text(await dea._format_all_runner_status_response())
        assert actual == expected


# ---------------------------------------------------------------------------
# _format_runner_status_response
# ---------------------------------------------------------------------------


class TestRunnerStatusResponse:
    async def test_unknown_runner_is_rejected(self, env):
        text = _chunk_text(
            await dea._format_runner_status_response("not-configured"),
        )
        assert "Error: runner 'not-configured' is not available." in text
        assert "Available ACP runners: codex, opencode." in text

    async def test_missing_session_context_is_reported(self, env):
        env.session_id = None
        text = _chunk_text(await dea._format_runner_status_response("codex"))
        assert text.startswith(
            "Error: delegate agent requires request context",
        )

    async def test_renders_task_state(self, env):
        await dea._set_runner_state(_runner_state(status="completed"))
        svc = _service(get_session=AsyncMock(return_value=_session(None)))
        env.profile = _profile("codex", "opencode")
        svc.config = env.profile.acp
        env.existing_service = svc

        text = _chunk_text(await dea._format_runner_status_response("codex"))

        assert "runner: codex" in text
        assert "session: open" in text
        assert "task: completed" in text

    async def test_pending_permission_is_appended(self, env):
        suspended = SimpleNamespace(
            agent="codex",
            tool_name="write",
            tool_kind="file",
            target="/tmp/x",
            action=None,
            summary=None,
            command=None,
            paths=[],
            options=[{"optionId": "allow_once", "title": "Allow once"}],
        )
        svc = _service(
            get_session=AsyncMock(return_value=_session(None)),
            get_pending_permission=AsyncMock(return_value=suspended),
        )
        env.profile = _profile("codex", "opencode")
        svc.config = env.profile.acp
        env.existing_service = svc
        await dea._set_runner_state(_runner_state(status="running"))

        text = _chunk_text(await dea._format_runner_status_response("codex"))

        assert "task: permission_required" in text
        assert "External Agent Permission Request" in text
        assert "allow_once" in text


# ---------------------------------------------------------------------------
# _validate_start_request
# ---------------------------------------------------------------------------


class TestValidateStartRequest:
    async def test_unknown_runner_is_rejected(self, env):
        error = await dea._validate_start_request(
            service=_service(),
            chat_id="chat-1",
            runner_name="ghost",
        )
        assert error is not None
        assert "is not available for ACP start." in error

    async def test_no_existing_session_allows_start(self, env):
        svc = _service(get_session=AsyncMock(return_value=None))
        assert (
            await dea._validate_start_request(
                service=svc,
                chat_id="chat-1",
                runner_name="codex",
            )
            is None
        )
        svc.close_chat_session.assert_not_awaited()

    async def test_exited_session_is_cleaned_up_and_start_allowed(self, env):
        svc = _service(get_session=AsyncMock(return_value=_session(137)))
        assert (
            await dea._validate_start_request(
                service=svc,
                chat_id="chat-1",
                runner_name="codex",
            )
            is None
        )
        svc.close_chat_session.assert_awaited_once_with(
            chat_id="chat-1",
            agent="codex",
        )

    async def test_live_session_blocks_a_second_start(self, env):
        svc = _service(get_session=AsyncMock(return_value=_session(None)))
        error = await dea._validate_start_request(
            service=svc,
            chat_id="chat-1",
            runner_name="codex",
        )
        assert error is not None
        assert "already open" in error
        assert 'action="message"' in error
        svc.close_chat_session.assert_not_awaited()


# ---------------------------------------------------------------------------
# _cancel_running_acp_turn / _cancel_runner_turn
# ---------------------------------------------------------------------------


class TestCancellation:
    async def test_returns_service_result(self):
        svc = _service(cancel_turn=AsyncMock(return_value=True))
        assert (
            await dea._cancel_running_acp_turn(
                service=svc,
                chat_id="chat-1",
                runner_name="codex",
            )
            is True
        )

    async def test_service_error_is_swallowed(self, caplog):
        svc = _service(cancel_turn=AsyncMock(side_effect=RuntimeError("gone")))
        assert (
            await dea._cancel_running_acp_turn(
                service=svc,
                chat_id="chat-1",
                runner_name="codex",
            )
            is False
        )

    async def test_cancels_for_streaming_actions(self):
        svc = _service()
        await dea._cancel_runner_turn(
            service=svc,
            chat_id="chat-1",
            action_name="message",
            runner_name="codex",
        )
        svc.cancel_turn.assert_awaited_once_with(
            chat_id="chat-1",
            agent="codex",
        )

    @pytest.mark.parametrize("action", ["list", "status", "close"])
    async def test_skips_non_streaming_actions(self, action):
        svc = _service()
        await dea._cancel_runner_turn(
            service=svc,
            chat_id="chat-1",
            action_name=action,
            runner_name="codex",
        )
        svc.cancel_turn.assert_not_awaited()

    async def test_skips_without_service(self):
        svc = _service()
        await dea._cancel_runner_turn(
            service=None,
            chat_id="chat-1",
            action_name="start",
            runner_name="codex",
        )
        svc.cancel_turn.assert_not_awaited()

    async def test_skips_without_chat_id(self):
        svc = _service()
        await dea._cancel_runner_turn(
            service=svc,
            chat_id="",
            action_name="start",
            runner_name="codex",
        )
        svc.cancel_turn.assert_not_awaited()


# ---------------------------------------------------------------------------
# _run_action
# ---------------------------------------------------------------------------


class TestRunAction:
    async def test_start_restarts_a_new_turn(self, tmp_path):
        svc = _service()
        on_message = AsyncMock()
        await dea._run_action(
            service=svc,
            chat_id="chat-1",
            action_name="start",
            runner_name="codex",
            message_text="do it",
            execution_cwd=tmp_path,
            on_message=on_message,
        )
        kwargs = svc.run_turn.await_args.kwargs
        assert kwargs["restart"] is True
        assert kwargs["prompt_blocks"] == [{"type": "text", "text": "do it"}]
        assert kwargs["cwd"] == str(tmp_path)
        assert kwargs["on_message"] is on_message

    async def test_start_without_message_sends_greeting(self, tmp_path):
        svc = _service()
        await dea._run_action(
            service=svc,
            chat_id="chat-1",
            action_name="start",
            runner_name="codex",
            message_text="",
            execution_cwd=tmp_path,
            on_message=AsyncMock(),
        )
        assert svc.run_turn.await_args.kwargs["prompt_blocks"] == [
            {"type": "text", "text": "hi"},
        ]

    async def test_message_requires_existing_session(self, tmp_path):
        svc = _service()
        await dea._run_action(
            service=svc,
            chat_id="chat-1",
            action_name="message",
            runner_name="codex",
            message_text="continue",
            execution_cwd=tmp_path,
            on_message=AsyncMock(),
        )
        kwargs = svc.run_turn.await_args.kwargs
        assert kwargs["require_existing"] is True
        assert "restart" not in kwargs

    async def test_respond_resumes_pending_permission(self, tmp_path):
        suspended = SimpleNamespace(options=[])
        svc = _service(
            get_session=AsyncMock(return_value=_session(None)),
            get_pending_permission=AsyncMock(return_value=suspended),
        )
        await dea._run_action(
            service=svc,
            chat_id="chat-1",
            action_name="respond",
            runner_name="codex",
            message_text="  allow_once  ",
            execution_cwd=tmp_path,
            on_message=AsyncMock(),
        )
        svc.resume_permission.assert_awaited_once()
        kwargs = svc.resume_permission.await_args.kwargs
        assert kwargs["acp_session_id"] == "acp-session-1"
        assert kwargs["option_id"] == "allow_once"

    async def test_respond_without_bound_session_raises(self, tmp_path):
        svc = _service(get_session=AsyncMock(return_value=None))
        with pytest.raises(ValueError) as excinfo:
            await dea._run_action(
                service=svc,
                chat_id="chat-1",
                action_name="respond",
                runner_name="codex",
                message_text="allow_once",
                execution_cwd=tmp_path,
                on_message=AsyncMock(),
            )
        assert "no bound ACP session found" in str(excinfo.value)
        svc.resume_permission.assert_not_awaited()

    async def test_respond_without_pending_permission_raises(self, tmp_path):
        svc = _service(get_session=AsyncMock(return_value=_session(None)))
        with pytest.raises(ValueError) as excinfo:
            await dea._run_action(
                service=svc,
                chat_id="chat-1",
                action_name="respond",
                runner_name="codex",
                message_text="allow_once",
                execution_cwd=tmp_path,
                on_message=AsyncMock(),
            )
        assert "not waiting for permission" in str(excinfo.value)

    async def test_unsupported_action_raises(self, tmp_path):
        with pytest.raises(ValueError) as excinfo:
            await dea._run_action(
                service=_service(),
                chat_id="chat-1",
                action_name="explode",
                runner_name="codex",
                message_text="",
                execution_cwd=tmp_path,
                on_message=AsyncMock(),
            )
        assert "unsupported action: explode" in str(excinfo.value)


# ---------------------------------------------------------------------------
# _validate_runner_start / _create_runner_state / _finalize_runner_state
# ---------------------------------------------------------------------------


class TestRunnerLifecycleHelpers:
    async def test_non_start_actions_skip_validation(self, env):
        state = _runner_state()
        assert (
            await dea._validate_runner_start(
                service=_service(),
                state=state,
                action_name="message",
                chat_id="chat-1",
                runner_name="codex",
            )
            is None
        )
        assert state.status == "running"

    async def test_valid_start_returns_none(self, env):
        svc = _service(get_session=AsyncMock(return_value=None))
        state = _runner_state()
        assert (
            await dea._validate_runner_start(
                service=svc,
                state=state,
                action_name="start",
                chat_id="chat-1",
                runner_name="codex",
            )
            is None
        )
        assert state.status == "running"

    async def test_invalid_start_marks_state_failed(self, env):
        svc = _service(get_session=AsyncMock(return_value=_session(None)))
        state = _runner_state()
        chunk = await dea._validate_runner_start(
            service=svc,
            state=state,
            action_name="start",
            chat_id="chat-1",
            runner_name="codex",
        )
        assert chunk is not None
        assert "already open" in _chunk_text(chunk)
        assert state.status == "failed"
        assert "already open" in (state.error or "")

    async def test_create_runner_state_is_stored(self, env):
        state = await dea._create_runner_state(
            action_name="start",
            runner_name="codex",
            chat_id="chat-1",
        )
        assert state.status == "running"
        assert state.agent_id == "agent-1"
        stored = await dea._get_runner_state(
            agent_id="agent-1",
            chat_id="chat-1",
            runner_name="codex",
        )
        assert stored is state

    async def test_finalize_marks_completed(self):
        svc = _service()
        state = _runner_state()
        await dea._finalize_runner_state(
            service=svc,
            state=state,
            chat_id="chat-1",
            runner_name="codex",
        )
        assert state.status == "completed"
        assert state.error is None

    async def test_finalize_marks_permission_required(self):
        suspended = SimpleNamespace(options=[])
        svc = _service(
            get_pending_permission=AsyncMock(return_value=suspended),
        )
        state = _runner_state()
        await dea._finalize_runner_state(
            service=svc,
            state=state,
            chat_id="chat-1",
            runner_name="codex",
        )
        assert state.status == "permission_required"
        assert state.pending_permission is suspended

    async def test_failed_state_records_error(self):
        state = _runner_state()
        await dea._set_failed_runner_state(state, RuntimeError("boom"))
        assert state.status == "failed"
        assert state.error == "boom"

    async def test_failed_state_without_record_is_noop(self):
        await dea._set_failed_runner_state(None, RuntimeError("boom"))

    def test_interrupted_response_mentions_how_to_continue(self):
        text = _chunk_text(dea._interrupted_response("codex"))
        assert "was interrupted by the user" in text
        assert "still open" in text
        assert 'runner="codex"' in text
        assert dea._interrupted_response("codex").is_last is True


# ---------------------------------------------------------------------------
# _handle_immediate_action
# ---------------------------------------------------------------------------


class TestHandleImmediateAction:
    async def test_list_returns_runner_states(self, env):
        env.session_id = None
        text = _chunk_text(
            await dea._handle_immediate_action(
                action_name="list",
                runner_name="",
            ),
        )
        assert "Available external ACP runners and states:" in text

    async def test_status_with_runner_inspects_that_runner(self, env):
        svc = _service(get_session=AsyncMock(return_value=_session(None)))
        env.profile = _profile("codex", "opencode")
        svc.config = env.profile.acp
        env.existing_service = svc

        text = _chunk_text(
            await dea._handle_immediate_action(
                action_name="status",
                runner_name="codex",
            ),
        )
        assert "runner: codex" in text

    async def test_status_without_runner_lists_all(self, env):
        env.session_id = None
        text = _chunk_text(
            await dea._handle_immediate_action(
                action_name="status",
                runner_name="",
            ),
        )
        assert "Available external ACP runners and states:" in text

    async def test_close_reports_a_closed_session(self, env):
        svc = _service(get_session=AsyncMock(return_value=_session(None)))
        env.profile = _profile("codex", "opencode")
        svc.config = env.profile.acp
        env.existing_service = svc

        text = _chunk_text(
            await dea._handle_immediate_action(
                action_name="close",
                runner_name="codex",
            ),
        )
        assert text == "Closed the bound ACP session for runner 'codex'."
        svc.close_chat_session.assert_awaited_once_with(
            chat_id="chat-1",
            agent="codex",
        )

    async def test_close_without_session_says_so(self, env):
        svc = _service(get_session=AsyncMock(return_value=None))
        env.profile = _profile("codex", "opencode")
        svc.config = env.profile.acp
        env.existing_service = svc

        text = _chunk_text(
            await dea._handle_immediate_action(
                action_name="close",
                runner_name="codex",
            ),
        )
        assert text == (
            "No bound ACP session found for runner 'codex' "
            "in the current chat."
        )

    async def test_streaming_actions_are_not_immediate(self, env):
        assert (
            await dea._handle_immediate_action(
                action_name="message",
                runner_name="codex",
            )
            is None
        )


# ---------------------------------------------------------------------------
# _stream_action_responses
# ---------------------------------------------------------------------------


def _stream(
    action_name: str = "message",
    runner_name: str = "codex",
    max_runtime: Optional[float] = None,
    cwd: Optional[Path] = None,
):
    """Open the streaming generator against a stubbed ``_run_action``."""
    return dea._stream_action_responses(
        service=_service(),
        chat_id="chat-1",
        action_name=action_name,
        runner_name=runner_name,
        message_text="payload",
        execution_cwd=cwd or Path("/tmp/work"),
        max_runtime=max_runtime,
    )


class TestStreamActionResponses:
    async def test_coalesces_text_deltas_into_one_item(self):
        async def run(**kwargs):
            on_message = kwargs["on_message"]
            await on_message({"type": "text", "text": "hel"}, False)
            await on_message({"type": "text", "text": "lo"}, False)
            return {"event": {"type": "text", "text": "hello"}}

        with patch.object(dea, "_run_action", run):
            chunks = [chunk async for chunk in _stream()]

        texts = [_chunk_text(chunk) for chunk in chunks]
        assert texts[0] == "[assistant]\nhello"
        # The closing event repeats streamed text, so only the header stays.
        assert texts[-1] == "runner: codex working directory: /tmp/work"
        assert chunks[-1].is_last is True

    async def test_non_text_event_ends_the_assistant_message(self):
        async def run(**kwargs):
            on_message = kwargs["on_message"]
            await on_message({"type": "text", "text": "thinking"}, False)
            await on_message(
                {"type": "tool_call", "kind": "read", "detail": "/tmp/a"},
                False,
            )
            return {}

        with patch.object(dea, "_run_action", run):
            texts = [_chunk_text(c) async for c in _stream()]

        assert texts[0] == ("[assistant]\nthinking[tool_call] read (/tmp/a)")
        # The last text delta was already streamed, so the tail keeps its
        # header only instead of repeating the assistant text.
        assert texts[-1] == "runner: codex working directory: /tmp/work"

    async def test_turn_without_any_event_says_so(self):
        async def run(**kwargs):
            await kwargs["on_message"](
                {"type": "tool_call", "kind": "read", "detail": "/tmp/a"},
                False,
            )
            return {}

        with patch.object(dea, "_run_action", run):
            texts = [_chunk_text(c) async for c in _stream()]

        assert "completed without text output" in texts[-1]

    async def test_duplicate_stream_items_are_deduplicated(self):
        event = {"type": "tool_call", "kind": "read", "detail": "/tmp/a"}

        async def run(**kwargs):
            on_message = kwargs["on_message"]
            await on_message(dict(event), False)
            await on_message(dict(event), False)
            return {}

        with patch.object(dea, "_run_action", run):
            texts = [_chunk_text(c) async for c in _stream()]

        assert texts[0].count("[tool_call] read (/tmp/a)") == 1

    async def test_non_dict_messages_are_ignored(self):
        async def run(**kwargs):
            on_message = kwargs["on_message"]
            await on_message("plain string", False)
            await on_message(None, True)
            await on_message({"type": "text", "text": "kept"}, False)
            return {}

        with patch.object(dea, "_run_action", run):
            texts = [_chunk_text(c) async for c in _stream()]

        assert texts[0] == "[assistant]\nkept"

    async def test_error_event_is_replayed_as_final_fallback(self):
        async def run(**kwargs):
            await kwargs["on_message"](
                {"type": "error", "message": "boom"},
                False,
            )
            return {}

        with patch.object(dea, "_run_action", run):
            texts = [_chunk_text(c) async for c in _stream()]

        assert texts[0] == "[error] boom"
        assert "[error] boom" in texts[-1]

    async def test_suspended_permission_short_circuits_the_final_block(self):
        suspended = SimpleNamespace(
            agent="codex",
            tool_name="write",
            tool_kind="file",
            target="/tmp/x",
            action=None,
            summary=None,
            command=None,
            paths=[],
            options=[],
        )

        async def run(**_kwargs):
            return {"suspended_permission": suspended}

        with patch.object(dea, "_run_action", run):
            chunks = [c async for c in _stream(action_name="respond")]

        assert len(chunks) == 1
        assert "External Agent Permission Request" in _chunk_text(chunks[0])

    async def test_run_result_event_wins_over_the_last_delta(self):
        async def run(**kwargs):
            await kwargs["on_message"]({"type": "text", "text": "frag"}, False)
            return {"event": {"type": "text", "text": "the complete answer"}}

        with patch.object(dea, "_run_action", run):
            texts = [_chunk_text(c) async for c in _stream()]

        assert "the complete answer" in texts[-1]

    async def test_max_runtime_interrupts_and_cancels_the_turn(self):
        started = asyncio.Event()

        async def run(**_kwargs):
            started.set()
            await asyncio.sleep(30)
            return {}

        cancel = AsyncMock(return_value=True)
        with (
            patch.object(dea, "_run_action", run),
            patch.object(dea, "_cancel_running_acp_turn", cancel),
        ):
            texts = [_chunk_text(c) async for c in _stream(max_runtime=0.05)]

        assert cancel.await_count == 1
        assert len(texts) == 1
        assert "reached the preset max runtime" in texts[0]
        assert 'message="continue"' in texts[0]

    async def test_interrupt_survives_a_stubborn_runner(self):
        """A runner that swallows cancellation must not break the tool."""
        started = asyncio.Event()

        async def run(**_kwargs):
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                pass
            raise RuntimeError("refused to stop")

        cancel = AsyncMock(return_value=True)
        with (
            patch.object(dea, "_run_action", run),
            patch.object(dea, "_cancel_running_acp_turn", cancel),
        ):
            texts = [_chunk_text(c) async for c in _stream(max_runtime=0.05)]

        assert "reached the preset max runtime" in texts[-1]

    async def test_consumer_cancellation_cancels_the_turn(self):
        started = asyncio.Event()

        async def run(**_kwargs):
            started.set()
            await asyncio.sleep(30)
            return {}

        cancel = AsyncMock(return_value=True)
        yielded = []

        async def consume():
            async for chunk in _stream():
                yielded.append(chunk)

        with (
            patch.object(dea, "_run_action", run),
            patch.object(dea, "_cancel_running_acp_turn", cancel),
        ):
            task = asyncio.create_task(consume())
            await started.wait()
            await asyncio.sleep(0.02)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert cancel.await_count == 1

    async def test_consumer_cancellation_survives_a_stubborn_runner(self):
        started = asyncio.Event()

        async def run(**_kwargs):
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                pass
            raise RuntimeError("refused to stop")

        cancel = AsyncMock(return_value=True)

        async def consume():
            async for _chunk in _stream():
                pass

        with (
            patch.object(dea, "_run_action", run),
            patch.object(dea, "_cancel_running_acp_turn", cancel),
        ):
            task = asyncio.create_task(consume())
            await started.wait()
            await asyncio.sleep(0.02)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert cancel.await_count == 1

    async def test_streamed_snapshot_is_flushed_before_the_deadline(self):
        started = asyncio.Event()

        async def run(**kwargs):
            await kwargs["on_message"](
                {"type": "text", "text": "partial"},
                False,
            )
            started.set()
            await asyncio.sleep(30)
            return {}

        cancel = AsyncMock(return_value=True)
        with (
            patch.object(dea, "_run_action", run),
            patch.object(dea, "_cancel_running_acp_turn", cancel),
        ):
            texts = [_chunk_text(c) async for c in _stream(max_runtime=0.05)]

        assert any("partial" in text for text in texts)
        assert "reached the preset max runtime" in texts[-1]


# ---------------------------------------------------------------------------
# _run_streaming_agent_action
# ---------------------------------------------------------------------------


def _fake_stream(items: list[str], error: Optional[Exception] = None):
    """Build an async-generator stand-in for ``_stream_action_responses``."""

    async def _generator(**_kwargs):
        for text in items:
            yield dea.response_text(text, is_last=False)
        if error is not None:
            raise error

    return _generator


class TestRunStreamingAgentAction:
    async def test_success_records_state_and_streams_chunks(self, env):
        svc = _service()
        env.profile = _profile("codex", "opencode")
        svc.config = env.profile.acp
        env.existing_service = svc

        with patch.object(
            dea,
            "_stream_action_responses",
            _fake_stream(["first", "second"]),
        ):
            chunks = [
                c
                async for c in dea._run_streaming_agent_action(
                    action_name="message",
                    runner_name="codex",
                    message_text="hi",
                    execution_cwd=Path("/tmp/work"),
                    timeout_seconds=None,
                )
            ]

        assert [_chunk_text(c) for c in chunks] == ["first", "second"]
        state = await dea._get_runner_state(
            agent_id="agent-1",
            chat_id="chat-1",
            runner_name="codex",
        )
        assert state is not None
        assert state.status == "completed"
        assert [block.text for block in state.content] == ["first", "second"]

    async def test_invalid_start_is_reported_without_streaming(self, env):
        svc = _service(get_session=AsyncMock(return_value=_session(None)))
        env.profile = _profile("codex", "opencode")
        svc.config = env.profile.acp
        env.existing_service = svc
        stream = MagicMock()

        with patch.object(dea, "_stream_action_responses", stream):
            chunks = [
                c
                async for c in dea._run_streaming_agent_action(
                    action_name="start",
                    runner_name="codex",
                    message_text="hi",
                    execution_cwd=Path("/tmp/work"),
                    timeout_seconds=None,
                )
            ]

        stream.assert_not_called()
        assert len(chunks) == 1
        assert "already open" in _chunk_text(chunks[0])
        state = await dea._get_runner_state(
            agent_id="agent-1",
            chat_id="chat-1",
            runner_name="codex",
        )
        assert state.status == "failed"

    async def test_cancellation_marks_state_and_reraises(self, env):
        svc = _service()
        env.profile = _profile("codex", "opencode")
        svc.config = env.profile.acp
        env.existing_service = svc
        emitted = []

        async def consume():
            async for chunk in dea._run_streaming_agent_action(
                action_name="message",
                runner_name="codex",
                message_text="hi",
                execution_cwd=Path("/tmp/work"),
                timeout_seconds=None,
            ):
                emitted.append(chunk)

        with (
            patch.object(
                dea,
                "_stream_action_responses",
                _fake_stream([], asyncio.CancelledError()),
            ),
            patch.object(
                dea,
                "_cancel_running_acp_turn",
                AsyncMock(),
            ) as cancel,
        ):
            with pytest.raises(asyncio.CancelledError):
                await consume()

        assert cancel.await_count == 1
        assert "interrupted by the user" in _chunk_text(emitted[-1])
        state = await dea._get_runner_state(
            agent_id="agent-1",
            chat_id="chat-1",
            runner_name="codex",
        )
        assert state.status == "cancelled"

    async def test_import_error_reports_acp_unavailable(self, env):
        with patch.object(
            dea,
            "_stream_action_responses",
            _fake_stream([], ImportError("no acp here")),
        ):
            texts = [
                _chunk_text(c)
                async for c in dea._run_streaming_agent_action(
                    action_name="message",
                    runner_name="codex",
                    message_text="hi",
                    execution_cwd=Path("/tmp/work"),
                    timeout_seconds=None,
                )
            ]

        assert texts == ["ACP mode not available: no acp here."]
        state = await dea._get_runner_state(
            agent_id="agent-1",
            chat_id="chat-1",
            runner_name="codex",
        )
        assert state.status == "failed"
        assert state.error == "no acp here"

    async def test_value_error_is_prefixed(self, env):
        with patch.object(
            dea,
            "_stream_action_responses",
            _fake_stream([], ValueError("bad input")),
        ):
            texts = [
                _chunk_text(c)
                async for c in dea._run_streaming_agent_action(
                    action_name="message",
                    runner_name="codex",
                    message_text="hi",
                    execution_cwd=Path("/tmp/work"),
                    timeout_seconds=None,
                )
            ]

        assert texts == ["Error: bad input"]

    async def test_unexpected_error_is_reported_as_execution_error(self, env):
        with patch.object(
            dea,
            "_stream_action_responses",
            _fake_stream([], RuntimeError("kaput")),
        ):
            texts = [
                _chunk_text(c)
                async for c in dea._run_streaming_agent_action(
                    action_name="message",
                    runner_name="codex",
                    message_text="hi",
                    execution_cwd=Path("/tmp/work"),
                    timeout_seconds=None,
                )
            ]

        assert texts == ["ACP execution error: kaput"]

    async def test_missing_session_context_reports_error(self, env):
        env.session_id = None
        texts = [
            _chunk_text(c)
            async for c in dea._run_streaming_agent_action(
                action_name="message",
                runner_name="codex",
                message_text="hi",
                execution_cwd=Path("/tmp/work"),
                timeout_seconds=None,
            )
        ]
        assert len(texts) == 1
        assert texts[0].startswith("Error: delegate agent requires")


# ---------------------------------------------------------------------------
# delegate_external_agent (public entry point)
# ---------------------------------------------------------------------------


class TestDelegateExternalAgent:
    async def test_invalid_timeout_is_rejected_up_front(self, env):
        chunk = await dea.delegate_external_agent(
            action="start",
            runner="codex",
            message="hi",
            max_runtime=0,
        )
        assert _chunk_text(chunk) == (
            "Error: max_runtime must be greater than 0."
        )

    async def test_invalid_action_is_rejected_up_front(self, env):
        chunk = await dea.delegate_external_agent(action="explode")
        assert "action must be one of" in _chunk_text(chunk)

    async def test_missing_runner_is_rejected_up_front(self, env):
        chunk = await dea.delegate_external_agent(action="start", message="hi")
        assert _chunk_text(chunk) == "Error: runner is empty."

    async def test_action_is_normalised(self, env):
        env.session_id = None
        chunk = await dea.delegate_external_agent(action="  LIST  ")
        assert "Available external ACP runners" in _chunk_text(chunk)

    async def test_list_returns_a_chunk(self, env):
        env.session_id = None
        chunk = await dea.delegate_external_agent(action="list")
        assert "- codex" in _chunk_text(chunk)

    async def test_status_with_runner_returns_a_chunk(self, env):
        svc = _service(get_session=AsyncMock(return_value=_session(None)))
        env.profile = _profile("codex", "opencode")
        svc.config = env.profile.acp
        env.existing_service = svc
        chunk = await dea.delegate_external_agent(
            action="status",
            runner="codex",
        )
        assert "runner: codex" in _chunk_text(chunk)

    async def test_close_returns_a_chunk(self, env):
        svc = _service(get_session=AsyncMock(return_value=None))
        env.profile = _profile("codex", "opencode")
        svc.config = env.profile.acp
        env.existing_service = svc
        chunk = await dea.delegate_external_agent(
            action="close",
            runner="codex",
        )
        assert "No bound ACP session found" in _chunk_text(chunk)

    async def test_import_error_during_immediate_action(self, env):
        with patch.object(
            dea,
            "_handle_immediate_action",
            AsyncMock(side_effect=ImportError("acp missing")),
        ):
            chunk = await dea.delegate_external_agent(action="list")
        assert _chunk_text(chunk) == "ACP mode not available: acp missing."

    async def test_value_error_during_immediate_action(self, env):
        with patch.object(
            dea,
            "_handle_immediate_action",
            AsyncMock(side_effect=ValueError("no session")),
        ):
            chunk = await dea.delegate_external_agent(action="list")
        assert _chunk_text(chunk) == "Error: no session"

    async def test_unexpected_error_during_immediate_action(self, env):
        with patch.object(
            dea,
            "_handle_immediate_action",
            AsyncMock(side_effect=RuntimeError("kaboom")),
        ):
            chunk = await dea.delegate_external_agent(action="list")
        assert _chunk_text(chunk) == "ACP execution error: kaboom"

    async def test_streaming_actions_return_a_generator(self, env):
        result = await dea.delegate_external_agent(
            action="message",
            runner="codex",
            message="continue",
            cwd="sub/dir",
            max_runtime=42,
        )
        assert hasattr(result, "__aiter__")
        await result.aclose()

    async def test_start_without_message_is_accepted(self, env):
        result = await dea.delegate_external_agent(
            action="start",
            runner="codex",
        )
        assert hasattr(result, "__aiter__")
        await result.aclose()

    async def test_end_to_end_streaming_message(self, env):
        svc = _service(get_session=AsyncMock(return_value=None))
        env.profile = _profile("codex", "opencode")
        svc.config = env.profile.acp
        env.existing_service = svc

        async def run(**kwargs):
            await kwargs["on_message"](
                {"type": "text", "text": "all done"},
                False,
            )
            return {"event": {"type": "text", "text": "all done"}}

        generator = await dea.delegate_external_agent(
            action="start",
            runner="codex",
            message="please work",
            max_runtime=30,
        )
        with patch.object(dea, "_run_action", run):
            texts = [_chunk_text(c) async for c in generator]

        assert "[assistant]\nall done" in texts[0]
        assert texts[-1].startswith("runner: codex working directory:")
        state = await dea._get_runner_state(
            agent_id="agent-1",
            chat_id="chat-1",
            runner_name="codex",
        )
        assert state is not None
        assert state.status == "completed"

    def test_tool_descriptor_is_attached(self):
        descriptor = getattr(
            dea.delegate_external_agent,
            "_tool_descriptor",
            None,
        )
        assert descriptor is not None
        assert descriptor.name == "delegate_external_agent"
        assert descriptor.async_execution is True
        assert descriptor.enabled_by_default is False
        assert descriptor.governance.target_param == "runner"
