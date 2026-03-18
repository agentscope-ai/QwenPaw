# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import copaw.app.runner.runner as runner_module
from copaw.app.runner.runner import AgentRunner


class _FakeMsg:
    def get_text_content(self) -> str:
        return "hello"


class _FakeSession:
    async def load_session_state(self, session_id, user_id, agent) -> None:
        return None

    async def save_session_state(self, session_id, user_id, agent) -> None:
        return None


@pytest.mark.asyncio
async def test_query_handler_propagates_cancelled_error(monkeypatch) -> None:
    interrupted = {"called": False}

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            del kwargs

        async def register_mcp_clients(self) -> None:
            return None

        def set_console_output_enabled(self, enabled=False) -> None:
            del enabled

        def rebuild_sys_prompt(self) -> None:
            return None

        async def interrupt(self, msg=None) -> None:
            del msg
            interrupted["called"] = True

        def __call__(self, msgs):
            del msgs

            async def _noop():
                return None

            return _noop()

    async def fake_stream_printing_messages(*, agents, coroutine_task):
        del agents
        coroutine_task.close()
        raise asyncio.CancelledError
        yield  # pragma: no cover

    runner = AgentRunner(agent_id="test-agent")
    runner.session = _FakeSession()

    monkeypatch.setattr(runner_module, "CoPawAgent", FakeAgent)
    monkeypatch.setattr(runner_module, "build_env_context", lambda **_: "")
    monkeypatch.setattr(
        runner_module,
        "load_agent_config",
        lambda agent_id: SimpleNamespace(),
    )
    monkeypatch.setattr(
        runner_module,
        "stream_printing_messages",
        fake_stream_printing_messages,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    generator = runner.query_handler([_FakeMsg()], request=request)

    with pytest.raises(asyncio.CancelledError):
        await generator.__anext__()

    assert interrupted["called"] is True
