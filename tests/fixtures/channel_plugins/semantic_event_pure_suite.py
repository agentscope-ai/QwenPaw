"""Complete legacy extractor branches at the neutral renderer/protocol seam."""
import pytest


def render(message, **settings):
    from qwenpaw.app.channels.renderer import (
        ChannelDisplayConfig,
        MessageRenderer,
        RenderStyle,
    )

    renderer = MessageRenderer(
        RenderStyle(display_config=ChannelDisplayConfig(**settings))
    )
    rows = renderer.message_to_semantic_parts(message)
    return renderer, rows


def message(content=(), kind="message", role="assistant"):
    from qwenpaw.schemas import Message

    return Message(
        object="message",
        type=kind,
        role=role,
        status="completed",
        content=list(content),
    )


def normalized(rows):
    return [
        (row.role, row.part.model_dump(mode="json", exclude_none=True))
        for row in rows
    ]


def test_original_text_extraction_keeps_message_provenance():
    from qwenpaw.schemas import TextContent

    _, rows = render(message([TextContent(text="Hello World")]))
    assert len(rows) == 1
    assert rows[0].role == "message"
    assert rows[0].part.type == "text"
    assert rows[0].part.text == "Hello World"


@pytest.mark.parametrize(
    "headline", ["⟦ 当前格式的内部检索标题 ⟧", "<!-- ⟦ 旧格式的内部检索标题 ⟧ -->"]
)
def test_original_scroll_headline_variants_do_not_escape(headline):
    from qwenpaw.schemas import TextContent

    _, rows = render(message([TextContent(text=f"正常答复\n{headline}")]))
    assert len(rows) == 1 and rows[0].role == "message"
    assert rows[0].part.text == "正常答复"


def test_original_empty_content_retains_rendered_fallback():
    from types import SimpleNamespace

    _, rows = render(SimpleNamespace(type="message", content=[]))
    assert len(rows) == 1
    assert rows[0].role == "rendered"
    assert rows[0].part.type == "text"
    assert "message" in rows[0].part.text


@pytest.mark.parametrize("visible", [True, False])
def test_original_hidden_tool_results_keep_media_without_placeholder(visible):
    from qwenpaw.schemas import DataContent

    event = message(
        [
            DataContent(
                data={
                    "name": "image_tool",
                    "output": [
                        {"type": "text", "text": "hidden"},
                        {
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": "https://example.com/image.png",
                            },
                        },
                    ],
                }
            )
        ],
        kind="plugin_call_output",
        role="tool",
    )
    renderer, rows = render(event, show_tool_results=visible)
    media = [row for row in rows if row.part.type == "image"]
    text = [row for row in rows if row.part.type == "text"]
    assert (
        len(media) == 1
        and media[0].part.image_url == "https://example.com/image.png"
    )
    assert all(row.role == "rendered" for row in rows)
    assert [row.part for row in rows] == renderer.message_to_parts(event)
    if visible:
        assert any("hidden" in row.part.text for row in text)
    else:
        assert text == []


@pytest.mark.parametrize(
    "headline", ["⟦ current headline ⟧", "<!-- ⟦ legacy headline ⟧ -->"]
)
@pytest.mark.parametrize("visible", [True, False])
def test_completed_reasoning_visibility_and_headline_cleaning(
    headline, visible
):
    from qwenpaw.schemas import TextContent

    _, rows = render(
        message([TextContent(text=f"thought\n{headline}")], kind="reasoning"),
        show_thinking=visible,
    )
    assert [(row.role, row.part.text) for row in rows] == (
        [("reasoning", "thought")] if visible else []
    )


@pytest.mark.parametrize("visible", [True, False])
def test_mixed_embedded_data_thinking_text_refusal_and_rendered_fallback_order(
    visible,
):
    from qwenpaw.schemas import DataContent, RefusalContent, TextContent

    content = [
        TextContent(text="before"),
        DataContent(
            data={
                "blocks": [
                    {"type": "text", "text": "not thinking"},
                    {"type": "thinking", "thinking": "deep\n⟦ remove ⟧"},
                ],
                "name": "fallback_tool",
                "output": "fallback output",
            }
        ),
        RefusalContent(refusal="raw refusal"),
        TextContent(text="after"),
    ]
    _, rows = render(message(content), show_thinking=visible)
    roles = [row.role for row in rows]
    assert roles == (
        ["message", "reasoning", "rendered", "refusal", "message"]
        if visible
        else ["message", "rendered", "refusal", "message"]
    )
    assert rows[0].part.text == "before" and rows[-1].part.text == "after"
    assert (
        next(row.part.refusal for row in rows if row.role == "refusal")
        == "raw refusal"
    )
    assert "fallback output" in next(
        row.part.text for row in rows if row.role == "rendered"
    )
    if visible:
        assert (
            next(row.part.text for row in rows if row.role == "reasoning")
            == "deep"
        )


@pytest.mark.parametrize(
    "blocks",
    [
        None,
        {},
        "invalid",
        [None, "invalid", {"type": "thinking", "thinking": ""}],
    ],
)
def test_non_thinking_or_malformed_data_blocks_preserve_fallback(blocks):
    from qwenpaw.schemas import DataContent

    _, rows = render(message([DataContent(data={"blocks": blocks})]))
    assert len(rows) == 1 and rows[0].role == "rendered"
    assert rows[0].part.text == "[Message type: MessageType.MESSAGE]"


def test_ordinary_event_media_retains_message_provenance_not_tool_rendered():
    from qwenpaw.schemas import (
        ImageContent,
        VideoContent,
        AudioContent,
        FileContent,
    )

    _, rows = render(
        message(
            [
                ImageContent(image_url="https://example.com/a.png"),
                VideoContent(video_url="https://example.com/a.mp4"),
                AudioContent(data="https://example.com/a.mp3"),
                FileContent(
                    file_url="https://example.com/a.pdf", filename="a.pdf"
                ),
            ]
        )
    )
    assert [row.role for row in rows] == ["message"] * 4
    assert [row.part.type for row in rows] == [
        "image",
        "video",
        "audio",
        "file",
    ]


def send_mapping(source, part):
    return {
        "channel_key": "external",
        "instance_id": "instance",
        "generation": 1,
        "delivery_id": "delivery",
        "to_handle": "route",
        "operation": "message.create",
        "content_source": source,
        "content_parts": [part],
    }


@pytest.mark.parametrize(
    "role", ["message", "reasoning", "refusal", "rendered"]
)
def test_event_text_roles_roundtrip_but_inbound_roles_remain_forbidden(role):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.channel_protocol.models import (
        SendParams,
        validate_content_part,
    )

    part = {"type": "text", "text": "original", "role": role}
    assert SendParams.from_mapping(send_mapping("event", part)).to_mapping()[
        "content_parts"
    ] == [part]
    with pytest.raises(ProtocolValidationError):
        validate_content_part(part)


@pytest.mark.parametrize("source", ["direct", "content_parts", "media"])
def test_non_event_sources_cannot_smuggle_roles(source):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.channel_protocol.models import SendParams

    with pytest.raises(ProtocolValidationError):
        SendParams.from_mapping(
            send_mapping(
                source, {"type": "text", "text": "x", "role": "message"}
            )
        )


@pytest.mark.parametrize("role", ["reasoning", "refusal", "arbitrary", ""])
def test_event_media_rejects_reasoning_refusal_and_unknown_roles(role):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.channel_protocol.models import SendParams

    with pytest.raises(ProtocolValidationError):
        SendParams.from_mapping(
            send_mapping(
                "event",
                {
                    "type": "image",
                    "image_url": "https://example.com/a.png",
                    "role": role,
                },
            )
        )


@pytest.mark.parametrize("role", ["message", "rendered"])
def test_event_media_preserves_allowed_provenance(role):
    from qwenpaw.channel_protocol.models import SendParams

    part = {
        "type": "image",
        "image_url": "https://example.com/a.png",
        "role": role,
    }
    assert SendParams.from_mapping(send_mapping("event", part)).to_mapping()[
        "content_parts"
    ] == [part]


@pytest.mark.parametrize(
    "capabilities,source,allowed",
    [
        ([], "event", False),
        ([], "direct", False),
        (["send.semantic_parts.v1"], "event", True),
        (["send.semantic_parts.v1"], "direct", False),
        (["send.content_source.v1"], "event", False),
        (["send.content_source.v1"], "direct", True),
    ],
)
def test_actual_worker_validation_requires_the_correct_source_capability(
    capabilities, source, allowed
):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.channel_protocol.shared_worker import ChannelRuntime

    runtime = ChannelRuntime()
    runtime._capabilities = capabilities
    part = {"type": "text", "text": "x"}
    if source == "event":
        part["role"] = "message"
    value = send_mapping(source, part)
    if allowed:
        assert (
            runtime._validate_params("channel.send", value).to_mapping()
            == value
        )
    else:
        with pytest.raises(ProtocolValidationError) as caught:
            runtime._validate_params("channel.send", value)
        assert caught.value.reason_code == "CAPABILITY_REQUIRED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capabilities,allowed",
    [
        ([], False),
        (["send.content_source.v1"], False),
        (["send.semantic_parts.v1"], True),
    ],
)
async def test_shared_driver_independently_rejects_event_without_semantic_capability(  # noqa: E501
    capabilities, allowed, monkeypatch
):
    from qwenpaw.channel_protocol.errors import RpcError
    from qwenpaw.channel_protocol.models import IdentityParams, SendParams
    from qwenpaw.channel_protocol.shared_worker import DriverContext
    import importlib
    from xiaoyi_native_support import HostBoundary, SOURCE

    monkeypatch.syspath_prepend(str(SOURCE))
    driver = importlib.import_module(
        "qwenpaw_channel_xiaoyi.driver"
    ).XiaoYiDriver()
    peer = HostBoundary()
    driver.bind(
        DriverContext(
            peer, IdentityParams("external", "instance", 1), capabilities
        )
    )
    params = SendParams.from_mapping(
        send_mapping("event", {"type": "text", "text": "x", "role": "message"})
    )
    if allowed:
        result = await driver._send(params, None)
        assert (
            result["state"] == "failed"
            and result["reason_code"] == "RESPONSE_HANDLE_UNKNOWN"
        )
    else:
        with pytest.raises(RpcError, match="capability"):
            await driver._send(params, None)
    assert peer.state == {} and peer.batches == []
