# -*- coding: utf-8 -*-
"""Tests for video size capping in the model_factory video helpers.

Tool-result videos inline through ``_format_openai_video_block`` and
``_format_anthropic_video_data_block`` rather than the capping formatters
(which only intercept ``_format_*_source``), so the inline byte cap is
enforced inside those helpers.  These tests pin that behaviour for both
the local-file (``file://`` / ``url``) and in-memory (``base64``) source
shapes, for both wire formats.
"""

# pylint: disable=protected-access,mixed-line-endings
from typing import Any, Callable

import pytest
from agentscope.message import DataBlock, Msg, URLSource

from qwenpaw.agents import model_factory
from qwenpaw.agents.model_factory import (
    MAX_INLINE_MEDIA_BYTES,
    _format_anthropic_video_data_block,
    _format_openai_video_block,
    _promote_tool_result_videos,
    _replace_video_placeholders,
    _video_oversize_placeholder,
)


def _write_video(tmp_path, name: str, size: int) -> str:
    """Write a ``size``-byte file and return its ``file://`` URL."""
    path = tmp_path / name
    path.write_bytes(b"\x00" * size)
    return f"file://{path}"


async def _format_prepared_local_video(
    formatter: Callable[..., Any],
    block: Any,
    base_formatter_class: type,
    *,
    max_bytes: int = MAX_INLINE_MEDIA_BYTES,
    **kwargs: Any,
) -> Any:
    """Call a pure formatter helper after async media preparation."""
    is_dict_block = isinstance(block, dict)
    if is_dict_block:
        source = block["source"]
        block = DataBlock(
            source=URLSource(
                url=source["url"],
                media_type=source.get("media_type", "video/mp4"),
            ),
        )
    msg = Msg(
        name="user",
        role="user",
        content=[block],
    )
    await model_factory._prepare_media_sources(
        [msg],
        base_formatter_class,
        max_bytes=max_bytes,
    )
    prepared = msg.content[0]
    if getattr(prepared, "type", None) == "text":
        return prepared.model_dump()
    if is_dict_block:
        prepared = prepared.model_dump()
    return formatter(prepared, **kwargs)


# --------------------------------------------------------------------- OpenAI


@pytest.mark.asyncio
async def test_openai_url_video_under_cap_is_inlined(tmp_path) -> None:
    url = _write_video(tmp_path, "small.mp4", MAX_INLINE_MEDIA_BYTES - 1024)
    block = {"source": {"type": "url", "url": url}}
    out = await _format_prepared_local_video(
        _format_openai_video_block,
        block,
        model_factory.OpenAIChatFormatter,
    )
    assert out["type"] == "video_url"
    assert out["video_url"]["url"].startswith("data:video/mp4;base64,")


@pytest.mark.asyncio
async def test_openai_url_video_over_cap_is_placeholder(tmp_path) -> None:
    url = _write_video(tmp_path, "big.mp4", MAX_INLINE_MEDIA_BYTES + 1)
    block = {"source": {"type": "url", "url": url}}
    out = await _format_prepared_local_video(
        _format_openai_video_block,
        block,
        model_factory.OpenAIChatFormatter,
    )
    assert out["type"] == "text"
    assert "video omitted from model context" in out["text"]
    assert str(MAX_INLINE_MEDIA_BYTES + 1) in out["text"]


def test_openai_base64_video_over_cap_is_placeholder() -> None:
    # base64 of (cap+1) raw bytes -> length * 3//4 > cap.
    import base64

    data = base64.b64encode(b"\x00" * (MAX_INLINE_MEDIA_BYTES + 1)).decode()
    block = {
        "source": {
            "type": "base64",
            "media_type": "video/mp4",
            "data": data,
        },
    }
    out = _format_openai_video_block(block)
    assert out["type"] == "text"
    assert "video omitted from model context" in out["text"]


def test_openai_base64_video_under_cap_is_inlined() -> None:
    import base64

    data = base64.b64encode(b"\x00" * 16).decode()
    block = {
        "source": {
            "type": "base64",
            "media_type": "video/mp4",
            "data": data,
        },
    }
    out = _format_openai_video_block(block)
    assert out["type"] == "video_url"
    assert out["video_url"]["url"].startswith("data:video/mp4;base64,")


def test_openai_remote_url_video_is_passed_through() -> None:
    block = {"source": {"type": "url", "url": "https://example.com/v.mp4"}}
    out = _format_openai_video_block(block)
    # Remote URL is not read from disk; pass through unchanged (no cap).
    assert out["video_url"]["url"] == "https://example.com/v.mp4"


# ------------------------------------------------------------------ Anthropic


@pytest.mark.asyncio
async def test_anthropic_url_video_over_cap_is_placeholder(tmp_path) -> None:
    url = _write_video(tmp_path, "big.mp4", MAX_INLINE_MEDIA_BYTES + 1)
    block = DataBlock(source=URLSource(url=url, media_type="video/mp4"))
    assert model_factory.AnthropicChatFormatter is not None
    out = await _format_prepared_local_video(
        _format_anthropic_video_data_block,
        block,
        model_factory.AnthropicChatFormatter,
    )
    assert out["type"] == "text"
    assert "video omitted from model context" in out["text"]


@pytest.mark.asyncio
async def test_anthropic_url_video_under_cap_is_inlined(tmp_path) -> None:
    url = _write_video(tmp_path, "small.mp4", MAX_INLINE_MEDIA_BYTES - 1024)
    block = DataBlock(source=URLSource(url=url, media_type="video/mp4"))
    assert model_factory.AnthropicChatFormatter is not None
    out = await _format_prepared_local_video(
        _format_anthropic_video_data_block,
        block,
        model_factory.AnthropicChatFormatter,
    )
    assert out["type"] == "video"
    assert out["source"]["type"] == "base64"
    assert out["source"]["media_type"] == "video/mp4"


def test_anthropic_base64_video_over_cap_is_placeholder() -> None:
    from agentscope.message import Base64Source

    import base64

    data = base64.b64encode(b"\x00" * (MAX_INLINE_MEDIA_BYTES + 1)).decode()
    block = DataBlock(
        source=Base64Source(type="base64", media_type="video/mp4", data=data),
    )
    out = _format_anthropic_video_data_block(block)
    assert out["type"] == "text"
    assert "video omitted from model context" in out["text"]


def test_anthropic_base64_video_under_cap_is_inlined() -> None:
    from agentscope.message import Base64Source

    import base64

    data = base64.b64encode(b"\x00" * 16).decode()
    block = DataBlock(
        source=Base64Source(type="base64", media_type="video/mp4", data=data),
    )
    out = _format_anthropic_video_data_block(block)
    assert out["type"] == "video"
    assert out["source"]["data"] == data


def test_anthropic_missing_file_returns_none(tmp_path) -> None:
    block = DataBlock(
        source=URLSource(
            url=f"file://{tmp_path / 'nope.mp4'}",
            media_type="video/mp4",
        ),
    )
    assert _format_anthropic_video_data_block(block) is None


# --------------------------------- OpenAI Responses API (input_video)


def test_openai_response_api_emits_input_video() -> None:
    import base64

    data = base64.b64encode(b"\x00" * 16).decode()
    block = {
        "source": {
            "type": "base64",
            "media_type": "video/mp4",
            "data": data,
        },
    }
    out = _format_openai_video_block(block, response_api=True)
    assert out["type"] == "input_video"
    assert out["video_url"].startswith("data:video/mp4;base64,")


def test_openai_response_api_remote_url() -> None:
    block = {
        "source": {
            "type": "url",
            "url": "https://example.com/v.mp4",
        },
    }
    out = _format_openai_video_block(block, response_api=True)
    assert out["type"] == "input_video"
    assert out["video_url"] == "https://example.com/v.mp4"


@pytest.mark.asyncio
async def test_openai_response_api_local_file(tmp_path) -> None:
    url = _write_video(tmp_path, "small.mp4", 64)
    block = {"source": {"type": "url", "url": url}}
    out = await _format_prepared_local_video(
        _format_openai_video_block,
        block,
        model_factory.OpenAIResponseFormatter,
        response_api=True,
    )
    assert out["type"] == "input_video"
    assert out["video_url"].startswith("data:video/mp4;base64,")


def test_openai_response_api_oversize_is_placeholder() -> None:
    import base64

    data = base64.b64encode(
        b"\x00" * (MAX_INLINE_MEDIA_BYTES + 1),
    ).decode()
    block = {
        "source": {
            "type": "base64",
            "media_type": "video/mp4",
            "data": data,
        },
    }
    out = _format_openai_video_block(block, response_api=True)
    assert out["type"] == "input_text"
    assert "video omitted" in out["text"]


# ------------------------------------------- _replace_video_placeholders


def _make_video_sub():
    import base64

    data = base64.b64encode(b"\x00" * 16).decode()
    key = "__QWENPAW_VID_test__"
    block = {
        "source": {
            "type": "base64",
            "media_type": "video/mp4",
            "data": data,
        },
    }
    return key, block


def _first_content_item(msgs: list[dict]) -> dict:
    """Return the first content item of the first message."""
    content = msgs[0]["content"]
    assert isinstance(content, list)
    return content[0]


def test_replace_placeholders_text_type() -> None:
    key, block = _make_video_sub()
    msgs: list[dict] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": key},
            ],
        },
    ]
    _replace_video_placeholders(msgs, {key: block})
    assert _first_content_item(msgs)["type"] == "video_url"


def test_replace_placeholders_input_text_type() -> None:
    key, block = _make_video_sub()
    msgs: list[dict] = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": key},
            ],
        },
    ]
    _replace_video_placeholders(msgs, {key: block})
    assert _first_content_item(msgs)["type"] == "video_url"


def test_replace_placeholders_skips_assistant_messages() -> None:
    key, block = _make_video_sub()
    msgs: list[dict] = [
        {
            "role": "assistant",
            "content": [
                {"type": "output_text", "text": key},
            ],
        },
    ]
    _replace_video_placeholders(msgs, {key: block})
    item = _first_content_item(msgs)
    assert item["type"] == "output_text"
    assert item["text"] == key


def test_replace_placeholders_response_api() -> None:
    key, block = _make_video_sub()
    msgs: list[dict] = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": key},
            ],
        },
    ]
    _replace_video_placeholders(
        msgs,
        {key: block},
        response_api=True,
    )
    item = _first_content_item(msgs)
    assert item["type"] == "input_video"


def test_replace_placeholders_non_match_untouched() -> None:
    key, block = _make_video_sub()
    msgs: list[dict] = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "hello"},
            ],
        },
    ]
    _replace_video_placeholders(msgs, {key: block})
    item = _first_content_item(msgs)
    assert item["type"] == "input_text"
    assert item["text"] == "hello"


# ---------------------------------------------------------------------
# _promote_tool_result_videos — Responses API (call_id) + chat (tool_call_id)
# ---------------------------------------------------------------------


def _make_tool_result_video_msg() -> tuple[object, dict]:
    """Build a Msg whose assistant content holds a tool_call + tool_result
    whose output carries a video DataBlock (base64 source so it does not
    depend on a real file), plus the promoted-video block."""
    import base64
    import json

    from agentscope.message import (
        Base64Source,
        TextBlock,
        ToolCallBlock,
        ToolResultBlock,
    )
    from agentscope.message import ToolCallState, ToolResultState

    data = base64.b64encode(b"\x00" * 16).decode()
    video_block = {
        "source": {
            "type": "base64",
            "media_type": "video/mp4",
            "data": data,
        },
    }
    call_block = ToolCallBlock(
        id="call_video_1",
        name="view_video",
        input=json.dumps({"video_path": "/tmp/sample.mp4"}),
        state=ToolCallState.FINISHED,
    )
    result_block = ToolResultBlock(
        id="call_video_1",
        name="view_video",
        output=[
            DataBlock(
                source=Base64Source(
                    data=data,
                    media_type="video/mp4",
                ),
            ),
            TextBlock(type="text", text="Video loaded: sample.mp4"),
        ],
        state=ToolResultState.SUCCESS,
    )
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[call_block, result_block],
    )
    return msg, video_block


def test_promote_tool_result_videos_response_api_call_id() -> None:
    """Responses API emits ``call_id``; the promoted user message carrying
    the video must be inserted after the ``function_call_output`` item."""
    import json

    msg, _ = _make_tool_result_video_msg()
    messages: list[dict] = [
        {"role": "user", "content": [{"type": "input_text", "text": "q"}]},
        {
            "type": "function_call",
            "call_id": "call_video_1",
            "name": "view_video",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "call_video_1",
            "output": "Video loaded: sample.mp4",
        },
    ]
    out = _promote_tool_result_videos([msg], messages, response_api=True)
    # exactly one promoted user message with an input_video block
    promoted = [
        m
        for m in out
        if m.get("role") == "user" and "system-info" in json.dumps(m)
    ]
    assert len(promoted) == 1
    s = json.dumps(promoted[0])
    assert "input_video" in s
    # promotion must follow the function_call_output (not before it)
    assert out.index(promoted[0]) > out.index(messages[2])


def test_promote_tool_result_videos_skips_function_call() -> None:
    """The assistant ``function_call`` item also carries ``call_id`` but is
    NOT a tool result; it must not trigger a duplicate promotion."""
    import json

    msg, _ = _make_tool_result_video_msg()
    messages: list[dict] = [
        {
            "type": "function_call",
            "call_id": "call_video_1",
            "name": "view_video",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "call_video_1",
            "output": "Video loaded: sample.mp4",
        },
    ]
    out = _promote_tool_result_videos([msg], messages, response_api=True)
    promoted = [
        m
        for m in out
        if m.get("role") == "user" and "system-info" in json.dumps(m)
    ]
    assert len(promoted) == 1


def test_promote_tool_result_videos_chat_tool_call_id() -> None:
    """OpenAI chat format uses ``tool_call_id``; promotion still works
    (no regression on the chat path)."""
    import json

    msg, _ = _make_tool_result_video_msg()
    messages: list[dict] = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_video_1",
                    "type": "function",
                    "function": {"name": "view_video", "arguments": "{}"},
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_video_1",
            "content": "Video loaded: sample.mp4",
        },
    ]
    out = _promote_tool_result_videos([msg], messages, response_api=False)
    promoted = [
        m
        for m in out
        if m.get("role") == "user" and "system-info" in json.dumps(m)
    ]
    assert len(promoted) == 1
    assert "video_url" in json.dumps(promoted[0])


# ------------------------------------------------------- configurable cap


@pytest.mark.asyncio
async def test_openai_url_video_over_default_but_under_custom_cap(
    tmp_path,
) -> None:
    """A 3 MB video exceeds a 2 MB default but fits a 50 MB provider cap."""
    url = _write_video(tmp_path, "mid.mp4", 3 * 1024 * 1024)
    block = {"source": {"type": "url", "url": url}}

    # Default 2 MB cap -> placeholder.
    default_out = await _format_prepared_local_video(
        _format_openai_video_block,
        block,
        model_factory.OpenAIChatFormatter,
    )
    assert default_out["type"] == "text"
    assert "video omitted from model context" in default_out["text"]

    # Provider-raised cap -> inlined (issue #7060).
    custom_out = await _format_prepared_local_video(
        _format_openai_video_block,
        block,
        model_factory.OpenAIChatFormatter,
        max_bytes=50 * 1024 * 1024,
        max_inline_media_bytes=50 * 1024 * 1024,
    )
    assert custom_out["type"] == "video_url"
    assert custom_out["video_url"]["url"].startswith(
        "data:video/mp4;base64,",
    )


def test_openai_base64_video_honors_custom_cap() -> None:
    """base64 sources must also respect a configurable cap."""
    import base64

    data = base64.b64encode(b"\x00" * (3 * 1024 * 1024)).decode()
    block = {
        "source": {
            "type": "base64",
            "media_type": "video/mp4",
            "data": data,
        },
    }

    default_out = _format_openai_video_block(block)
    assert default_out["type"] == "text"

    custom_out = _format_openai_video_block(
        block,
        max_inline_media_bytes=50 * 1024 * 1024,
    )
    assert custom_out["type"] == "video_url"


def test_openai_base64_video_zero_cap_disables_capping() -> None:
    """``max_inline_media_bytes <= 0`` must disable the cap (issue #7060)."""
    import base64

    data = base64.b64encode(b"\x00" * (3 * 1024 * 1024)).decode()
    block = {
        "source": {
            "type": "base64",
            "media_type": "video/mp4",
            "data": data,
        },
    }

    # Default cap -> placeholder.
    assert _format_openai_video_block(block)["type"] == "text"

    # Zero cap -> no capping, video inlined.
    out = _format_openai_video_block(block, max_inline_media_bytes=0)
    assert out["type"] == "video_url"
    assert out["video_url"]["url"].startswith("data:video/mp4;base64,")


@pytest.mark.asyncio
async def test_anthropic_url_video_honors_custom_cap(tmp_path) -> None:
    """Anthropic path: provider cap must override the hardcoded 2 MB."""
    url = _write_video(tmp_path, "mid.mp4", 3 * 1024 * 1024)
    block = DataBlock(source=URLSource(url=url, media_type="video/mp4"))

    default_out = await _format_prepared_local_video(
        _format_anthropic_video_data_block,
        block,
        model_factory.AnthropicChatFormatter,
    )
    assert default_out["type"] == "text"
    assert "video omitted from model context" in default_out["text"]

    custom_out = await _format_prepared_local_video(
        _format_anthropic_video_data_block,
        block,
        model_factory.AnthropicChatFormatter,
        max_bytes=50 * 1024 * 1024,
        max_inline_media_bytes=50 * 1024 * 1024,
    )
    assert custom_out["type"] == "video"
    assert custom_out["source"]["type"] == "base64"


def test_oversize_placeholder_reports_custom_limit() -> None:
    """The placeholder text must echo the configurable cap, not 2 MB."""
    out = _video_oversize_placeholder(
        3 * 1024 * 1024,
        max_inline_media_bytes=50 * 1024 * 1024,
    )
    assert "52428800 bytes" in out["text"]
    assert "2097152" not in out["text"]
