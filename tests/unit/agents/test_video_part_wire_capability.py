# -*- coding: utf-8 -*-
"""Tests for video part wire-capability gating.

A tool result that carries a ``video/mp4`` data block used to be promoted
into an unconditional ``video_url`` content part.  OpenAI-compatible
endpoints that never implemented that extension reject the whole request at
the schema level — DeepSeek answers ``422 ... unknown variant `video_url`,
expected one of `text`, `image_url`, `file`` — and because the block is
replayed from stored history, the session stays broken forever.

These tests pin the two halves of the fix:

* ``_video_wire_allows_video`` decides whether the part may be emitted at
  all (wire shape + declared ``supports_video``);
* the placeholder paths keep the evidence (path, media type) as text; and
* ``QwenPawAgent._is_video_fallback_error`` recognises the schema rejection
  so an already-poisoned session can retry without video.
"""

# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.agents import model_factory
from qwenpaw.agents.model_factory import (
    _promote_tool_result_videos,
    _replace_video_placeholders,
    _video_wire_allows_video,
)
from qwenpaw.agents.react_agent import QwenPawAgent

DEEPSEEK_VIDEO_422 = (
    "Error code: 422 - {'error': {'message': 'Failed to deserialize the JSON "
    "body into the target type: messages[443]: unknown variant `video_url`, "
    "expected one of `text`, `image_url`, `file` at line 1 column 20498070'}}"
)

DEEPSEEK_IMAGE_400 = (
    "Error code: 400 - {'error': {'message': 'Failed to deserialize the JSON "
    "body into the target type: messages[106].image[0]: You have uploaded an "
    "unsupported image. Please make sure your image is valid and has one of "
    "the following formats: webp, png, jpeg, and gif.'}}"
)

VIDEO_BLOCK = {
    "type": "data",
    "source": {
        "type": "url",
        "url": "file:///D:/ProjectBlenderAgent/out/turntable.mp4",
        "media_type": "video/mp4",
    },
}
REMOTE_VIDEO_BLOCK = {
    "type": "data",
    "source": {
        "type": "url",
        "url": "https://example.com/turntable.mp4",
        "media_type": "video/mp4",
    },
}


# --------------------------------------------------------------------------
# wire capability
# --------------------------------------------------------------------------


def test_chat_completions_rejects_video_by_default() -> None:
    """`video_url` is a vendor extension, not part of the chat schema."""
    assert _video_wire_allows_video(model_factory.OpenAIChatFormatter) is False


def test_dashscope_formatter_keeps_video() -> None:
    assert (
        _video_wire_allows_video(model_factory.DashScopeChatFormatter) is True
    )


def test_declared_capability_wins_over_wire_rule() -> None:
    assert (
        _video_wire_allows_video(
            model_factory.OpenAIChatFormatter,
            declared=True,
        )
        is True
    )
    assert (
        _video_wire_allows_video(
            model_factory.DashScopeChatFormatter,
            declared=False,
        )
        is False
    )


def test_responses_api_keeps_input_video() -> None:
    assert (
        _video_wire_allows_video(
            model_factory.OpenAIResponseFormatter,
            response_api=True,
        )
        is True
    )


# --------------------------------------------------------------------------
# placeholder paths
# --------------------------------------------------------------------------


def test_replace_placeholders_emits_text_when_video_unsupported() -> None:
    placeholder = "__QWENPAW_VID_1__"
    messages: list[dict] = [
        {
            "role": "user",
            "content": [{"type": "text", "text": placeholder}],
        },
    ]
    _replace_video_placeholders(
        messages,
        {placeholder: VIDEO_BLOCK},
        allow_video=False,
    )

    parts = messages[0]["content"]
    assert [p["type"] for p in parts] == ["text"]
    assert "video not sent to the model" in parts[0]["text"]
    assert "turntable.mp4" in parts[0]["text"]
    assert "video/mp4" in parts[0]["text"]


def test_replace_placeholders_still_emits_video_when_supported() -> None:
    placeholder = "__QWENPAW_VID_2__"
    messages: list[dict] = [
        {
            "role": "user",
            "content": [{"type": "text", "text": placeholder}],
        },
    ]
    _replace_video_placeholders(
        messages,
        {placeholder: REMOTE_VIDEO_BLOCK},
        allow_video=True,
    )

    assert messages[0]["content"][0]["type"] == "video_url"


def _tool_result_msgs(block: dict | None = None) -> list:
    if block is None:
        block = VIDEO_BLOCK
    msg = SimpleNamespace(
        role="user",
        content=[
            {
                "type": "tool_result",
                "id": "call_00_CLpgK9evj9rxHoY6rqdn4781",
                "name": "send_file_to_user",
                "output": [
                    block,
                    {"type": "text", "text": "File sent successfully."},
                ],
            },
        ],
    )
    return [msg]


def _wire_messages() -> list[dict]:
    return [
        {
            "role": "tool",
            "tool_call_id": "call_00_CLpgK9evj9rxHoY6rqdn4781",
            "content": "File sent successfully.",
        },
    ]


def _all_parts(messages: list[dict]) -> list[dict]:
    """Flatten wire content parts, skipping string content (tool messages)."""
    parts: list[dict] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            parts.extend(p for p in content if isinstance(p, dict))
    return parts


def test_promoted_tool_result_video_becomes_text_when_unsupported() -> None:
    out = _promote_tool_result_videos(
        _tool_result_msgs(),
        _wire_messages(),
        allow_video=False,
    )

    parts = _all_parts(out)
    assert not any(p.get("type") == "video_url" for p in parts)
    joined = " ".join(p.get("text", "") for p in parts)
    assert "video not sent to the model" in joined
    assert "turntable.mp4" in joined


def test_promoted_tool_result_video_keeps_part_when_supported() -> None:
    """An explicit capability keeps the real part (remote URL form)."""
    msgs = _tool_result_msgs(REMOTE_VIDEO_BLOCK)
    out = _promote_tool_result_videos(
        msgs,
        _wire_messages(),
        allow_video=True,
    )

    parts = _all_parts(out)
    assert any(p.get("type") == "video_url" for p in parts)


# --------------------------------------------------------------------------
# schema-rejection detection
# --------------------------------------------------------------------------


def test_video_part_rejection_is_recognised() -> None:
    assert (
        QwenPawAgent._is_video_fallback_error(Exception(DEEPSEEK_VIDEO_422))
        is True
    )


def test_image_rejection_is_not_a_video_rejection() -> None:
    assert (
        QwenPawAgent._is_video_fallback_error(Exception(DEEPSEEK_IMAGE_400))
        is False
    )


def test_unrelated_errors_are_not_video_rejections() -> None:
    for text in (
        "Error code: 400 - rate limit exceeded",
        "Error code: 401 - invalid api key",
        "Connection reset by peer",
        "Error code: 422 - unknown variant `image_url`",
    ):
        assert QwenPawAgent._is_video_fallback_error(Exception(text)) is False


LMSTUDIO_VIDEO_400 = (
    "Error code: 400 - {'error': {'message': 'At most 0 video(s) may be "
    "provided in one prompt. (parameter=video)', 'type': 'BadRequestError', "
    "'param': 'video', 'code': 400}}"
)


def test_at_most_n_video_rejection_is_recognised() -> None:
    """The LM Studio wording tracked by issue #8290 rejects video too."""
    assert (
        QwenPawAgent._is_video_fallback_error(Exception(LMSTUDIO_VIDEO_400))
        is True
    )


def test_at_most_n_image_rejection_is_not_a_video_rejection() -> None:
    text = (
        "Error code: 400 - {'error': {'message': 'At most 0 image(s) may be "
        "provided in one prompt. (parameter=image)'}}"
    )
    assert QwenPawAgent._is_video_fallback_error(Exception(text)) is False
