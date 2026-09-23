# -*- coding: utf-8 -*-
"""Interrupted Scroll instructions follow the runtime save lifecycle."""

# pylint: disable=protected-access

import asyncio
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.event import ReplyEndEvent, ReplyFinishedReason
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.manager import ScrollContextManager
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.hooks.session.session_hook import SessionSaveHook
from qwenpaw.runtime.console_turn_state import CLIENT_ID, TURN_STATE
from qwenpaw.runtime.hooks import HookRegistry
from qwenpaw.runtime.runtime import Runtime


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ending",
    ["success", "interrupted", "cancel", "error"],
)
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
        session = SafeJSONSession(save_dir=str(tmp_path))
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

        async def reply_stream(inputs):
            agent.state.context.extend(inputs)
            if ending == "cancel":
                raise asyncio.CancelledError()
            if ending == "error":
                raise RuntimeError("model unavailable")
            reasons = {
                "success": ReplyFinishedReason.COMPLETED,
                "interrupted": ReplyFinishedReason.INTERRUPTED,
            }
            yield ReplyEndEvent(
                session_id="s",
                reply_id="reply",
                finished_reason=reasons[ending],
            )

        agent.reply_stream = reply_stream
        runtime = Runtime(workspace=workspace, app_services=None)

        async def consume():
            async for _ in runtime.run(
                {
                    "session_id": "s",
                    "user_id": "user",
                    "channel": "console",
                    "input": [
                        {
                            "role": "user",
                            "metadata": {CLIENT_ID: "request-b"},
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
        saved = (await session.get_session_state_dict("s", "user", "console"))[
            "agent"
        ]
        pinned = set(saved["scroll"]["interrupted_user_ids"])
        if ending == "success":
            assert pinned == set()
        elif ending in {"cancel", "interrupted"}:
            assert pinned == {m.id for m in agent.state.context}
        else:
            assert pinned == {original.id}
        if ending in {"cancel", "interrupted", "success"}:
            assert saved["state"]["context"][-1]["metadata"][TURN_STATE] == {
                "status": "completed" if ending == "success" else "canceled",
            }

        if ending != "interrupted":
            return

        # The event-interrupted turn stays pinned on reload until completion.
        manager.load_state(saved["scroll"])
        agent.state.context = [
            Msg.model_validate(message)
            for message in saved["state"]["context"]
        ]
        ending = "success"
        await consume()
        resumed = await session.get_session_state_dict("s", "user", "console")
        assert resumed["agent"]["scroll"]["interrupted_user_ids"] == []
