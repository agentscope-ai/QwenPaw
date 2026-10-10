# -*- coding: utf-8 -*-
"""Session hook persistence behavior."""

from __future__ import annotations

import asyncio
import threading
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
