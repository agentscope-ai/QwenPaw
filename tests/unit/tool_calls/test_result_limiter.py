# -*- coding: utf-8 -*-
"""Tests for execution-layer tool result limiting."""

from __future__ import annotations

import asyncio

from agentscope.message import DataBlock, TextBlock, ToolResultState, URLSource
from agentscope.tool import ToolResponse

from qwenpaw.constant import TRUNCATION_NOTICE_MARKER
from qwenpaw.tool_calls._context import ToolCallContext
from qwenpaw.tool_calls._result_limiter import ToolResultLimiter


def _ctx() -> ToolCallContext:
    return ToolCallContext(
        tool_call_id="call-1",
        tool_name="read_file",
        session_id="session-1",
        agent_id="agent-1",
        root_session_id="root-1",
        started_at=0.0,
        deadline=None,
        cancel_event=asyncio.Event(),
    )


def _response(
    *blocks: object,
    state: ToolResultState = ToolResultState.SUCCESS,
) -> ToolResponse:
    return ToolResponse(
        content=list(blocks),
        id="call-1",
        state=state,
        metadata={"source": "test"},
    )


def _text_response(text: str) -> ToolResponse:
    return _response(TextBlock(type="text", text=text))


def _text_blocks(response: ToolResponse) -> list[str]:
    return [
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ]


def _all_text(response: ToolResponse) -> str:
    return "".join(_text_blocks(response))


def _total_text_bytes(response: ToolResponse) -> int:
    return sum(len(text.encode("utf-8")) for text in _text_blocks(response))


def test_small_result_is_returned_unchanged(tmp_path):
    response = _text_response("hello")
    limiter = ToolResultLimiter(
        enabled=True,
        max_text_bytes=512,
        cache_dir=tmp_path,
    )

    result = limiter.limit(response, _ctx())

    assert result is response
    assert _all_text(result) == "hello"
    assert not list(tmp_path.iterdir())


def test_ascii_result_is_capped_and_original_is_cached(tmp_path):
    response = _text_response("a" * 2000)
    limiter = ToolResultLimiter(
        enabled=True,
        max_text_bytes=512,
        cache_dir=tmp_path,
    )

    result = limiter.limit(response, _ctx())

    assert _total_text_bytes(result) <= 512
    assert TRUNCATION_NOTICE_MARKER in _all_text(result)
    assert "Tool output truncated before entering agent context" in _all_text(
        result,
    )
    saved = list(tmp_path.iterdir())
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == "a" * 2000


def test_multibyte_result_is_capped_at_valid_utf8_boundary(tmp_path):
    response = _text_response("你好🙂" * 1000)
    limiter = ToolResultLimiter(
        enabled=True,
        max_text_bytes=700,
        cache_dir=tmp_path,
    )

    result = limiter.limit(response, _ctx())
    encoded = _all_text(result).encode("utf-8")

    assert len(encoded) <= 700
    assert encoded.decode("utf-8")


def test_multiple_text_blocks_share_one_budget(tmp_path):
    response = _response(
        TextBlock(type="text", text="a" * 600),
        TextBlock(type="text", text="b" * 600),
        TextBlock(type="text", text="c" * 600),
    )
    limiter = ToolResultLimiter(
        enabled=True,
        max_text_bytes=640,
        cache_dir=tmp_path,
    )

    result = limiter.limit(response, _ctx())

    assert _total_text_bytes(result) <= 640
    assert TRUNCATION_NOTICE_MARKER in _all_text(result)


def test_notice_counts_toward_total_limit(tmp_path):
    response = _text_response("x" * 5000)
    limiter = ToolResultLimiter(
        enabled=True,
        max_text_bytes=384,
        cache_dir=tmp_path,
    )

    result = limiter.limit(response, _ctx())

    assert _total_text_bytes(result) <= 384


def test_non_text_blocks_are_preserved(tmp_path):
    data_block = DataBlock(
        source=URLSource(
            url="https://example.com/image.png",
            media_type="image/png",
        ),
        name="image.png",
    )
    response = _response(
        TextBlock(type="text", text="a" * 1000),
        data_block,
        TextBlock(type="text", text="b" * 1000),
    )
    limiter = ToolResultLimiter(
        enabled=True,
        max_text_bytes=800,
        cache_dir=tmp_path,
    )

    result = limiter.limit(response, _ctx())

    assert data_block in result.content
    assert _total_text_bytes(result) <= 800


def test_response_identity_state_and_metadata_are_preserved(tmp_path):
    response = _response(
        TextBlock(type="text", text="error" * 1000),
        state=ToolResultState.ERROR,
    )
    limiter = ToolResultLimiter(
        enabled=True,
        max_text_bytes=512,
        cache_dir=tmp_path,
    )

    result = limiter.limit(response, _ctx())

    assert result.id == response.id
    assert result.state == ToolResultState.ERROR
    assert result.metadata == {"source": "test"}
    assert _total_text_bytes(result) <= 512


def test_cache_write_failure_still_caps_result(tmp_path):
    cache_path = tmp_path / "not-a-directory"
    cache_path.write_text("occupied", encoding="utf-8")
    response = _text_response("x" * 2000)
    limiter = ToolResultLimiter(
        enabled=True,
        max_text_bytes=512,
        cache_dir=cache_path,
    )

    result = limiter.limit(response, _ctx())

    assert _total_text_bytes(result) <= 512
    assert "full output could not be persisted" in _all_text(result).lower()


def test_disabled_limiter_returns_original_response(tmp_path):
    response = _text_response("x" * 2000)
    limiter = ToolResultLimiter(
        enabled=False,
        max_text_bytes=512,
        cache_dir=tmp_path,
    )

    result = limiter.limit(response, _ctx())

    assert result is response
