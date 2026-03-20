# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncIterator, cast

from agentscope.message import Msg, TextBlock
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

from copaw.app.runner.runner import AgentRunner, _build_retryable_error_msg
from copaw.app.runner.session import SafeJSONSession


class _Retryable503Error(Exception):
    status_code = 503


class _DummyAgent:
    def __init__(self, *args, **kwargs) -> None:
        _ = args, kwargs

    async def register_mcp_clients(self) -> None:
        return None

    def set_console_output_enabled(self, enabled: bool) -> None:
        _ = enabled

    def rebuild_sys_prompt(self) -> None:
        return None

    def __call__(self, msgs):
        _ = msgs
        return object()


class _DummySession(SafeJSONSession):
    def __init__(self) -> None:
        super().__init__(save_dir=".")
        self.saved = False

    async def load_session_state(
        self,
        session_id: str,
        user_id: str = "",
        allow_not_exist: bool = True,
        **state_modules_mapping,
    ) -> None:
        _ = session_id, user_id, allow_not_exist, state_modules_mapping

    async def save_session_state(
        self,
        session_id: str,
        user_id: str = "",
        **state_modules_mapping,
    ) -> None:
        _ = session_id, user_id, state_modules_mapping
        self.saved = True


def test_build_retryable_error_msg_includes_status_code() -> None:
    msg = _build_retryable_error_msg(_Retryable503Error("Error code: 503"))
    text = cast(str, (msg.get_text_content() if msg is not None else "") or "")

    assert msg is not None
    assert "503" in text
    assert "稍后再试" in text


def test_build_retryable_error_msg_from_text_status_code() -> None:
    msg = _build_retryable_error_msg(Exception("Error code: 503"))
    text = cast(str, (msg.get_text_content() if msg is not None else "") or "")

    assert msg is not None
    assert "503" in text
    assert "稍后再试" in text


async def test_query_handler_returns_retryable_error_msg(
    monkeypatch,
) -> None:
    from copaw.app.runner import runner as runner_module

    async def _no_approval(session_id: str, query: str | None):
        _ = session_id, query
        return None, False

    async def _failing_stream_printing_messages(*args, **kwargs):
        _ = args, kwargs
        raise _Retryable503Error("Error code: 503")
        yield  # pragma: no cover

    runner = AgentRunner()
    runner.session = _DummySession()
    cast(Any, runner)._resolve_pending_approval = _no_approval

    monkeypatch.setattr(runner_module, "CoPawAgent", _DummyAgent)
    monkeypatch.setattr(runner_module, "build_env_context", lambda **kwargs: kwargs)
    monkeypatch.setattr(
        runner_module,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(),
    )
    monkeypatch.setattr(
        runner_module,
        "stream_printing_messages",
        _failing_stream_printing_messages,
    )
    monkeypatch.setattr(
        runner_module,
        "write_query_error_dump",
        lambda **kwargs: "/tmp/copaw_query_error.json",
    )

    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="继续")],
        ),
    ]
    request = cast(
        AgentRequest,
        SimpleNamespace(
            session_id="session-1",
            user_id="user-1",
            channel="console",
        ),
    )

    results = []
    stream = cast(
        AsyncIterator[tuple[Msg, bool]],
        cast(Any, runner).query_handler(msgs, request=request),
    )
    async for msg, last in stream:
        results.append((msg, last))

    assert len(results) == 1
    msg, last = results[0]
    text = cast(str, msg.get_text_content() or "")
    assert last is True
    assert "503" in text
    assert "稍后再试" in text
    assert cast(_DummySession, runner.session).saved is True
