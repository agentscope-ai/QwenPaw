# -*- coding: utf-8 -*-
"""Session headers survive task-per-event streaming and early teardown."""

import asyncio

import httpx
import openai
import pytest
from agentscope.agent import Agent

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.exceptions import (
    ModelContextLengthExceededException,
    UnauthorizedModelAccessException,
    convert_model_exception,
)
from qwenpaw.providers.adapters.request_context import session_header
from qwenpaw.runtime.heartbeat import _iter_with_heartbeat


def bare_agent(session):
    agent = object.__new__(QwenPawAgent)
    agent._request_context = {f"session_id": session}
    agent._model_session_id = f"fallback"
    return agent


async def test_heartbeat_stream_keeps_header_and_resets_consumer(monkeypatch):
    observed = []

    async def reply(self, **kwargs):
        for index in range(3):
            observed.append(session_header(f"missing"))
            yield index

    monkeypatch.setattr(Agent, f"_reply", reply)
    stream = bare_agent(f"first")._reply()
    assert [item async for item in _iter_with_heartbeat(stream, 1)] == [
        0,
        1,
        2,
    ]
    assert len(set(observed)) == 1
    assert observed[0] != f"missing"
    assert session_header(f"outside") == f"outside"


async def test_early_close_in_another_task_preserves_session(monkeypatch):
    observed = []

    async def reply(self, **kwargs):
        try:
            observed.append(session_header(f"missing"))
            yield f"text"
        finally:
            observed.append(session_header(f"missing"))

    monkeypatch.setattr(Agent, f"_reply", reply)
    stream = bare_agent(f"first")._reply()
    assert await asyncio.create_task(anext(stream)) == f"text"
    await asyncio.create_task(stream.aclose())
    assert len(observed) == 2
    assert observed[0] == observed[1] != f"missing"
    assert session_header(f"outside") == f"outside"


async def test_original_provider_denial_is_not_masked(monkeypatch):
    request = httpx.Request(f"POST", f"https://example.test/chat")
    denial = openai.PermissionDeniedError(
        f"Free tier can only be used from within OpenCode",
        response=httpx.Response(403, request=request),
        body=None,
    )

    async def reply(self, **kwargs):
        yield f"text"
        raise denial

    monkeypatch.setattr(Agent, f"_reply", reply)
    stream = bare_agent(f"first")._reply()
    assert await asyncio.create_task(anext(stream)) == f"text"
    with pytest.raises(openai.PermissionDeniedError) as error:
        await asyncio.create_task(anext(stream))
    assert error.value is denial
    assert isinstance(
        convert_model_exception(error.value, f"mimo-v2.5-free"),
        UnauthorizedModelAccessException,
    )


async def test_concurrent_sessions_do_not_share_headers(monkeypatch):
    async def reply(self, **kwargs):
        for _ in range(2):
            await asyncio.sleep(0)
            yield session_header(f"missing")

    monkeypatch.setattr(Agent, f"_reply", reply)

    async def consume(session):
        stream = bare_agent(session)._reply()
        return [item async for item in _iter_with_heartbeat(stream, 1)]

    first, second = await asyncio.gather(consume(f"a"), consume(f"b"))
    assert first[0] == first[1]
    assert second[0] == second[1]
    assert first[0] != second[0]


@pytest.mark.parametrize(
    f"message,overflow",
    [
        (f"Token model_session was created in a different Context", False),
        (f"maximum context length exceeded", True),
        (f"context_length_exceeded", True),
        (f"too many tokens", True),
    ],
)
def test_context_error_classification(message, overflow):
    error = convert_model_exception(ValueError(message), f"test")
    assert isinstance(error, ModelContextLengthExceededException) is overflow


async def test_cancelled_pull_closes_with_its_session(monkeypatch):
    entered = asyncio.Event()
    observed = []

    async def reply(self, **kwargs):
        try:
            observed.append(session_header(f"missing"))
            yield f"text"
            entered.set()
            await asyncio.Event().wait()
        finally:
            observed.append(session_header(f"missing"))

    monkeypatch.setattr(Agent, f"_reply", reply)
    stream = bare_agent(f"first")._reply()
    await asyncio.create_task(anext(stream))
    pending = asyncio.create_task(anext(stream))
    await entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert len(observed) == 2
    assert observed[0] == observed[1] != f"missing"
    assert session_header(f"outside") == f"outside"
