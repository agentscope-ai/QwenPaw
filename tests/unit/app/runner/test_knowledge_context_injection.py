# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncIterator, cast

from agentscope.message import Msg, TextBlock
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

from copaw.app.runner.runner import AgentRunner
from copaw.app.runner.session import SafeJSONSession


class _DummyAgent:
    captured_input_msgs = None

    def __init__(self, *args, **kwargs) -> None:
        _ = args, kwargs

    async def register_mcp_clients(self) -> None:
        return None

    def set_console_output_enabled(self, enabled: bool) -> None:
        _ = enabled

    def rebuild_sys_prompt(self) -> None:
        return None

    def __call__(self, msgs):
        type(self).captured_input_msgs = msgs
        return object()


class _DummySession(SafeJSONSession):
    def __init__(self) -> None:
        super().__init__(save_dir=".")

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


async def test_query_handler_does_not_inject_knowledge_context(monkeypatch) -> None:
    from copaw.app.runner import runner as runner_module

    async def _no_approval(session_id: str, query: str | None):
        _ = session_id, query
        return None, False

    async def _stream_printing_messages(*args, **kwargs):
        _ = args, kwargs
        yield (
            Msg(
                name="assistant",
                role="assistant",
                content=[TextBlock(type="text", text="ok")],
            ),
            True,
        )

    runner = AgentRunner()
    runner.session = _DummySession()
    cast(Any, runner)._resolve_pending_approval = _no_approval

    monkeypatch.setattr(runner_module, "CoPawAgent", _DummyAgent)
    monkeypatch.setattr(runner_module, "build_env_context", lambda **kwargs: kwargs)
    monkeypatch.setattr(
        runner_module,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                running=SimpleNamespace(
                    max_iters=8,
                    max_input_length=8192,
                    auto_collect_chat_files=False,
                    auto_collect_chat_urls=False,
                    auto_collect_long_text=False,
                ),
            ),
            knowledge=SimpleNamespace(enabled=True),
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "stream_printing_messages",
        _stream_printing_messages,
    )

    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="如何接入知识库")],
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

    stream = cast(
        AsyncIterator[tuple[Msg, bool]],
        cast(Any, runner).query_handler(msgs, request=request),
    )
    async for _msg, _last in stream:
        pass

    captured = cast(list[Msg], _DummyAgent.captured_input_msgs)
    assert captured is not None
    assert len(captured) == 1
    assert captured[0].role == "user"


async def test_query_handler_skips_knowledge_context_when_disabled(monkeypatch) -> None:
    from copaw.app.runner import runner as runner_module

    async def _no_approval(session_id: str, query: str | None):
        _ = session_id, query
        return None, False

    async def _stream_printing_messages(*args, **kwargs):
        _ = args, kwargs
        yield (
            Msg(
                name="assistant",
                role="assistant",
                content=[TextBlock(type="text", text="ok")],
            ),
            True,
        )

    runner = AgentRunner()
    runner.session = _DummySession()
    cast(Any, runner)._resolve_pending_approval = _no_approval

    monkeypatch.setattr(runner_module, "CoPawAgent", _DummyAgent)
    monkeypatch.setattr(runner_module, "build_env_context", lambda **kwargs: kwargs)
    monkeypatch.setattr(
        runner_module,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                running=SimpleNamespace(
                    max_iters=8,
                    max_input_length=8192,
                    auto_collect_chat_files=False,
                    auto_collect_long_text=False,
                    knowledge_retrieval_enabled=False,
                ),
            ),
            knowledge=SimpleNamespace(enabled=True),
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "stream_printing_messages",
        _stream_printing_messages,
    )

    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="如何接入知识库")],
        ),
    ]
    request = cast(
        AgentRequest,
        SimpleNamespace(
            session_id="session-2",
            user_id="user-1",
            channel="console",
        ),
    )

    stream = cast(
        AsyncIterator[tuple[Msg, bool]],
        cast(Any, runner).query_handler(msgs, request=request),
    )
    async for _msg, _last in stream:
        pass

    captured = cast(list[Msg], _DummyAgent.captured_input_msgs)
    assert captured is not None
    assert len(captured) == 1
    assert captured[0].role == "user"
