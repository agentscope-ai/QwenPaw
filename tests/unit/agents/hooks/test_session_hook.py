# -*- coding: utf-8 -*-
"""Session hook persistence behavior."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from qwenpaw.agents.acp.meta import ACP_EPHEMERAL_META_KEY
from qwenpaw.hooks.session.session_hook import SessionLoadHook, SessionSaveHook
from qwenpaw.hooks.session.signals import SESSION_SAVE_SUCCEEDED_KEY

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
    )


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
    from agentscope.message import Msg, TextBlock
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
