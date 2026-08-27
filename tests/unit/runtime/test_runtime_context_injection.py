# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression tests for request-local runtime context persistence."""

from __future__ import annotations

from types import SimpleNamespace

from agentscope.message import Msg
import pytest

from qwenpaw.constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    RUNTIME_CONTEXT_MESSAGE_TAG,
)
from qwenpaw.runtime.runtime import Runtime

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
