"""
Ordinary event failure must not terminate the actual Agent event consumer.
"""

import json
import os

import pytest

from extension_sample import sample_source

from real_host_runtime import bind_real_runtime

pytest_plugins = ["extension_process_suite"]


def failure_source(directory, key, *, capabilities=None):
    """Add a deterministic SDK refusal to the copied external test artifact."""
    source = sample_source(directory, key, capabilities=capabilities)
    descriptor = source / "channel.json"
    value = json.loads(descriptor.read_text())
    value["capabilities"] = sorted(
        set(value["capabilities"])
        | {
            "send.content_source.v1",
            "send.semantic_parts.v1",
        }
    )
    value["config_schema"]["properties"]["route_policies"][
        "additionalProperties"
    ]["properties"]["continue_on_delivery_error"] = {"type": "boolean"}
    descriptor.write_text(json.dumps(value))
    path = source / key / "driver.py"
    body = path.read_text()
    needle = '        if self.fault == "unknown":'
    assert body.count(needle) == 1
    body = body.replace(
        needle,
        """        if self.fault == "failed" or (
            self.fault == "notice-failed" and any(
                part.get("text", "").startswith("Model switched")
                for part in getattr(params, "content_parts", ())
            )
        ):
            raise DeliveryError(
                "PLATFORM_SEND_REFUSED", side_effect_possible=False
            )
"""
        + needle,
    )
    path.write_text(body)
    return source


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["failed", "unknown"])
async def test_actual_agent_response_is_consumed_after_ordinary_event_send_failure(  # noqa: E501
    runtime,
    monkeypatch,
    fault,
):
    rt = await runtime(
        source_factory=failure_source,
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": False,
                "completion_reaction": False,
                "continue_on_delivery_error": True,
            }
        },
    )
    host = await bind_real_runtime(rt, monkeypatch)
    await rt.process.call("fixture.fault", {"mode": fault})
    payload = {
        "sender_id": "member",
        "session_id": "room-A",
        "content_parts": [{"type": "text", "text": "real agent question"}],
        "meta": {},
    }
    streamed, errors = [], []
    try:
        async for row in rt.channel._stream_with_tracker(payload):
            streamed.append(json.loads(row.removeprefix("data: ")))
    except (
        Exception
    ) as exc:  # preserve diagnostic then prove actual consumption
        errors.append(repr(exc))
    assert host.calls and host.calls[0]["pid"] == os.getpid()
    assert host.builds and host.builds[0]["agent"] == "QwenPawAgent"
    state = await rt.process.call("fixture.inspect", {})
    attempts = [
        row for row in state["effects"] if row["operation"] == "message.create"
    ]
    assert (
        attempts
        and attempts[0]["pid"]
        == rt.process.health_snapshot()["pid"]
        != os.getpid()
    )
    assert any(
        row.get("object") == "message" and row.get("status") == "completed"
        for row in host.events
    )
    assert any(
        row.get("object") == "response" and row.get("status") == "completed"
        for row in host.events
    ), (host.events, errors)
    assert any(
        row.get("object") == "response" and row.get("status") == "completed"
        for row in streamed
    ), (streamed, errors)
    assert errors == []
    # Unknown delivery remains one actual attempt; no fallback/error
    # blind replay.
    if fault == "unknown":
        assert len(attempts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault,state", [("failed", "failed"), ("unknown", "unknown")]
)
async def test_api_send_stays_strict_and_unknown_delivery_is_not_replayed(
    runtime, fault, state
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await runtime(
        source_factory=failure_source,
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": False,
                "completion_reaction": False,
                "continue_on_delivery_error": True,
            }
        },
    )
    await rt.process.call("fixture.fault", {"mode": fault})
    target = rt.channel.to_handle_from_target(
        user_id="member", session_id="room-A"
    )
    meta = {}
    with pytest.raises(ChannelDeliveryError) as caught:
        await rt.channel.send(target, "strict api", meta)
    assert caught.value.state == state
    assert caught.value.side_effect_possible is (fault == "unknown")
    before = await rt.process.call("fixture.inspect", {})
    assert (
        len(
            [
                row
                for row in before["effects"]
                if row["operation"] == "message.create"
            ]
        )
        == 1
    )
    if fault == "unknown":
        with pytest.raises(ChannelDeliveryError) as repeated:
            await rt.channel.send(target, "strict api", meta)
        assert repeated.value.state == "unknown"
        with pytest.raises(ChannelDeliveryError):
            await rt.channel.send(target, "different body", meta)
        after = await rt.process.call("fixture.inspect", {})
        assert after["effects"] == before["effects"]


@pytest.mark.asyncio
async def test_default_policy_completed_event_remains_strict(runtime):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    from qwenpaw.schemas import Message, TextContent

    rt = await runtime(source_factory=failure_source)
    await rt.process.call("fixture.fault", {"mode": "failed"})
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
        content=[TextContent(text="answer")],
    )
    with pytest.raises(ChannelDeliveryError) as caught:
        await rt.channel.on_event_message_completed(request, target, event, {})
    assert (
        caught.value.state == "failed"
        and not caught.value.side_effect_possible
    )


def test_delivery_error_policy_defaults_false_and_true_roundtrips():
    from qwenpaw.channel_protocol.response_policy import ResponsePolicy

    base = {"streaming": False, "prepare": False, "completion_reaction": False}
    assert (
        ResponsePolicy.from_mapping(base).continue_on_delivery_error is False
    )
    assert ResponsePolicy().to_mapping() == base
    assert ResponsePolicy(continue_on_delivery_error=True).to_mapping() == {
        **base,
        "continue_on_delivery_error": True,
    }
    assert (
        ResponsePolicy.from_mapping(
            {**base, "continue_on_delivery_error": True}
        ).continue_on_delivery_error
        is True
    )


@pytest.mark.parametrize("invalid", [None, 0, 1, "true", [], {}])
def test_delivery_error_policy_rejects_non_boolean(invalid):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.channel_protocol.response_policy import ResponsePolicy

    with pytest.raises(ProtocolValidationError):
        ResponsePolicy(continue_on_delivery_error=invalid)
    with pytest.raises(ProtocolValidationError):
        ResponsePolicy.from_mapping(
            {
                "streaming": False,
                "prepare": False,
                "completion_reaction": False,
                "continue_on_delivery_error": invalid,
            }
        )


def test_formal_xiaoyi_driver_explicitly_requests_tolerant_event_policy(
    monkeypatch,
):
    from xiaoyi_native_support import SOURCE
    import importlib

    monkeypatch.syspath_prepend(str(SOURCE))
    driver = importlib.import_module(
        "qwenpaw_channel_xiaoyi.driver"
    ).XiaoYiDriver()
    policy = driver.response_policy("native-response")
    assert policy.continue_on_delivery_error is True
    assert policy.to_mapping()["continue_on_delivery_error"] is True
    assert (
        not policy.streaming
        and not policy.prepare
        and not policy.completion_reaction
    )
    assert policy.send_format.direct_prefix is False
    assert policy.send_format.parts_configured_prefix is False
    assert policy.send_format.parts_metadata_prefix is True


@pytest.mark.asyncio
async def test_api_parts_and_media_remain_strict_with_tolerant_ordinary_policy(
    runtime,
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await runtime(
        source_factory=failure_source,
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": False,
                "completion_reaction": False,
                "continue_on_delivery_error": True,
            }
        },
    )
    await rt.process.call("fixture.fault", {"mode": "failed"})
    target = rt.channel.to_handle_from_target(
        user_id="member", session_id="room-A"
    )
    image = {"type": "image", "image_url": "https://example.com/a.png"}
    for method, argument in (
        (rt.channel.send_content_parts, [image]),
        (rt.channel.send_media, image),
    ):
        with pytest.raises(ChannelDeliveryError) as caught:
            await method(target, argument, {})
        assert (
            caught.value.state == "failed"
            and not caught.value.side_effect_possible
        )
    state = await rt.process.call("fixture.inspect", {})
    assert (
        len(
            [
                row
                for row in state["effects"]
                if row["operation"] == "message.create"
            ]
        )
        == 2
    )


@pytest.mark.asyncio
async def test_tolerant_policy_does_not_swallow_response_describe_rpc_failure(
    runtime,
):
    from qwenpaw.channel_protocol.errors import RpcError
    from qwenpaw.schemas import Message, TextContent

    rt = await runtime(
        source_factory=failure_source,
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": False,
                "completion_reaction": False,
                "continue_on_delivery_error": True,
            }
        },
    )
    await rt.process.call("fixture.fault", {"mode": "describe-error"})
    request = rt.channel.build_agent_request_from_native(
        {
            "sender_id": "member",
            "session_id": "room-A",
            "content_parts": [{"type": "text", "text": "question"}],
            "meta": {},
        }
    )
    target = rt.channel.get_to_handle_from_request(request)
    with pytest.raises(RpcError) as caught:
        await rt.channel.on_event_message_completed(
            request,
            target,
            Message(
                object="message",
                type="message",
                role="assistant",
                status="completed",
                content=[TextContent(text="answer")],
            ),
            {},
        )
    assert caught.value.data["reason_code"] == "DESCRIBE_UNAVAILABLE"
    state = await rt.process.call("fixture.inspect", {})
    assert state["effects"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["failed", "unknown", "notice-failed"])
async def test_actual_agent_fallback_notice_after_failed_event_does_not_end_consumption(  # noqa: E501
    runtime, monkeypatch, fault
):
    from qwenpaw.agents.react_agent import QwenPawAgent
    from qwenpaw.app.channels.base import BaseChannel

    rt = await runtime(
        source_factory=failure_source,
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": False,
                "completion_reaction": False,
                "continue_on_delivery_error": True,
            }
        },
    )
    host = await bind_real_runtime(rt, monkeypatch)
    await rt.process.call("fixture.fault", {"mode": fault})
    actual = rt.channel._process
    metadata_seen = []
    fallback = {
        "type": "model_fallback",
        "from_provider_id": "provider-A",
        "from_model_id": "model-A",
        "to_provider_id": "provider-B",
        "to_model_id": "model-B",
        "reason_kind": "timeout",
    }

    async def actual_agent_with_fallback_metadata(request):
        async for event in actual(request):
            if (
                getattr(event, "object", None) == "message"
                and getattr(event, "status", None) == "completed"
            ):
                # Same production metadata attachment used
                # after a model fallback;
                # the Agent/runtime/model execution itself remains real.
                QwenPawAgent._attach_fallback_notices(
                    event, {"events": [fallback]}
                )
                metadata_seen.extend(BaseChannel._model_fallback_events(event))
            yield event

    monkeypatch.setattr(
        rt.channel, "_process", actual_agent_with_fallback_metadata
    )
    payload = {
        "sender_id": "member",
        "session_id": "room-A",
        "content_parts": [
            {"type": "text", "text": "actual fallback question"}
        ],
        "meta": {},
    }
    streamed, errors = [], []
    try:
        async for row in rt.channel._stream_with_tracker(payload):
            streamed.append(json.loads(row.removeprefix("data: ")))
    except Exception as exc:
        errors.append(repr(exc))
    assert host.calls and host.calls[0]["pid"] == os.getpid()
    assert host.builds and host.builds[0]["agent"] == "QwenPawAgent"
    assert metadata_seen == [
        {key: value for key, value in fallback.items() if key != "type"}
    ]
    state = await rt.process.call("fixture.inspect", {})
    attempts = [
        row for row in state["effects"] if row["operation"] == "message.create"
    ]
    assert attempts and all(
        row["pid"] == rt.process.health_snapshot()["pid"] != os.getpid()
        for row in attempts
    )
    assert (
        len(
            [
                row
                for row in attempts
                if any(
                    part.get("text") == "actual agent answer"
                    for part in row["content_parts"]
                )
            ]
        )
        == 1
    )
    if fault == "unknown":
        assert len(attempts) == 1
    assert any(
        row.get("object") == "response" and row.get("status") == "completed"
        for row in host.events
    ), (host.events, errors)
    assert any(
        row.get("object") == "response" and row.get("status") == "completed"
        for row in streamed
    ), (streamed, errors)
    assert errors == []


@pytest.mark.asyncio
async def test_disable_after_real_policy_read_stays_strict_lifecycle_error(
    runtime, monkeypatch
):
    import asyncio
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    from qwenpaw.schemas import Message, TextContent

    rt = await runtime(
        source_factory=failure_source,
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": False,
                "completion_reaction": False,
                "continue_on_delivery_error": True,
            }
        },
    )
    actual = rt.channel._response_policy
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause_after_actual_policy(target, meta):
        policy = await actual(target, meta)
        assert policy.continue_on_delivery_error is True
        entered.set()
        await release.wait()
        return policy

    monkeypatch.setattr(
        rt.channel, "_response_policy", pause_after_actual_policy
    )
    request = rt.channel.build_agent_request_from_native(
        {
            "sender_id": "member",
            "session_id": "room-A",
            "content_parts": [{"type": "text", "text": "question"}],
            "meta": {},
        }
    )
    target = rt.channel.get_to_handle_from_request(request)
    meta = {}
    sending = asyncio.create_task(
        rt.channel.on_event_message_completed(
            request,
            target,
            Message(
                object="message",
                type="message",
                role="assistant",
                status="completed",
                content=[TextContent(text="answer")],
            ),
            meta,
        )
    )
    try:
        async with asyncio.timeout(3):
            await entered.wait()
        assert rt.channel.enabled and not sending.done()
        # Change the real proxy state after the real child policy receipt.
        # Its actual _require_enabled guard must raise before any child send.
        rt.channel.enabled = False
        release.set()
        with pytest.raises(ChannelDeliveryError) as caught:
            await sending
        assert caught.value.reason_code == "CHANNEL_DISABLED"
        assert "_continued_event_delivery_error" not in meta
        state = await rt.process.call("fixture.inspect", {})
        assert state["effects"] == []
    finally:
        release.set()
        await asyncio.gather(sending, return_exceptions=True)


@pytest.mark.asyncio
async def test_fallback_notice_outside_completed_event_scope_remains_strict(
    runtime,
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    from qwenpaw.schemas import Message, TextContent

    rt = await runtime(
        source_factory=failure_source,
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": False,
                "completion_reaction": False,
                "continue_on_delivery_error": True,
            }
        },
    )
    await rt.process.call("fixture.fault", {"mode": "failed"})
    target = rt.channel.to_handle_from_target(
        user_id="member", session_id="room-A"
    )
    event = Message(
        object="message",
        type="message",
        role="assistant",
        status="completed",
        content=[TextContent(text="answer")],
        metadata={
            "qwenpaw_model_fallbacks": [
                {
                    "type": "model_fallback",
                    "from_provider_id": "A",
                    "from_model_id": "a",
                    "to_provider_id": "B",
                    "to_model_id": "b",
                    "reason_kind": "timeout",
                }
            ]
        },
    )
    assert rt.channel._model_fallback_events(event)
    with pytest.raises(ChannelDeliveryError) as caught:
        await rt.channel._send_model_fallback_notice(target, event, {})
    assert (
        caught.value.state == "failed"
        and caught.value.reason_code == "PLATFORM_SEND_REFUSED"
    )
