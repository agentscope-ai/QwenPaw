# -*- coding: utf-8 -*-
"""Structured display through real Runtime/workers, plus closed wire boundaries."""

import json

import pytest

from qwenpaw.app.channels.renderer import (
    ChannelDisplayConfig,
    MessageRenderer,
    RenderStyle,
)
from qwenpaw.app.channels.structured_content import project_structured_content
from qwenpaw.channel_protocol.errors import ProtocolValidationError
from qwenpaw.channel_protocol.models import SendParams
from qwenpaw.channel_protocol.structured_content import (
    validate_structured_parts,
)
from qwenpaw.plugins import SDKError
from qwenpaw.plugins.channel_workers import (
    ChannelContent,
    ChannelDefinition,
    ResponsePolicy,
)
from qwenpaw.plugins.testing import PluginTestHost
from qwenpaw.schemas import (
    DataContent,
    Message,
    MessageType,
    RefusalContent,
    RunStatus,
    TextContent,
)
from tests.channel_support.sdk import make_channel, workspace_store
from tests.channel_support.process import alive, eventually
from .sdk_author_fixture import make_plugin
from .test_sdk_channel_policy import MODEL
from .test_sdk_channel_worker import setup, open_response

DRIVER = """
import os
from dataclasses import asdict
from qwenpaw.plugins.channel_workers import (
    ChannelContent,
    ChannelDriver,
    ChannelSendResult,
    ResponsePolicy,
)
from qwenpaw.plugins.channels import ChannelMessage
from qwenpaw.plugins.messages import ContentBlock


class Driver(ChannelDriver):
    response_policy = ResponsePolicy(
        content_source="semantic", text_merge_delay_ms=0
    )

    async def start(self, ch):
        await ch.storage.awrite_json("pid.json", os.getpid())
        await ch.report_status("connected")
        await ch.receive(
            ChannelMessage(
                "alice",
                (ContentBlock(text="Use the tool then answer"),),
                session_id="room",
                message_id="one",
            )
        )

    async def send(self, ch, response):
        assert all(isinstance(b, ChannelContent) for b in response.content)
        sent = await ch.storage.aread_json("sent.json", [])
        sent.extend(asdict(b) for b in response.content)
        await ch.storage.awrite_json("sent.json", sent)
        return ChannelSendResult(str(len(sent)))

    async def finish_response(self, ch, target, outcome):
        await ch.storage.awrite_json("finished.json", outcome)
"""


def message(content, kind=MessageType.MESSAGE):
    return Message(
        type=kind,
        role="assistant",
        content=content,
        status=RunStatus.Completed,
    )


def tool_result(output, name="external"):
    return message(
        [
            DataContent(
                data={"call_id": "call-one", "name": name, "output": output},
            ),
        ],
        MessageType.FUNCTION_CALL_OUTPUT,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        "visible",
        "hidden",
        "preview",
        "truncated",
        "tool-error",
        "missing-capability",
    ],
)
async def test_runtime_content_policy_in_real_worker(tmp_path, scenario):
    source = tmp_path / "channel"
    key = "sdk-content"
    capabilities = ("channel.generic.v1", "channel.text_merge.v1")
    if scenario != "missing-capability":
        capabilities += ("send.structured_parts.v1",)
    definition = ChannelDefinition(
        key,
        {"en": "Content", "zh": "内容"},
        "driver:Driver",
        {"type": "object", "properties": {}},
        (),
        capabilities,
    )
    make_channel(
        source,
        DRIVER,
        definition,
        capabilities=["channels", "storage"],
    )
    model = MODEL.replace(
        "from qwenpaw.plugins.messages import ContentBlock",
        "from qwenpaw.plugins.messages import ContentBlock, Attachment",
    )
    model = model.replace(
        'blocks = (ContentBlock(text="part-" + str(count)),)',
        'blocks = (ContentBlock("thinking", text="private-reasoning"), ContentBlock(text="part-" + str(count)))',
    )
    model = model.replace(
        'return ToolResult.text("tool-result")',
        """return ToolResult((ContentBlock(text="before-image"),
                ContentBlock("image", attachment=Attachment("https://example.invalid/image.png", "image/png")),
                ContentBlock(text="after-image")), is_error=ctx.config.get("error", False))""",
    )
    provider_source = make_plugin(
        tmp_path,
        model,
        ["providers", "storage", "tools"],
    )
    root = tmp_path / "host"
    async with PluginTestHost(root, process_channels=(key,)) as host:
        if scenario == "missing-capability":
            with pytest.raises(SDKError, match="WORKER_START_FAILED"):
                await host.install(source)
            assert not list((root / "plugin-data" / key).glob("**/pid.json"))
            return
        assert (await host.install(source)).ok
        provider = await host.load(
            provider_source,
            config={"error": scenario == "tool-error"},
        )
        await host.configure_chat_model("policy-model", "model")
        if scenario == "preview":
            from qwenpaw.config import load_config, save_config

            config = load_config()
            config.show_tool_details = False
            save_config(config)
        settings = {}
        if scenario == "hidden":
            settings = {
                "show_tool_calls": False,
                "show_tool_results": False,
                "show_thinking": False,
            }
        elif scenario == "truncated":
            settings = {"tool_call_max_length": 1, "tool_result_max_length": 3}
        await host.start_channel(key, settings)
        storage = workspace_store(root, key, "test")
        await eventually((storage / "finished.json").exists, timeout=15)
        assert (
            json.loads((storage / "finished.json").read_text()) == "completed"
        )
        parts = json.loads((storage / "sent.json").read_text())
        assert provider.storage.read_json("calls.json") == 2
        assert provider.storage.read_json("tool.json") is True
        assert parts[-1]["type"] == "text" and parts[-1]["text"] == "part-2"
        if scenario == "hidden":
            assert not any(
                p["type"] in {"tool_call", "tool_result", "thinking"}
                for p in parts
            )
            assert "private-reasoning" not in json.dumps(parts)
            assert "before-image" not in json.dumps(parts)
            assert any(p["type"] == "image" for p in parts)
        else:
            call = next(p for p in parts if p["type"] == "tool_call")
            result = next(p for p in parts if p["type"] == "tool_result")
            assert call["id"] == result["id"] == "policy-call"
            assert call["name"] == result["name"] == "policy_echo"
            assert parts.index(call) < parts.index(result) < len(parts) - 1
            assert any(
                p["type"] == "thinking" and p["role"] == "reasoning"
                for p in parts
            )
            assert result["state"] == (
                "error" if scenario == "tool-error" else "success"
            )
            output = result["output"]
            assert (
                next(p for p in output if p["type"] == "image")["attachment"][
                    "mime_type"
                ]
                == "image/png"
            )
            if scenario in {"visible", "tool-error"}:
                assert [p["type"] for p in output] == ["text", "image", "text"]
                assert [output[0]["text"], output[2]["text"]] == [
                    "before-image",
                    "after-image",
                ]
                assert call["arguments"] == "{}"
            elif scenario == "preview":
                assert call["arguments"] == "..."
                assert [p["type"] for p in output] == ["text", "image"]
                assert output[0]["text"] == "..."
                assert "before-image" not in json.dumps(parts)
            else:
                assert call["arguments"] == "{..."
                assert [p["type"] for p in output] == ["text", "image"]
                assert output[0]["text"] == "bef..."
                assert "after-image" not in json.dumps(parts)
        pid = json.loads((storage / "pid.json").read_text())
        assert (await host.uninstall(key)).quiescent
        assert not alive(pid)


def test_hidden_internal_media_and_shared_truncation_budget():
    blocks = [
        {"type": "text", "text": "ab"},
        {
            "type": "image",
            "source": {"type": "url", "url": "https://example.test/a.png"},
        },
        {"type": "text", "text": "cdef"},
        {"type": "thinking", "thinking": "hidden-thought"},
    ]
    display = ChannelDisplayConfig(
        show_thinking=False,
        tool_result_max_length=3,
    )
    renderer = MessageRenderer(
        RenderStyle(
            display_config=display,
            internal_tools=frozenset({"view_image"}),
        ),
    )
    output = project_structured_content(renderer, tool_result(blocks))[0][
        "output"
    ]
    assert [p["type"] for p in output] == ["text", "image", "text"]
    assert [output[0]["text"], output[2]["text"]] == ["ab", "c..."]
    display.show_tool_results = False
    assert (
        project_structured_content(renderer, tool_result(blocks, "view_image"))
        == []
    )
    assert [
        p["type"]
        for p in project_structured_content(renderer, tool_result(blocks))
    ] == ["image"]


@pytest.mark.asyncio
async def test_refusal_reasoning_and_nested_media_reach_public_types(tmp_path):
    renderer = MessageRenderer()
    ordinary = message(
        [
            TextContent(text="before"),
            RefusalContent(refusal="declined"),
            TextContent(text="after"),
        ],
    )
    parts = project_structured_content(renderer, ordinary)
    parts += project_structured_content(
        renderer,
        message([TextContent(text="thought")], MessageType.REASONING),
    )
    blocks = [{"type": "text", "text": "left"}]
    for kind in ("audio", "video", "file"):
        blocks.append(
            {
                "type": kind,
                "source": {
                    "type": "url",
                    "url": "https://example.test/" + kind,
                },
            },
        )
    blocks.append({"type": "text", "text": "right"})
    parts += project_structured_content(renderer, tool_result(blocks))
    adapter, peer, identity = await setup(
        tmp_path,
        capabilities=("channel.generic.v1", "send.structured_parts.v1"),
    )
    try:
        route = await open_response(peer, identity)
        params = SendParams.from_mapping(
            {
                **identity.to_mapping(),
                "delivery_id": "one",
                "to_handle": route,
                "operation": "message.create",
                "content_source": "structured",
                "content_parts": parts,
            },
        )
        await adapter._send(params, None)
        received = adapter.driver.sent[-1].content
        assert all(isinstance(p, ChannelContent) for p in received)
        assert [(p.type, p.text, p.role) for p in received[:4]] == [
            ("text", "before", "message"),
            ("text", "declined", "refusal"),
            ("text", "after", "message"),
            ("thinking", "thought", "reasoning"),
        ]
        assert [p.type for p in received[-1].output] == [
            "text",
            "audio",
            "video",
            "file",
            "text",
        ]
    finally:
        await adapter.stop()


@pytest.mark.parametrize(
    "parts",
    [
        [
            {
                "type": "tool_call",
                "id": "x",
                "name": "t",
                "arguments": {},
                "hidden": True,
            },
        ],
        [
            {
                "type": "tool_result",
                "id": "x",
                "name": "t",
                "output": [
                    {
                        "type": "tool_call",
                        "id": "y",
                        "name": "t",
                        "arguments": "{}",
                    },
                ],
            },
        ],
        [
            {
                "type": "image",
                "image_url": "https://example.test/a",
                "role": "refusal",
            },
        ],
        [{"type": "text", "text": "x", "role": "secret"}],
        [{"type": "text", "text": "x"}] * 4097,
    ],
)
def test_structured_wire_rejects_unbounded_or_unsupported_content(parts):
    with pytest.raises(ProtocolValidationError):
        validate_structured_parts(parts)


def test_content_source_is_closed_and_versioned():
    with pytest.raises(ValueError):
        ResponsePolicy(content_source="raw")
    with pytest.raises(ProtocolValidationError):
        ChannelDefinition(
            "example",
            {"en": "Example", "zh": "例子"},
            "driver:Driver",
            {"type": "object", "properties": {}},
            (),
            ("channel.generic.v1", "send.structured_parts.v2"),
        )


@pytest.mark.asyncio
async def test_nested_media_pins_only_own_workspace_and_releases_on_ack(
    tmp_path,
):
    from qwenpaw.config.context import current_workspace_dir
    from qwenpaw.utils.outbound_media import (
        stage_outbound_file,
        update_outbound_media,
    )

    original = tmp_path / "picture.png"
    original.write_bytes(b"independent media snapshot")
    first, second = tmp_path / "first", tmp_path / "second"
    snapshots = []
    for workspace in (first, second):
        token = current_workspace_dir.set(workspace)
        try:
            snapshots.append(await stage_outbound_file(original))
        finally:
            current_workspace_dir.reset(token)
    parts = [
        {
            "type": "tool_result",
            "id": "call",
            "name": "tool",
            "output": [
                {"type": "image", "image_url": str(path)} for path in snapshots
            ],
        },
    ]

    def state(path):
        return json.loads((path.parent.parent / ".state.json").read_text())

    await update_outbound_media(first, parts, "delivery", pending=True)
    assert state(snapshots[0])["pending"] == ["delivery"]
    assert state(snapshots[1])["pending"] == []
    assert snapshots[0].read_bytes() == original.read_bytes()
    await update_outbound_media(first, parts, "delivery", pending=False)
    assert state(snapshots[0])["pending"] == []
    assert state(snapshots[1])["pending"] == []


def test_embedded_tool_data_keeps_surrounding_text_and_failure_state():
    renderer = MessageRenderer()
    value = message(
        [
            TextContent(text="first"),
            DataContent(
                data={
                    "call_id": "failed-call",
                    "name": "tool",
                    "output": "failure",
                    "state": "error",
                },
            ),
            RefusalContent(refusal="declined"),
            TextContent(text="last"),
        ],
    )
    parts = project_structured_content(renderer, value)
    assert [p["type"] for p in parts] == [
        "text",
        "tool_result",
        "text",
        "text",
    ]
    assert parts[1] == {
        "type": "tool_result",
        "id": "failed-call",
        "name": "tool",
        "output": "failure",
        "state": "error",
    }
    assert parts[2]["role"] == "refusal"
    renderer.style.display_config.show_tool_results = False
    assert [
        p["text"] for p in project_structured_content(renderer, value)
    ] == [
        "first",
        "declined",
        "last",
    ]


@pytest.mark.asyncio
async def test_structured_content_requires_declared_worker_capability(
    tmp_path,
):
    from qwenpaw.channel_protocol.errors import RpcError

    adapter, peer, identity = await setup(tmp_path)
    try:
        route = await open_response(peer, identity)
        params = SendParams.from_mapping(
            {
                **identity.to_mapping(),
                "delivery_id": "one",
                "to_handle": route,
                "operation": "message.create",
                "content_source": "structured",
                "content_parts": [
                    {"type": "text", "text": "declined", "role": "refusal"},
                ],
            },
        )
        with pytest.raises(RpcError, match="capability"):
            await adapter._send(params, None)
        assert adapter.driver.sent == []
    finally:
        await adapter.stop()


def test_ordinary_projection_rejects_too_many_blocks_before_delivery():
    value = message([TextContent(text="one")] * 4097)
    with pytest.raises(ProtocolValidationError, match="Too many"):
        project_structured_content(MessageRenderer(), value)
