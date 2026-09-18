# -*- coding: utf-8 -*-
"""Interrupted Scroll instructions follow the runtime save lifecycle."""

# pylint: disable=protected-access

import asyncio
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.manager import ScrollContextManager
from qwenpaw.hooks.session.session_hook import SessionSaveHook
from qwenpaw.runtime.hooks import HookRegistry
from qwenpaw.runtime.runtime import Runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["success", "cancel", "error"])
async def test_runtime_checkpoints_interrupted_instructions(
    tmp_path,
    monkeypatch,
    ending,
):
    with closing(HistoryStore(tmp_path / "history.db")) as history:
        manager = ScrollContextManager(history=history, session_id="s")
        original = Msg(name="user", role="user", content=[TextBlock(text="A")])
        agent = SimpleNamespace(
            state=SimpleNamespace(context=[original]),
            _context_manager=manager,
        )
        manager.mark_interrupted_turn(agent)
        agent.state_dict = lambda: {
            "state": {
                "context": [
                    m.model_dump(mode="json") for m in agent.state.context
                ],
            },
            "scroll": manager.to_dict(),
        }
        session = SimpleNamespace(save_session_state=AsyncMock())
        hooks = HookRegistry()
        hooks.register(SessionSaveHook())
        workspace = SimpleNamespace(
            session=session,
            plugins=SimpleNamespace(
                hook_registry=hooks,
                modes=[],
                slash_command_registry=SimpleNamespace(
                    dispatch=AsyncMock(return_value=None),
                ),
            ),
        )
        builder = SimpleNamespace(build=AsyncMock(return_value=agent))
        monkeypatch.setattr(
            "qwenpaw.runtime.runtime.AgentBuilder",
            lambda **kwargs: builder,
        )
        monkeypatch.setattr(
            "qwenpaw.runtime.runtime.record_agent_activity",
            AsyncMock(),
        )

        class Executor:
            def __init__(self, *_args):
                pass

            async def run(self, inputs):
                agent.state.context.extend(inputs)
                if ending == "cancel":
                    raise asyncio.CancelledError()
                if ending == "error":
                    raise RuntimeError("model unavailable")
                if False:  # pylint: disable=using-constant-test
                    yield

        monkeypatch.setattr("qwenpaw.runtime.runtime.AgentExecutor", Executor)
        runtime = Runtime(workspace=workspace, app_services=None)

        async def consume():
            async for _ in runtime.run(
                {
                    "session_id": "s",
                    "input": [
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": "B"}],
                        },
                    ],
                },
            ):
                pass

        if ending == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await consume()
        elif ending == "error":
            with pytest.raises(RuntimeError, match="model unavailable"):
                await consume()
        else:
            await consume()
        session.save_session_state.assert_awaited_once()
        saved = session.save_session_state.call_args.kwargs["agent"].data
        pinned = set(saved["scroll"]["interrupted_user_ids"])
        if ending == "success":
            assert pinned == set()
        elif ending == "cancel":
            assert pinned == {m.id for m in agent.state.context}
        else:
            assert pinned == {original.id}
