# -*- coding: utf-8 -*-
"""Test display filtering through both PawApp chat APIs."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.pawapp.app import _build_capability_router
from qwenpaw.pawapp.context import ChatReply as LegacyChatReply, PawAppContext
from qwenpaw.plugins._apps import CapabilityContext, Services, wire_event
from qwenpaw.plugins._events import chat_event
from qwenpaw.plugins.apps import ChatReply, ChatRequest
from qwenpaw.runtime.backends.streaming import TextStream
from qwenpaw.schemas import AgentResponse, MessageType, TextContent


@pytest.mark.parametrize("sdk", [False, True])
@pytest.mark.parametrize("answer", ["", "public answer"])
@pytest.mark.parametrize("final_response", [False, True])
def test_pawapp_chat_routes_filter_assistant_scaffolding(
    sdk,
    answer,
    final_response,
    tmp_path,
):
    note = f"<system-info>private note</system-info>{answer}"
    reasoning = "structured reasoning"
    raw_responses = []

    async def stream_query(_request):
        response = AgentResponse(object="response")
        raw_responses.append(response)
        stream = TextStream(response)
        for event in stream.push(MessageType.REASONING, reasoning):
            yield event
        for event in stream.push(MessageType.MESSAGE, note[:20]):
            yield event
        for event in stream.push(MessageType.MESSAGE, note[20:]):
            yield event
        for event in stream.finish():
            yield event
        if final_response:
            yield response

    class Context(PawAppContext):
        async def _get_workspace(self):
            return SimpleNamespace(
                workspace_dir=tmp_path,
                stream_query=stream_query,
            )

        async def ensure_chat_session(self, session_id):
            return True

    @asynccontextmanager
    async def invocation(**_kwargs):
        yield

    class PublicContext:
        app_id = "fixture"
        storage = None

        def __init__(self, context):
            self.services = Services(
                SimpleNamespace(_invocation=invocation, _guard=lambda: None),
                context,
                lambda: True,
            )

        def chat_stream(self, request: ChatRequest):
            return self.services._produce_chat(request)

        async def chat(self, request: ChatRequest):
            events = [event async for event in self.chat_stream(request)]
            return ChatReply(tuple(events))

    async def dependency():
        context = Context("fixture")
        return CapabilityContext(PublicContext(context)) if sdk else context

    app = FastAPI()
    kwargs = {"encode": wire_event, "managed_stream": True} if sdk else {}
    app.include_router(_build_capability_router(dependency, **kwargs))
    with TestClient(app) as client:
        stream = client.post("/chat/stream", json={"message": "hello"})
        reply = client.post("/chat", json={"message": "hello"})

    assert stream.status_code == reply.status_code == 200
    assert "private note" not in stream.text
    assert reasoning in stream.text
    frames = [
        json.loads(line[6:])
        for line in stream.text.splitlines()
        if line.startswith("data: ")
    ]
    message_id = raw_responses[0].output[-1].id
    contents = [
        event["text"]
        for event in frames
        if event["object"] == "content" and event["msg_id"] == message_id
    ]
    assert contents == ["", ""] + ([answer] if answer else [])
    assert reply.json() == {"text": answer}
    assert [item.output[-1].content[0].text for item in raw_responses] == [
        note,
        note,
    ]


@pytest.mark.parametrize("sdk", [False, True])
@pytest.mark.parametrize("answer", ["", "visible delta"])
def test_reply_delta_fallback_requires_an_assistant_message(sdk, answer):
    stream = TextStream(AgentResponse(object="response"))
    events = stream.push(MessageType.REASONING, "structured reasoning")
    if answer:
        events.extend(stream.push(MessageType.MESSAGE, answer))
    events.append(TextContent(text="orphan", msg_id="unknown", delta=True))

    if sdk:
        reply = ChatReply(tuple(map(chat_event, events)))
    else:
        reply = LegacyChatReply(events)
    assert reply.text == answer
