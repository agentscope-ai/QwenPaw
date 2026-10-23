"""
Neutral semantic-event contracts through real host proxy and shared worker.
"""
import json
import os

import pytest

from extension_sample import sample_source

pytest_plugins = ["extension_process_suite"]


def semantic_source(directory, key, *, capabilities=None):
    """Add transport observation to the test-only external sample Driver."""
    source = sample_source(directory, key, capabilities=capabilities)
    descriptor = source / "channel.json"
    value = json.loads(descriptor.read_text())
    value["capabilities"] = sorted(
        set(
            [
                *value["capabilities"],
                "send.content_source.v1",
                "send.semantic_parts.v1",
            ]
        )
    )
    descriptor.write_text(json.dumps(value))
    driver = source / key / "driver.py"
    body = driver.read_text()
    needle = '"content_parts": list(getattr(params, "content_parts", ())),'
    assert body.count(needle) == 1
    body = body.replace(
        needle,
        needle
        + (
            '\n                "content_source": '
            'getattr(getattr(params, "content_source", None), "value", None),'
        ),
    )
    driver.write_text(body)
    return source


@pytest.mark.asyncio
async def test_completed_reasoning_keeps_semantic_role_through_actual_proxy_worker(  # noqa: E501
    runtime,
):
    """
    Removing semantic conversion must expose plain text at real IPC effect.
    """
    from qwenpaw.schemas import (
        Message,
        MessageType,
        Role,
        RunStatus,
        TextContent,
    )

    rt = await runtime(source_factory=semantic_source)
    channel = rt.channel
    request = channel.build_agent_request_from_native(
        {
            "sender_id": "member",
            "session_id": "room-A",
            "content_parts": [{"type": "text", "text": "question"}],
            "meta": {},
        }
    )
    event = Message(
        object="message",
        type=MessageType.REASONING,
        role=Role.ASSISTANT,
        status=RunStatus.Completed,
        content=[TextContent(text="visible analysis\n⟦ internal headline ⟧")],
    )
    target = channel.to_handle_from_target(
        user_id="member", session_id="room-A"
    )
    await channel.on_event_message_completed(request, target, event, {})
    state = await rt.process.call("fixture.inspect", {})
    effects = [
        row for row in state["effects"] if row["operation"] == "message.create"
    ]
    assert len(effects) == 1
    assert (
        effects[0]["pid"] == rt.process.health_snapshot()["pid"] != os.getpid()
    )
    assert effects[0]["content_source"] == "event", effects
    assert effects[0]["content_parts"] == [
        {"type": "text", "role": "reasoning", "text": "visible analysis"},
    ]


def merge_semantic_source(directory, key, *, capabilities=None):
    source = semantic_source(directory, key, capabilities=capabilities)
    path = source / "channel.json"
    value = json.loads(path.read_text())
    value["capabilities"] = sorted(
        set(value["capabilities"]) | {"channel.text_merge.v1"}
    )
    value["config_schema"]["properties"]["route_policies"][
        "additionalProperties"
    ]["properties"]["text_merge_delay_ms"] = {"type": "integer", "minimum": 0}
    path.write_text(json.dumps(value))
    return source


@pytest.mark.asyncio
async def test_mixed_semantic_events_and_hidden_tool_media_keep_roles_through_one_real_worker(  # noqa: E501
    runtime,
):
    from qwenpaw.schemas import (
        DataContent,
        Message,
        RefusalContent,
        TextContent,
    )

    rt = await runtime(
        source_factory=merge_semantic_source,
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": False,
                "completion_reaction": False,
                "text_merge_delay_ms": 1,
            }
        },
    )
    channel = rt.channel
    request = channel.build_agent_request_from_native(
        {
            "sender_id": "member",
            "session_id": "room-A",
            "content_parts": [{"type": "text", "text": "question"}],
            "meta": {},
        }
    )
    target = channel.get_to_handle_from_request(request)
    mixed = Message(
        object="message",
        type="message",
        role="assistant",
        status="completed",
        content=[
            TextContent(text="before"),
            DataContent(
                data={
                    "blocks": [
                        {"type": "thinking", "thinking": "deep\n⟦ internal ⟧"}
                    ]
                }
            ),
            RefusalContent(refusal="raw refusal"),
            TextContent(text="after"),
        ],
    )
    await channel.on_event_message_completed(request, target, mixed, {})
    state = await rt.process.call("fixture.inspect", {})
    effects = [
        row for row in state["effects"] if row["operation"] == "message.create"
    ]
    assert len(effects) == 1 and effects[0]["content_source"] == "event"
    assert effects[0]["content_parts"] == [
        {"type": "text", "text": "before", "role": "message"},
        {"type": "text", "text": "deep", "role": "reasoning"},
        {"type": "text", "text": "raw refusal", "role": "refusal"},
        {"type": "text", "text": "after", "role": "message"},
    ]
    channel._display_config.show_tool_results = False
    tool = Message(
        object="message",
        type="plugin_call_output",
        role="tool",
        status="completed",
        content=[
            DataContent(
                data={
                    "name": "image_tool",
                    "output": [
                        {"type": "text", "text": "hidden"},
                        {
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": "https://example.com/tool.png",
                            },
                        },
                    ],
                }
            )
        ],
    )
    await channel.on_event_message_completed(request, target, tool, {})
    state = await rt.process.call("fixture.inspect", {})
    effects = [
        row for row in state["effects"] if row["operation"] == "message.create"
    ]
    assert len(effects) == 2
    assert effects[1]["content_source"] == "event"
    assert effects[1]["content_parts"] == [
        {
            "type": "image",
            "image_url": "https://example.com/tool.png",
            "role": "rendered",
        }
    ]
    assert all(
        row["pid"] == rt.process.health_snapshot()["pid"] != os.getpid()
        for row in effects
    )

    image = {"type": "image", "image_url": "https://example.com/explicit.png"}
    await channel.send_content_parts(target, [image], {})
    await channel.send_media(target, image, {})
    state = await rt.process.call("fixture.inspect", {})
    effects = [
        row for row in state["effects"] if row["operation"] == "message.create"
    ]
    assert len(effects) == 4
    assert effects[2]["content_source"] == "content_parts"
    # Generic IPC keeps native media only; XiaoYi platform adds its legacy
    # explicit-content-parts placeholder (covered by private pure control).
    assert effects[2]["content_parts"] == [image]
    assert effects[3]["content_source"] == "media" and effects[3][
        "content_parts"
    ] == [image]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file_fields", [{"file_id": "ref"}, {"filename": "name-only.pdf"}]
)
async def test_valid_runtime_ordinary_file_without_url_does_not_send_or_fail(
    runtime, file_fields
):
    from qwenpaw.schemas import FileContent, Message

    rt = await runtime(source_factory=semantic_source)
    request = rt.channel.build_agent_request_from_native(
        {
            "sender_id": "member",
            "session_id": "room-A",
            "content_parts": [{"type": "text", "text": "question"}],
            "meta": {},
        }
    )
    target = rt.channel.get_to_handle_from_request(request)
    event = Message(
        object="message",
        type="message",
        role="assistant",
        status="completed",
        content=[FileContent(**file_fields)],
    )
    assert event.content[0].type == "file"
    await rt.channel.on_event_message_completed(request, target, event, {})
    state = await rt.process.call("fixture.inspect", {})
    assert [
        row for row in state["effects"] if row["operation"] == "message.create"
    ] == []
