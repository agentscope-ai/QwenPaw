"""Tests for typed model-output protocol normalization."""

from types import SimpleNamespace

import pytest
from agentscope.message import TextBlock, ThinkingBlock, ToolCallBlock
from agentscope.model import ChatResponse

from qwenpaw.agents.middlewares import ReasoningBoundaryMiddleware


async def call_middleware(result):
    async def next_handler(**_kwargs):
        return result

    return await ReasoningBoundaryMiddleware().on_model_call(
        SimpleNamespace(),
        {},
        next_handler,
    )


def text(response: ChatResponse) -> str:
    return "".join(
        block.text
        for block in response.content
        if isinstance(block, TextBlock)
    )


@pytest.mark.asyncio
async def test_normalizes_non_streaming_marker_after_typed_thinking():
    response = ChatResponse(
        content=[
            ThinkingBlock(thinking="private"),
            TextBlock(text="\n</think>\n\n答案"),
        ],
        is_last=True,
    )

    result = await call_middleware(response)

    assert result is response
    assert text(result) == "答案"


@pytest.mark.asyncio
async def test_preserves_literal_marker_without_typed_thinking():
    response = ChatResponse(
        content=[TextBlock(text="请解释 </think> 标签")],
        is_last=True,
    )

    result = await call_middleware(response)

    assert text(result) == "请解释 </think> 标签"


@pytest.mark.asyncio
async def test_preserves_incomplete_literal_after_typed_thinking():
    response = ChatResponse(
        content=[
            ThinkingBlock(thinking="private"),
            TextBlock(text="</thi", id="text-1"),
        ],
        is_last=True,
    )

    result = await call_middleware(response)

    assert text(result) == "</thi"


@pytest.mark.asyncio
async def test_normalizes_chunk_split_marker_for_live_and_final_output():
    async def responses():
        yield ChatResponse(
            content=[ThinkingBlock(thinking="private", id="thinking-1")],
            is_last=False,
            id="response-1",
        )
        yield ChatResponse(
            content=[TextBlock(text="\n</", id="text-1")],
            is_last=False,
            id="response-1",
        )
        yield ChatResponse(
            content=[TextBlock(text="think>\n答案", id="text-1")],
            is_last=False,
            id="response-1",
        )
        yield ChatResponse(
            content=[
                ThinkingBlock(thinking="private", id="thinking-1"),
                TextBlock(text="\n</think>\n答案", id="text-1"),
            ],
            is_last=True,
            id="response-1",
        )

    stream = await call_middleware(responses())
    chunks = [chunk async for chunk in stream]

    assert [text(chunk) for chunk in chunks if not chunk.is_last] == [
        "",
        "",
        "答案",
    ]
    assert text(chunks[-1]) == "答案"


@pytest.mark.asyncio
async def test_removes_standalone_marker_before_tool_call():
    response = ChatResponse(
        content=[
            ThinkingBlock(thinking="private"),
            TextBlock(text="\n</think>\n\n"),
            ToolCallBlock(id="call-1", name="test", input="{}"),
        ],
        is_last=True,
    )

    result = await call_middleware(response)

    assert not any(isinstance(block, TextBlock) for block in result.content)
    assert any(isinstance(block, ToolCallBlock) for block in result.content)
