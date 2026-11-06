# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression tests for request-local runtime context persistence."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agentscope.message import Msg
import pytest

from qwenpaw.constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    RUNTIME_CONTEXT_MESSAGE_TAG,
)
from qwenpaw.runtime.runtime import Runtime
from qwenpaw.runtime.hooks import HookResult
from qwenpaw.runtime.phases import Phase
from qwenpaw.hooks.session.session_hook import SessionSaveHook

pytestmark = [pytest.mark.unit, pytest.mark.p1]


def _message(name: str, role: str, text: str) -> Msg:
    return Msg(
        name=name,
        role=role,
        content=[{"type": "text", "text": text}],
    )


def _ctx(real_message: Msg):
    return SimpleNamespace(
        context_injections=[
            {"content": "dynamic page context", "priority": 10},
        ],
        input_msgs=[real_message],
        extras={},
        error=None,
        agent=SimpleNamespace(
            state=SimpleNamespace(context=[]),
        ),
    )


def test_context_is_visible_to_current_call_then_removed_from_agent_state():
    real_message = _message("user", "user", "real question")
    ctx = _ctx(real_message)

    Runtime._apply_context_injections(ctx)

    injected = ctx.input_msgs[0]
    assert injected.metadata[QWENPAW_MESSAGE_TAG_KEY] == (
        RUNTIME_CONTEXT_MESSAGE_TAG
    )
    assert ctx.input_msgs == [injected, real_message]

    # AgentScope saves reply_stream inputs into the in-memory context.
    ctx.agent.state.context.extend(ctx.input_msgs)
    assert Runtime._remove_applied_context_injection(ctx) is True
    assert ctx.agent.state.context == [real_message]


def test_multiple_turns_do_not_accumulate_runtime_context_messages():
    shared_context = []

    for turn in range(2):
        real_message = _message("user", "user", f"question {turn}")
        ctx = _ctx(real_message)
        ctx.agent.state.context = shared_context
        Runtime._apply_context_injections(ctx)
        shared_context.extend(ctx.input_msgs)
        Runtime._remove_applied_context_injection(ctx)

    assert [message.get_text_content() for message in shared_context] == [
        "question 0",
        "question 1",
    ]


async def test_cancel_and_error_save_path_excludes_runtime_context():
    saved = {}

    class FakeSession:
        async def save_session_state(self, **kwargs):
            saved.update(kwargs["agent"].state_dict())

    class FakeAgent:
        def __init__(self):
            self.state = SimpleNamespace(context=[])

        def state_dict(self):
            return {
                "state": {
                    "context": [
                        message.model_dump(mode="json")
                        for message in self.state.context
                    ],
                },
            }

    runtime = Runtime(workspace=SimpleNamespace(), app_services=None)
    real_message = _message("user", "user", "real question")
    ctx = _ctx(real_message)
    ctx.agent = FakeAgent()
    ctx.workspace = SimpleNamespace(session=FakeSession())
    ctx.request = SimpleNamespace(user_id="user-1", channel="console")
    ctx.session_id = "session-1"

    Runtime._apply_context_injections(ctx)
    ctx.agent.state.context.extend(ctx.input_msgs)
    await runtime._try_save_on_cancel(ctx)

    messages = saved["state"]["context"]
    assert [message["content"][0]["text"] for message in messages] == [
        "real question",
    ]


@pytest.mark.parametrize("outcome", ["normal", "cancel", "error", "close"])
async def test_runtime_lifecycle_does_not_save_injected_context(
    monkeypatch,
    outcome,
):
    """Exercise normal saves and every interrupted-stream persistence path."""
    saved = []
    observed = []
    real_message = _message("user", "user", "real question")
    ctx = _ctx(real_message)
    ctx.request = SimpleNamespace(user_id="user-1", channel="console")
    ctx.session_id = "session-1"
    ctx.mode_state = {}
    ctx.agent.state_dict = lambda: {
        "state": {
            "context": [
                message.model_dump(mode="json")
                for message in ctx.agent.state.context
            ],
        },
    }

    async def save_session_state(**kwargs):
        saved.append(deepcopy(kwargs["agent"].state_dict()))

    async def run_hook(phase, hook_ctx):
        if phase == Phase.POST_RESPONSE:
            return await SessionSaveHook().run(hook_ctx)
        return HookResult()

    workspace = SimpleNamespace(
        session=SimpleNamespace(save_session_state=save_session_state),
        plugins=SimpleNamespace(
            hook_registry=SimpleNamespace(run=run_hook),
            slash_command_registry=SimpleNamespace(
                dispatch=AsyncMock(return_value=None),
            ),
            modes=[],
        ),
    )
    ctx.workspace = workspace
    runtime = Runtime(workspace=workspace, app_services=None)
    monkeypatch.setattr(runtime, "_build_context", lambda _request: ctx)
    monkeypatch.setattr(
        "qwenpaw.runtime.runtime.AgentBuilder",
        lambda **_kwargs: SimpleNamespace(
            build=AsyncMock(return_value=ctx.agent),
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.runtime.runtime.record_agent_activity",
        AsyncMock(),
    )

    stream_event = object()

    async def execute(input_msgs):
        observed.extend(message.get_text_content() for message in input_msgs)
        ctx.agent.state.context.extend(deepcopy(input_msgs))
        yield stream_event
        if outcome == "cancel":
            raise asyncio.CancelledError()
        if outcome == "error":
            raise RuntimeError("interrupted model stream")

    monkeypatch.setattr(
        "qwenpaw.runtime.runtime.AgentExecutor",
        lambda *_args: SimpleNamespace(run=execute),
    )

    async def consume():
        stream = runtime.run({"session_id": ctx.session_id})
        async for event in stream:
            if outcome == "close" and event is stream_event:
                await stream.aclose()
                break

    if outcome in {"cancel", "error"}:
        error = asyncio.CancelledError if outcome == "cancel" else RuntimeError
        with pytest.raises(error):
            await consume()
    else:
        await consume()

    assert observed == ["dynamic page context", "real question"]
    assert len(saved) == 1
    assert [
        message["content"][0]["text"]
        for message in saved[0]["state"]["context"]
    ] == ["real question"]
