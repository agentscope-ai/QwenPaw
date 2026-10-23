# -*- coding: utf-8 -*-
"""Session hook persistence behavior."""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.formatter import DashScopeChatFormatter, OpenAIChatFormatter
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from qwenpaw.agents.acp.meta import ACP_EPHEMERAL_META_KEY
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.chats.timeline import (
    ChatTimelineJournal,
    pending_timeline_messages,
)
from qwenpaw.app.chats.utils import agentscope_msg_to_message
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.hooks.session.session_hook import SessionLoadHook, SessionSaveHook
from qwenpaw.hooks.session.signals import SESSION_SAVE_SUCCEEDED_KEY
from qwenpaw.runtime._state_utils import StateProxy

pytestmark = [pytest.mark.unit, pytest.mark.p1]


class _FakeSession:
    def __init__(self, *, save_error: Exception | None = None) -> None:
        self.loaded = False
        self.saved = False
        self.load_payload = {}
        self.saved_payload = {}
        self.save_error = save_error

    async def load_session_state(self, *args, **kwargs) -> None:
        del args
        self.loaded = True
        kwargs["agent"].load_state_dict(self.load_payload)

    async def save_session_state(self, *args, **kwargs) -> None:
        del args
        if self.save_error is not None:
            raise self.save_error
        self.saved = True
        self.saved_payload = kwargs["agent"].state_dict()


def _ctx(session: _FakeSession, *, ephemeral: bool):
    return SimpleNamespace(
        request=SimpleNamespace(
            request_context={ACP_EPHEMERAL_META_KEY: ephemeral},
            user_id="acp_warmup",
            channel="",
        ),
        workspace=SimpleNamespace(session=session),
        agent=SimpleNamespace(state_dict=lambda: {"context": []}),
        session_id="warmup-session",
        mode_state={},
        extras={},
        error=None,
        session_state=None,
    )


@pytest.mark.parametrize("storage_format", ["current", "legacy", "pending"])
async def test_load_recovers_speech_journal_after_stale_agent_save(
    tmp_path, storage_format
):
    session = SafeJSONSession(str(tmp_path))
    ctx = _ctx(session, ephemeral=False)
    chat = SimpleNamespace(
        id="chat",
        session_id=ctx.session_id,
        user_id=ctx.request.user_id,
        channel=ctx.request.channel,
    )
    ctx.workspace.task_tracker = TaskTracker()
    journal = ChatTimelineJournal(ctx.workspace, chat)
    original = Msg(
        id="input",
        name="user",
        role="user",
        content=[TextBlock(text="DELEGATED_REQUEST")],
    )
    old = StateProxy()
    if storage_format == "current":
        old.data = {
            "state": AgentState(
                context=[original], summary="retained summary"
            ).model_dump(mode="json")
        }
    elif storage_format == "legacy":
        old.data = {
            "memory": {
                "content": [[original.model_dump(mode="json"), []]],
                "_compressed_summary": "retained summary",
            }
        }
    initial = {"source_id": "audio", "text": "PARTIAL_WORDS", "final": False}
    final = {**initial, "text": "FINAL_WORDS", "final": True}

    async def stale_save():
        await session.save_session_state(
            chat.session_id, chat.user_id, chat.channel, agent=old
        )

    await journal.append_speech_transcript("input", initial)
    await asyncio.gather(
        stale_save(), journal.append_speech_transcript("input", final)
    )
    # An Agent save that started before final ASR can finish after its commit.
    await stale_save()
    ctx.workspace.session = SafeJSONSession(str(tmp_path))
    ctx.workspace.task_tracker = TaskTracker()
    ctx.workspace.task_tracker.submit_or_start = AsyncMock()
    await SessionLoadHook().run(ctx)
    restored = AgentState.model_validate(ctx.session_state["state"])
    assert len(restored.context) == (2 if storage_format == "pending" else 3)
    if storage_format != "pending":
        assert restored.summary == "retained summary"
        assert restored.context[0].model_dump() == original.model_dump()

    agent = object.__new__(QwenPawAgent)
    agent.state = restored
    agent.context_config = SimpleNamespace(compression_tool_enabled=False)
    agent._get_system_prompt = AsyncMock(return_value="Test")
    agent.toolkit = SimpleNamespace(
        get_tool_schemas=AsyncMock(return_value=[])
    )
    agent._run_input_mailbox = None
    prepared = await agent._prepare_model_input()
    for formatter in (DashScopeChatFormatter, OpenAIChatFormatter):
        wire = json.dumps(await formatter().format(prepared["messages"]))
        assert wire.count("PARTIAL_WORDS") == 1
        assert wire.count("FINAL_WORDS") == 1
    visible = agentscope_msg_to_message(restored.context)
    assert len(visible) == (0 if storage_format == "pending" else 1)
    assert all(message.role == "user" for message in visible)
    ctx.workspace.task_tracker.submit_or_start.assert_not_awaited()

    # Loading does not consume pending data before the Agent has saved it.
    saved = await session.get_session_state_dict(
        chat.session_id, chat.user_id, chat.channel
    )
    assert len(pending_timeline_messages(saved)) == 2
    ctx.agent = SimpleNamespace(state_dict=lambda: ctx.session_state)
    await SessionSaveHook().run(ctx)
    assert await journal.reconcile() == 0
    await journal.append_speech_transcript("input", final)
    assert await journal.reconcile() == 0
    await SessionLoadHook().run(ctx)
    reloaded = AgentState.model_validate(ctx.session_state["state"])
    assert [m.id for m in reloaded.context] == [m.id for m in restored.context]


async def test_ephemeral_request_skips_session_load_and_save():
    session = _FakeSession()
    ctx = _ctx(session, ephemeral=True)

    await SessionLoadHook().run(ctx)
    await SessionSaveHook().run(ctx)

    assert session.loaded is False
    assert session.saved is False
    assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] is False


async def test_normal_request_loads_and_saves_session_state():
    session = _FakeSession()
    session.load_payload = {
        "mode_state": {"mission": {"active": True}},
    }
    ctx = _ctx(session, ephemeral=False)

    await SessionLoadHook().run(ctx)
    await SessionSaveHook().run(ctx)

    assert session.loaded is True
    assert session.saved is True
    assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] is True
    assert ctx.mode_state == {"mission": {"active": True}}
    assert session.saved_payload["mode_state"] == ctx.mode_state


async def test_failed_session_save_does_not_mark_turn_as_persisted():
    session = _FakeSession(save_error=RuntimeError("save failed"))
    ctx = _ctx(session, ephemeral=False)

    await SessionSaveHook().run(ctx)

    assert session.saved is False
    assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] is False


async def test_console_image_check_keeps_event_loop_responsive(monkeypatch):
    session = _FakeSession()
    session.load_payload = {"state": {"context": []}}
    ctx = _ctx(session, ephemeral=False)
    ctx.request.channel = "console"
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    completed = False

    def slow_repair(data):
        nonlocal completed
        assert data is ctx.session_state
        loop.call_soon_threadsafe(started.set)
        # A synchronous invocation must fail rather than hang the test suite.
        assert release.wait(timeout=3)
        completed = True

    monkeypatch.setattr(
        "qwenpaw.hooks.session.session_hook.repair_invalid_history_images",
        slow_repair,
    )
    task = asyncio.create_task(SessionLoadHook().run(ctx))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        assert not task.done()
        assert not completed
    finally:
        release.set()
        await task
    assert completed


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_repeated_cancel_waits_for_actual_save_before_returning(fail):
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowSession(_FakeSession):
        async def save_session_state(self, **kwargs):
            entered.set()
            await release.wait()
            return await super().save_session_state(**kwargs)

    session = SlowSession(save_error=OSError("disk full") if fail else None)
    ctx = _ctx(session, ephemeral=False)
    task = asyncio.create_task(SessionSaveHook().run(ctx))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] is False
    release.set()
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    assert session.saved is not fail
    assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] is not fail


@pytest.mark.asyncio
async def test_cancelled_wait_is_not_saved_as_resumable_work():
    from qwenpaw.runtime.reply_cycle import ReplyCycleContext
    from qwenpaw.runtime.runtime import Runtime

    session = _FakeSession()
    ctx = _ctx(session, ephemeral=False)
    cycle = ReplyCycleContext("run", "input")
    cycle.start_inputs(("input",))
    cycle.finish_reply("waiting")
    ctx.agent._reply_cycle_context = cycle
    ctx.agent.state_dict = lambda: {"waiting_inputs": cycle.waiting_inputs()}
    runtime = Runtime(workspace=ctx.workspace, app_services=None)
    await runtime._try_save_on_cancel(ctx)
    assert session.saved
    assert session.saved_payload["waiting_inputs"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cancelled", "failed"])
async def test_request_termination_is_persisted_once_and_scoped(outcome):
    from qwenpaw.runtime.reply_cycle import ReplyCycleContext
    from qwenpaw.runtime.runtime import Runtime

    session = _FakeSession()
    ctx = _ctx(session, ephemeral=False)
    cycle = ReplyCycleContext("run", "done")
    cycle.start_inputs(("done",))
    cycle.finish_reply("completed")
    cycle.activate(("old-request",))
    cycle.accept_input("queued-request")
    context = [
        Msg(
            id="old-request",
            name="user",
            role="user",
            content=[TextBlock(text="old")],
        )
    ]
    ctx.agent.state = SimpleNamespace(context=context)
    ctx.agent._reply_cycle_context = cycle
    ctx.agent.state_dict = lambda: {
        "state": {"context": [m.model_dump(mode="json") for m in context]}
    }
    runtime = Runtime(workspace=ctx.workspace, app_services=None)
    await runtime._try_save_on_cancel(ctx, outcome=outcome)
    await runtime._try_save_on_cancel(ctx, outcome=outcome)
    saved = session.saved_payload["state"]["context"]
    assert len(saved) == 2
    notice = saved[-1]
    assert notice["metadata"]["request_termination"] == {
        "run_id": "run",
        "input_ids": ["old-request", "queued-request"],
        "status": outcome,
    }
    assert "不再自动续做" in notice["content"][0]["text"]
    assert "明确重新提交" in notice["content"][0]["text"]
    next_cycle = ReplyCycleContext("next", "new-request")
    assert next_cycle.pending_input_ids() == ("new-request",)
