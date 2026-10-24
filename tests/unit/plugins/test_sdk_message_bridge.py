# -*- coding: utf-8 -*-
"""Public messages must not silently discard host message content."""

from types import SimpleNamespace

import pytest


def test_tool_call_round_trip_preserves_correlation_and_arguments():
    from agentscope.message import Msg, ToolCallBlock
    from qwenpaw.plugins._messages import from_host, to_host

    original = ToolCallBlock(
        id="call-123",
        name="calculate",
        input='{"x":3}',
        state="allowed",
    )
    public = from_host(
        Msg(name="assistant", role="assistant", content=[original]),
    )
    assert len(public.content) == 1
    assert public.content[0].type == "tool_call"
    restored = to_host(public).content[0]
    assert (restored.id, restored.name, restored.input, restored.state) == (
        "call-123",
        "calculate",
        '{"x":3}',
        "allowed",
    )


def test_tool_result_round_trip_preserves_error_and_multimodal_output():
    from agentscope.message import (
        DataBlock,
        Msg,
        TextBlock,
        ToolResultBlock,
        URLSource,
    )
    from qwenpaw.plugins._messages import from_host, to_host

    original = ToolResultBlock(
        id="call-123",
        name="generate",
        state="error",
        metadata={"retryable": True},
        output=[
            TextBlock(text="partial"),
            DataBlock(
                source=URLSource(
                    url="https://example.test/result.png",
                    media_type="image/png",
                ),
            ),
        ],
    )
    public = from_host(Msg(name="tool", role="assistant", content=[original]))
    assert len(public.content) == 1
    assert public.content[0].type == "tool_result"
    restored = to_host(public).content[0]
    assert restored.id == original.id and restored.name == original.name
    assert restored.state == "error" and restored.metadata == {
        "retryable": True,
    }
    assert restored.output[0].text == "partial"
    assert (
        str(restored.output[1].source.url) == "https://example.test/result.png"
    )
    assert restored.output[1].source.media_type == "image/png"


def test_unknown_host_block_is_rejected_instead_of_silently_removed():
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins._messages import from_host

    unknown = SimpleNamespace(type="future_block", value="must-not-disappear")
    message = SimpleNamespace(
        role="user",
        content=[unknown],
        name="user",
        metadata={},
    )
    with pytest.raises(SDKError):
        from_host(message)


def test_unknown_public_block_is_rejected_instead_of_silently_removed():
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins._messages import to_host
    from qwenpaw.plugins.messages import ContentBlock, Message

    with pytest.raises(SDKError):
        to_host(Message("user", (ContentBlock(type="future_block"),)))


def test_unsupported_message_role_raises_public_error():
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins._messages import to_host
    from qwenpaw.plugins.messages import ContentBlock, Message

    with pytest.raises(SDKError):
        to_host(Message("tool", (ContentBlock(text="unsupported role"),)))


def test_thinking_block_preserves_provider_extension_fields():
    from agentscope.message import Msg, ThinkingBlock
    from qwenpaw.plugins._messages import from_host, to_host

    original = ThinkingBlock(
        thinking="reason",
        metadata={"origin": "provider"},
        source="provider",
        name="trace",
    )
    restored = to_host(
        from_host(Msg(name="assistant", role="assistant", content=[original])),
    ).content[0]
    assert restored.model_dump() == original.model_dump()


def test_invalid_public_tool_state_raises_sdk_error():
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins._messages import to_host
    from qwenpaw.plugins.messages import ContentBlock, Message

    with pytest.raises(SDKError):
        to_host(
            Message(
                "assistant",
                (
                    ContentBlock(
                        "tool_call",
                        id="call",
                        name="tool",
                        state="invalid-state",
                    ),
                ),
            ),
        )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "author-value",
        {"format": "qwenpaw-attachment-previews/1", "refs": {}},
    ],
)
@pytest.mark.parametrize("with_preview", [False, True])
def test_public_metadata_collision_survives_round_trip(value, with_preview):
    from qwenpaw.plugins._messages import from_host, to_host
    from qwenpaw.plugins.messages import Attachment, ContentBlock, Message

    block = (
        ContentBlock(
            "image",
            attachment=Attachment(
                "file:///tmp/test.png",
                "image/png",
                "test.png",
                "/api/files/preview/test.png",
            ),
        )
        if with_preview
        else ContentBlock(text="unchanged")
    )
    metadata = {
        "_sdk_attachment_previews": value,
        "author": {"nested": ["keep"]},
    }
    restored = from_host(
        to_host(Message("assistant", (block,), metadata=metadata)),
    )
    assert restored.metadata == metadata
    if with_preview:
        assert restored.content[0].attachment == block.attachment


@pytest.mark.parametrize(
    "value",
    [
        None,
        "ordinary-host-value",
        {"format": "qwenpaw-attachment-previews/1", "refs": {}},
        {"format": "qwenpaw-attachment-previews/1", "refs": {"block": None}},
    ],
)
def test_ordinary_host_metadata_is_not_mistaken_for_sdk_envelope(value):
    from agentscope.message import DataBlock, Msg, URLSource
    from qwenpaw.plugins._messages import from_host

    metadata = {"_sdk_attachment_previews": value}
    original = Msg(
        name="assistant",
        role="assistant",
        metadata=metadata,
        content=[
            DataBlock(
                id="block",
                source=URLSource(
                    url="https://example.test/image.png",
                    media_type="image/png",
                ),
            ),
        ],
    )
    restored = from_host(original)
    assert restored.metadata == metadata
    assert (
        restored.content[0].attachment.url == "https://example.test/image.png"
    )


@pytest.mark.parametrize("kind", ["image", "tool_result", "hint"])
def test_preview_and_author_metadata_survive_host_json_history(kind):
    from agentscope.message import Msg
    from qwenpaw.plugins._messages import from_host, to_host
    from qwenpaw.plugins.messages import Attachment, ContentBlock, Message

    image = ContentBlock(
        "image",
        id="image-id",
        attachment=Attachment(
            "file:///tmp/history.png",
            "image/png",
            "history.png",
            "/api/files/preview/history.png",
        ),
    )
    block = (
        image
        if kind == "image"
        else ContentBlock(
            kind,
            id="result-id",
            name="generate",
            output=(image,),
        )
    )
    metadata = {
        "_sdk_attachment_previews": {
            "format": "qwenpaw-attachment-previews/1",
            "refs": {},
        },
        "_sdk_event": "author-event",
        "is_error": "author-value",
    }
    public = Message("assistant", (block,), metadata=metadata)
    saved = to_host(public).model_dump_json()
    restored = from_host(Msg.model_validate_json(saved))
    assert restored.metadata == metadata
    restored_image = (
        restored.content[0]
        if kind == "image"
        else restored.content[0].output[0]
    )
    assert restored_image.attachment == image.attachment


@pytest.mark.parametrize("kind", ["text", "thinking", "image"])
def test_content_block_metadata_survives_json_history(kind):
    from agentscope.message import Msg
    from qwenpaw.plugins._messages import from_host, to_host
    from qwenpaw.plugins.messages import Attachment, ContentBlock, Message

    original = ContentBlock(
        kind,
        text="content",
        metadata={"author": "keep"},
        attachment=(
            Attachment("https://example.test/a.png", "image/png")
            if kind == "image"
            else None
        ),
    )
    restored = from_host(
        Msg.model_validate_json(
            to_host(Message("assistant", (original,))).model_dump_json(),
        ),
    ).content[0]
    assert restored.metadata == original.metadata


@pytest.mark.parametrize("second_preview", ["/api/files/preview/b", ""])
def test_duplicate_attachment_ids_never_silently_replace_preview_reference(
    second_preview,
):
    from agentscope.message import Msg
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins._messages import from_host, to_host
    from qwenpaw.plugins.messages import Attachment, ContentBlock, Message

    images = tuple(
        ContentBlock(
            "image",
            id="same",
            attachment=Attachment(
                f"https://example.test/{name}.png",
                "image/png",
                preview_url=preview,
            ),
        )
        for name, preview in (
            ("a", "/api/files/preview/a"),
            ("b", second_preview),
        )
    )
    try:
        saved = to_host(Message("assistant", images)).model_dump_json()
    except SDKError:
        # Reject ambiguous IDs before publishing corrupt content.
        return
    restored = from_host(Msg.model_validate_json(saved))
    assert [block.attachment for block in restored.content] == [
        block.attachment for block in images
    ]


def test_author_tool_result_metadata_that_looks_like_full_codec_is_escaped():
    from agentscope.message import Msg
    from qwenpaw.plugins._messages import from_host, to_host
    from qwenpaw.plugins.messages import ContentBlock, Message

    metadata = {
        "_sdk_tool_result": {
            "format": "qwenpaw-tool-result/1",
            "block_ids": ["output"],
            "event": "end",
            "is_error": False,
            "original": {"claimed": "original"},
        },
    }
    block = ContentBlock(
        "tool_result",
        id="call",
        name="tool",
        output=(ContentBlock(text="result", id="output"),),
        metadata=metadata,
    )
    restored = from_host(
        Msg.model_validate_json(
            to_host(Message("assistant", (block,))).model_dump_json(),
        ),
    ).content[0]
    assert restored.metadata == metadata


@pytest.mark.parametrize("second_metadata", [{}, {"author": "second"}])
def test_duplicate_block_ids_never_silently_replace_metadata(second_metadata):
    from agentscope.message import Msg
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins._messages import from_host, to_host
    from qwenpaw.plugins.messages import ContentBlock, Message

    blocks = (
        ContentBlock(text="first", id="same", metadata={"author": "first"}),
        ContentBlock(text="second", id="same", metadata=second_metadata),
    )
    try:
        saved = to_host(Message("assistant", blocks)).model_dump_json()
    except SDKError:
        return
    restored = from_host(Msg.model_validate_json(saved))
    assert [block.metadata for block in restored.content] == [
        block.metadata for block in blocks
    ]


def test_tool_call_and_result_may_share_correlation_id():
    from agentscope.message import Msg
    from qwenpaw.plugins._messages import from_host, to_host
    from qwenpaw.plugins.messages import ContentBlock, Message

    blocks = (
        ContentBlock(
            "tool_call",
            id="correlation",
            name="tool",
            arguments="{}",
            metadata={"call": True},
        ),
        ContentBlock(
            "tool_result",
            id="correlation",
            name="tool",
            output="done",
            metadata={"result": True},
        ),
    )
    restored = from_host(
        Msg.model_validate_json(
            to_host(Message("assistant", blocks)).model_dump_json(),
        ),
    )
    assert [block.id for block in restored.content] == [
        "correlation",
        "correlation",
    ]
    assert [block.metadata for block in restored.content] == [
        {"call": True},
        {"result": True},
    ]
