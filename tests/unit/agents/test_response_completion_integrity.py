# -*- coding: utf-8 -*-
"""Exercise completion integrity through real provider and agent code."""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from agentscope.agent import ReActConfig
from agentscope.credential import DashScopeCredential, OpenAICredential
from agentscope.event import ReplyEndEvent
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import (
    Base64Source,
    DataBlock,
    Msg,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    URLSource,
)
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse, FinishedReason
from agentscope.tool import Toolkit

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.app.chats.utils import (
    agentscope_msg_to_message,
    clean_display_text,
)
from qwenpaw.loop.gates import StopAction, StopHandlerResult
from qwenpaw.loop.gates.completion import CompletionRubricGate
from qwenpaw.providers.dashscope_provider import _DashScopeChatModelCompat
from qwenpaw.providers.fallback_chat_model import FallbackChatModel
from qwenpaw.providers.openai_chat_model_compat import OpenAIChatModelCompat
from qwenpaw.providers.retry_chat_model import RetryChatModel
from qwenpaw.runtime.envelope import Envelope
from qwenpaw.runtime.executor import AgentExecutor


@asynccontextmanager
async def model_response(provider, stream, replies, body=None):
    """Serve deterministic wire responses without a real model or API key."""
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        reply = replies[min(len(requests) - 1, len(replies) - 1)]
        content, reasoning, reason = reply
        message = {f"role": f"assistant", f"content": content}
        if reasoning:
            message[f"reasoning_content"] = reasoning
        common = {f"id": f"completion", f"created": 1, f"model": f"test"}
        if not stream:
            return httpx.Response(
                200,
                json={
                    **common,
                    f"object": f"chat.completion",
                    f"choices": [
                        {
                            f"index": 0,
                            f"message": message,
                            f"finish_reason": reason,
                        },
                    ],
                },
            )
        if body is not None:
            return httpx.Response(
                200,
                stream=body,
                headers={f"content-type": f"text/event-stream"},
            )
        frames = []
        for delta, finish in [(message, None), ({}, reason)]:
            chunk = {
                **common,
                f"object": f"chat.completion.chunk",
                f"choices": [
                    {f"index": 0, f"delta": delta, f"finish_reason": finish},
                ],
            }
            frames.append(f"data: {json.dumps(chunk)}\n\n")
        frames.append(f"data: [DONE]\n\n")
        return httpx.Response(
            200,
            text=f"".join(frames),
            headers={f"content-type": f"text/event-stream"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
    ) as client:
        credential_type, model_type = (
            (DashScopeCredential, _DashScopeChatModelCompat)
            if provider == f"dashscope"
            else (OpenAICredential, OpenAIChatModelCompat)
        )
        model = model_type(
            credential=credential_type(
                api_key=f"test-key",
                base_url=f"https://example.test/v1",
            ),
            model=f"test",
            stream=stream,
            max_retries=0,
            context_size=32768,
            client_kwargs={f"http_client": client},
        )
        try:
            yield model, requests
        finally:
            await model.client.close()


def make_agent(model):
    """Build the ordinary agent with an empty toolkit and no plugins."""
    return QwenPawAgent(
        name=f"test",
        model=RetryChatModel(model),
        system_prompt=f"Answer the question.",
        toolkit=Toolkit(tools=[]),
        react_config=ReActConfig(max_iters=3),
        middlewares=[],
        agent_config=AgentProfileConfig(id=f"test", name=f"Test"),
    )


def question():
    return Msg(
        name=f"user",
        role=f"user",
        content=[TextBlock(text=f"What is six times seven?")],
    )


@pytest.mark.parametrize(f"provider", [f"openai", f"dashscope"])
@pytest.mark.parametrize(f"stream", [False, True])
@pytest.mark.parametrize(
    f"content",
    [
        f"",
        f" \n",
        f"⟦ Internal index title ⟧",
        f"<!-- ⟦ Internal index title ⟧ -->",
        f"〚 Internal index title 〛",
        f"⟦ Unfinished index title",
    ],
)
async def test_empty_terminal_answer_is_not_completed(
    provider,
    stream,
    content,
):
    async with model_response(
        provider,
        stream,
        [(content, f"Thinking" if content else None, f"stop")],
    ) as (model, requests):
        agent = make_agent(model)
        with pytest.raises(RuntimeError, match=f"empty|answer|output"):
            _ = [event async for event in agent._reply(inputs=question())]
        assert len(requests) == 1


@pytest.mark.parametrize(f"provider", [f"openai", f"dashscope"])
@pytest.mark.parametrize(f"stream", [False, True])
async def test_thinking_only_still_continues(provider, stream):
    replies = [(None, f"Thinking", f"stop"), (f"42", None, f"stop")]
    async with model_response(provider, stream, replies) as (model, requests):
        events = [
            event
            async for event in make_agent(model)._reply(
                inputs=question(),
            )
        ]
        assert len(requests) == 2
        assert [
            e.get_text_content() for e in events if isinstance(e, Msg)
        ] == [
            f"42",
        ]
        assert any(isinstance(e, ReplyEndEvent) for e in events)


@pytest.mark.parametrize(f"provider", [f"openai", f"dashscope"])
@pytest.mark.parametrize(f"stream", [False, True])
@pytest.mark.parametrize(f"reason", [f"stop", f"length"])
async def test_finish_reason_survives_to_sse_and_history(
    provider,
    stream,
    reason,
):
    async with model_response(
        provider,
        stream,
        [(f"partial answer", None, reason)],
    ) as (model, _requests):
        agent = make_agent(model)
        envelope = Envelope(session_id=f"test")
        _ = [
            event
            async for event in AgentExecutor(agent, envelope).run(
                [question()],
            )
        ]
        final = [event async for event in envelope.finalize()][-1]
        completion = {
            f"finish_reason": reason,
            f"truncated": reason == f"length",
        }
        assert final.metadata[f"qwenpaw_model_completion"] == completion
        assert (
            agent.state.context[-1].metadata[f"qwenpaw_model_completion"]
            == completion
        )
        assert any(
            getattr(part, f"text", None) == f"partial answer"
            for message in final.output
            for part in message.content
        )
        restored = Msg.from_dict(agent.state.context[-1].model_dump())
        history = agentscope_msg_to_message(restored)
        assert (
            history[-1].metadata[f"metadata"][f"qwenpaw_model_completion"]
            == completion
        )


async def test_concurrent_provider_calls_keep_their_finish_reasons():
    async with model_response(
        f"openai",
        True,
        [(f"first", None, f"length"), (f"second", None, f"stop")],
    ) as (model, _requests):

        async def consume():
            response = await model(messages=[question()])
            chunks = []
            while True:
                try:
                    chunks.append(await asyncio.create_task(anext(response)))
                except StopAsyncIteration:
                    break
            return chunks[-1]

        first, second = await asyncio.gather(consume(), consume())
        reasons = [
            response.metadata[f"qwenpaw_model_completion"][f"finish_reason"]
            for response in (first, second)
        ]
        assert sorted(reasons) == [f"length", f"stop"]


class _BlockModel(ChatModelBase):
    """Return native blocks to exercise non-text and interruption paths."""

    def __init__(self, blocks, reason=FinishedReason.COMPLETED):
        super().__init__(
            credential=None,
            model=f"blocks",
            parameters=ChatModelBase.Parameters(),
            stream=False,
            context_size=32768,
        )
        self.blocks = blocks
        self.reason = reason
        self.formatter = OpenAIChatFormatter()

    async def __call__(self, *args, **kwargs):
        return ChatResponse(
            content=self.blocks,
            is_last=True,
            finished_reason=self.reason,
        )


@pytest.mark.parametrize(
    f"block",
    [
        DataBlock(source=Base64Source(media_type=f"image/png", data=f"YWJj")),
        DataBlock(
            source=URLSource(
                media_type=f"audio/wav",
                url=f"https://example.test/a.wav",
            ),
        ),
        ToolCallBlock(id=f"lookup", name=f"lookup", input=f"{{}}"),
    ],
)
async def test_valid_non_text_outputs_are_not_empty_answers(block):
    agent = make_agent(_BlockModel([block]))
    events = [event async for event in agent._reasoning()]
    assert events


async def test_cancelled_empty_response_keeps_interruption_semantics():
    agent = make_agent(_BlockModel([], FinishedReason.INTERRUPTED))
    events = [event async for event in agent._reasoning()]
    assert not any(isinstance(event, Msg) for event in events)
    assert events[-1].finished_reason == FinishedReason.INTERRUPTED


async def test_stop_handler_can_replace_an_empty_answer():
    agent = make_agent(_BlockModel([]))

    async def stop_handler(_message):
        return StopHandlerResult(
            action=StopAction.TERMINATE,
            final_message=Msg(
                name=f"test",
                role=f"assistant",
                content=[TextBlock(text=f"Explicit stop result")],
            ),
        )

    agent._run_stop_handlers = stop_handler
    events = [event async for event in agent._reasoning()]
    assert events[-1].get_text_content() == f"Explicit stop result"


async def test_stop_handler_can_continue_after_an_empty_answer():
    agent = make_agent(_BlockModel([]))

    async def stop_handler(_message):
        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            continuation_message=f"Finish the task.",
        )

    agent._run_stop_handlers = stop_handler
    events = [event async for event in agent._reasoning()]
    assert not any(isinstance(event, Msg) for event in events)
    assert agent.state.context[-1].get_text_content() == f"Finish the task."


async def test_empty_answer_produces_a_failed_sse_response():
    agent = make_agent(
        _BlockModel(
            [ThinkingBlock(thinking=f"Thought"), TextBlock(text=f" ")],
        ),
    )
    envelope = Envelope()
    with pytest.raises(RuntimeError) as failure:
        _ = [
            event
            async for event in AgentExecutor(agent, envelope).run([question()])
        ]
    final = [
        event async for event in envelope.error_envelope(str(failure.value))
    ][-1]
    assert final.status.value == f"failed"
    assert f"empty answer" in final.error[f"message"]


async def test_later_success_does_not_inherit_earlier_truncation():
    replies = [(None, f"Thinking", f"length"), (f"42", None, f"stop")]
    async with model_response(f"dashscope", True, replies) as (
        model,
        requests,
    ):
        envelope = Envelope()
        agent = make_agent(model)
        _ = [
            event
            async for event in AgentExecutor(agent, envelope).run([question()])
        ]
        final = [event async for event in envelope.finalize()][-1]
        assert len(requests) == 2
        assert final.metadata[f"qwenpaw_model_completion"] == {
            f"finish_reason": f"stop",
            f"truncated": False,
        }


@pytest.mark.parametrize(f"provider", [f"openai", f"dashscope"])
@pytest.mark.parametrize(f"stream", [False, True])
@pytest.mark.parametrize(
    f"headline",
    [f"⟦ Internal index title ⟧", f"<!-- ⟦ Internal index title ⟧ -->"],
)
async def test_visible_answer_keeps_original_headline_in_history(
    provider,
    stream,
    headline,
):
    """Validation must not mutate the text used by context and indexing."""
    content = f"42\n{headline}"
    async with model_response(
        provider,
        stream,
        [(content, None, f"stop")],
    ) as (model, _requests):
        agent = make_agent(model)
        events = [event async for event in agent._reply(inputs=question())]
        assert any(isinstance(event, ReplyEndEvent) for event in events)
        assert agent.state.context[-1].get_text_content() == content
        assert clean_display_text(content, f"assistant") == f"42"


def _reloaded_history_completion(agent):
    """Inspect metadata after a state reload and history conversion."""
    restored = make_agent(_BlockModel([]))
    restored.load_state_dict(agent.state_dict())
    messages = agentscope_msg_to_message(restored.state.context[-1])
    metadata = messages[-1].metadata[f"metadata"]
    return metadata.get(f"qwenpaw_model_completion")


@pytest.mark.parametrize(f"provider", [f"openai", f"dashscope"])
@pytest.mark.parametrize(f"stream", [False, True])
@pytest.mark.parametrize(
    (f"candidate_reason", f"evaluation_reason"),
    [
        (f"length", f"stop"),
        (f"stop", f"length"),
        (None, f"length"),
        (f"length", None),
    ],
)
async def test_rubric_preserves_selected_candidate_completion(
    provider,
    stream,
    candidate_reason,
    evaluation_reason,
):
    """Use the selected answer's reason for SSE and restored history."""
    replies = [
        (f"Candidate answer", None, candidate_reason),
        (f"COMPLETED", None, evaluation_reason),
    ]
    async with model_response(provider, stream, replies) as (model, requests):
        agent = make_agent(model)
        gate = CompletionRubricGate(prompt=f"Check the answer.")
        candidates = []
        candidate_metadata = []

        async def stop_handler(message):
            candidates.append(message)
            candidate_metadata.append(dict(message.metadata))
            return await gate.check(
                {f"final_msg": message, f"has_tool_calls": message is None},
            )

        agent._run_stop_handlers = stop_handler
        envelope = Envelope()
        _ = [
            event
            async for event in AgentExecutor(agent, envelope).run([question()])
        ]
        final = [event async for event in envelope.finalize()][-1]
        completion = (
            {
                f"finish_reason": candidate_reason,
                f"truncated": candidate_reason == f"length",
            }
            if candidate_reason is not None
            else None
        )
        assert len(requests) == 2
        assert candidates[0].get_text_content() == f"Candidate answer"
        assert (
            candidate_metadata[0].get(f"qwenpaw_model_completion")
            == completion
        )
        assert (
            candidates[0].metadata.get(f"qwenpaw_model_completion")
            == completion
        )
        assert final.status.value == f"completed"
        assert (final.metadata or {}).get(
            f"qwenpaw_model_completion",
        ) == completion
        assert _reloaded_history_completion(agent) == completion


@pytest.mark.parametrize(f"provider", [f"openai", f"dashscope"])
@pytest.mark.parametrize(f"stream", [False, True])
async def test_unknown_final_reason_clears_old_history_warning(
    provider,
    stream,
):
    """A later answer without finish metadata must clear an old warning."""
    replies = [(None, f"Thinking", f"length"), (f"42", None, None)]
    async with model_response(provider, stream, replies) as (model, requests):
        agent = make_agent(model)
        envelope = Envelope()
        _ = [
            event
            async for event in AgentExecutor(agent, envelope).run([question()])
        ]
        final = [event async for event in envelope.finalize()][-1]
        assert len(requests) == 2
        assert final.status.value == f"completed"
        assert not (final.metadata or {}).get(f"qwenpaw_model_completion")
        assert agent.state.context[-1].get_text_content() == f"42"
        assert _reloaded_history_completion(agent) is None


class _RateLimitedPrimary(_BlockModel):
    """Think once, then trigger the configured cross-provider fallback."""

    def __init__(self):
        super().__init__([ThinkingBlock(thinking=f"Thinking")])
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls > 1:
            raise httpx.HTTPStatusError(
                f"Rate limited",
                request=httpx.Request(f"POST", f"https://example.test/v1"),
                response=httpx.Response(429),
            )
        response = await super().__call__(*args, **kwargs)
        response.metadata[f"qwenpaw_model_completion"] = {
            f"finish_reason": f"length",
            f"truncated": True,
        }
        return response


async def test_successful_cross_provider_fallback_clears_history_warning():
    """A native fallback answer must not inherit the primary model limit."""
    native = _BlockModel([TextBlock(text=f"42")])
    native.model = f"native-fallback"
    agent = make_agent(FallbackChatModel([_RateLimitedPrimary(), native]))
    envelope = Envelope()
    _ = [
        event
        async for event in AgentExecutor(agent, envelope).run([question()])
    ]
    final = [event async for event in envelope.finalize()][-1]
    assert final.status.value == f"completed"
    assert not (final.metadata or {}).get(f"qwenpaw_model_completion")
    assert agent.state.context[-1].get_text_content() == f"42"
    assert _reloaded_history_completion(agent) is None


async def test_audio_only_reply_preserves_previous_reply_completion():
    """Audio omitted from context must not change a previous reply marker."""
    audio = DataBlock(
        source=Base64Source(media_type=f"audio/wav", data=f"YWJj"),
    )
    agent = make_agent(_BlockModel([audio]))
    metadata = {
        f"custom": f"keep",
        f"qwenpaw_model_completion": {
            f"finish_reason": f"length",
            f"truncated": True,
        },
    }
    previous = Msg(
        id=f"previous-reply",
        name=agent.name,
        role=f"assistant",
        content=[TextBlock(text=f"Previous answer")],
        metadata=metadata,
    )
    agent.state.context.append(previous)
    events = [event async for event in agent._reasoning()]
    assert any(isinstance(event, Msg) for event in events)
    assert agent.state.context == [previous]
    assert previous.metadata == metadata


def test_completion_metadata_clear_preserves_unrelated_metadata():
    """Removing a stale completion marker must preserve extension metadata."""
    agent = make_agent(_BlockModel([]))
    target = Msg(
        name=agent.name,
        role=f"assistant",
        content=[TextBlock(text=f"Answer")],
        metadata={
            f"custom": f"keep",
            f"qwenpaw_model_completion": {f"truncated": True},
        },
    )
    agent._attach_model_completion(target)
    assert target.metadata == {f"custom": f"keep"}


class _HangingBody(httpx.AsyncByteStream):
    """Keep a real HTTP response open after emitting partial text."""

    def __init__(self, error=None):
        self.closed = False
        self.waiting = asyncio.Event()
        self.error = error

    async def __aiter__(self):
        chunk = {
            f"id": f"partial",
            f"created": 1,
            f"model": f"test",
            f"object": f"chat.completion.chunk",
            f"choices": [
                {
                    f"index": 0,
                    f"finish_reason": None,
                    f"delta": {f"content": f"partial"},
                },
            ],
        }
        yield f"data: {json.dumps(chunk)}\n\n".encode()
        self.waiting.set()
        if self.error is not None:
            raise self.error
        await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize(f"provider", [f"openai", f"dashscope"])
async def test_abandoned_provider_stream_closes_http_response(provider):
    body = _HangingBody()
    async with model_response(
        provider,
        True,
        [(f"partial", None, f"stop")],
        body,
    ) as (model, _requests):
        stream = await model(messages=[question()])
        assert (await anext(stream)).content[0].text == f"partial"
        await asyncio.create_task(stream.aclose())
        assert body.closed


@pytest.mark.parametrize(f"provider", [f"openai", f"dashscope"])
async def test_cancelled_provider_stream_is_not_completed(provider):
    body = _HangingBody()
    async with model_response(
        provider,
        True,
        [(f"partial", None, f"stop")],
        body,
    ) as (model, _requests):
        stream = await model(messages=[question()])
        await anext(stream)
        pending = asyncio.create_task(anext(stream))
        await body.waiting.wait()
        pending.cancel()
        final = await pending
        assert final.finished_reason == FinishedReason.INTERRUPTED
        assert f"qwenpaw_model_completion" not in final.metadata
        await stream.aclose()
        assert body.closed


@pytest.mark.parametrize(f"provider", [f"openai", f"dashscope"])
async def test_transport_failure_after_text_does_not_become_success(provider):
    failure = httpx.ReadError(f"Connection dropped after partial output")
    body = _HangingBody(failure)
    async with model_response(
        provider,
        True,
        [(f"partial", None, f"stop")],
        body,
    ) as (model, _requests):
        stream = await model(messages=[question()])
        await anext(stream)
        with pytest.raises(httpx.ReadError) as error:
            await anext(stream)
        assert error.value is failure
        assert body.closed
