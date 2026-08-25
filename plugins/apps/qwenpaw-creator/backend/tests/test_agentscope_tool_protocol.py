# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

import asyncio

import pytest

from services.file_agent_runtime.tool_protocol import (
    NativeToolTextStream,
    NonNativeToolMarkupError,
    contains_non_native_tool_markup,
)


pytestmark = pytest.mark.unit


def test_native_text_stream_preserves_prose_across_tag_shaped_chunk_boundaries() -> (
    None
):
    async def scenario() -> list[str]:
        observed: list[str] = []

        async def collect(delta: str) -> None:
            observed.append(delta)

        stream = NativeToolTextStream(collect)
        await stream.feed("正在检查 <")
        await stream.feed("普通说明>")
        await stream.finalize("正在检查 <普通说明>")
        return observed

    assert "".join(asyncio.run(scenario())) == "正在检查 <普通说明>"


def test_native_text_stream_never_publishes_textual_tool_markup() -> None:
    async def scenario() -> list[str]:
        observed: list[str] = []

        async def collect(delta: str) -> None:
            observed.append(delta)

        stream = NativeToolTextStream(collect)
        with pytest.raises(NonNativeToolMarkupError):
            await stream.feed("说明\n<fun")
            await stream.feed(
                "ction=glob_search><parameter=pattern>x</parameter></function>",
            )
        return observed

    observed = asyncio.run(scenario())
    assert not contains_non_native_tool_markup("".join(observed))


def test_native_text_stream_rejects_non_streamed_textual_tool_markup() -> None:
    async def scenario() -> None:
        stream = NativeToolTextStream(None)
        with pytest.raises(NonNativeToolMarkupError):
            await stream.finalize(
                "<function=glob_search><parameter=pattern>story/outline.md"
                "</parameter></function></tool_call>",
            )

    asyncio.run(scenario())
