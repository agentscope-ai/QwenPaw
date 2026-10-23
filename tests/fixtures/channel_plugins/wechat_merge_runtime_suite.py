"""Opt-in text merge through real Loader/proxy/child/journal contracts."""

import asyncio
from copy import deepcopy

import pytest

from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
from qwenpaw.channel_protocol.errors import ProtocolValidationError, RpcError
from qwenpaw.channel_protocol.models import APPROVAL_RESOLUTION_CAPABILITY

from extension_process_suite import (
    durable_snapshot,
    inspect,
    runtime,
)
from wechat_merge_support import merge_runtime, route, sends


@pytest.mark.asyncio
async def test_old_owner_policy_and_unknown_retry_keep_original_wire(runtime):
    rt = await runtime("unchanged_third_party_owner")
    target, meta = await route(rt)
    policy = await rt.channel._response_policy(target, meta)
    assert policy.to_mapping() == {
        "streaming": False,
        "prepare": False,
        "completion_reaction": False,
    }
    await rt.process.call("fixture.fault", {"mode": "unknown"})
    with pytest.raises(ChannelDeliveryError) as first:
        await rt.channel.send(target, " old exact body ", meta)
    assert first.value.state == "unknown"
    pending = deepcopy(meta["_pending_delivery"])
    with pytest.raises(ChannelDeliveryError):
        await rt.channel.send(target, " old exact body ", meta)
    assert meta["_pending_delivery"] == pending
    rows = await sends(rt)
    assert len(rows) == 1
    assert rows[0]["content_parts"] == [
        {"type": "text", "text": " old exact body "}
    ]
    assert rows[0]["delivery_id"] == pending["delivery_id"]
    assert rt.ws.requests == []  # No substitute/default Agent was exercised.


@pytest.mark.asyncio
async def test_opted_in_text_is_local_until_one_actual_acknowledged_flush(
    runtime,
):
    rt = await merge_runtime(runtime)
    target, meta = await route(rt)
    assert await rt.channel.send(target, "first", meta) is None
    assert await rt.channel.send(target, "second", meta) is None
    assert await sends(rt) == []
    assert "_last_delivery_id" not in meta
    assert "_pending_delivery" not in meta
    await rt.channel._flush_response_text(meta["response_handle"])
    rows = await sends(rt)
    assert len(rows) == 1
    assert rows[0]["content_parts"] == [
        {"type": "text", "text": "first\nsecond"}
    ]
    assert rows[0]["delivery_id"] == meta["_last_delivery_id"]
    serialized = str(durable_snapshot(rt, meta["response_handle"]))
    assert rows[0]["delivery_id"] in serialized
    assert "acknowledged" in serialized
    assert rt.ws.requests == []


@pytest.mark.asyncio
async def test_capability_is_required_before_buffering_or_platform_effect(
    runtime,
):
    rt = await merge_runtime(runtime, opted_in=False)
    target, meta = await route(rt)
    with pytest.raises((ProtocolValidationError, RpcError)) as raised:
        await rt.channel.send(target, "must not dispatch", meta)
    error = raised.value
    reason = getattr(error, "reason_code", None)
    if isinstance(getattr(error, "data", None), dict):
        reason = error.data.get("reason_code", reason)
    assert reason == "CAPABILITY_REQUIRED"
    assert await sends(rt) == []


@pytest.mark.asyncio
async def test_same_recipient_responses_keep_separate_buffers(runtime):
    rt = await merge_runtime(runtime)
    target_a, a = await route(rt)
    target_b, b = await route(rt)
    await rt.channel.send(target_a, "A-one", a)
    await rt.channel.send(target_b, "B-one", b)
    await rt.channel.send(target_a, "A-two", a)
    assert await sends(rt) == []
    await rt.channel._flush_response_text(b["response_handle"])
    await rt.channel._flush_response_text(a["response_handle"])
    assert [row["content_parts"] for row in await sends(rt)] == [
        [{"type": "text", "text": "B-one"}],
        [{"type": "text", "text": "A-one\nA-two"}],
    ]


@pytest.mark.asyncio
async def test_media_flushes_pending_text_before_immediate_media(runtime):
    rt = await merge_runtime(runtime)
    target, meta = await route(rt)
    await rt.channel.send(target, "before image", meta)
    assert await sends(rt) == []
    await rt.channel.send_media(
        target,
        {"type": "image", "image_url": "https://asset.test/a.png"},
        meta,
    )
    assert [row["content_parts"] for row in await sends(rt)] == [
        [{"type": "text", "text": "before image"}],
        [{"type": "image", "image_url": "https://asset.test/a.png"}],
    ]


@pytest.mark.asyncio
async def test_proactive_scope_flushes_before_send_returns(runtime):
    rt = await merge_runtime(runtime)
    target = rt.channel.to_handle_from_target(
        user_id="member", session_id="room-A"
    )
    await rt.channel.send(target, "proactive exact")
    assert [r["content_parts"] for r in await sends(rt)] == [
        [{"type": "text", "text": "proactive exact"}]
    ]
    assert (await inspect(rt))["finish_calls"][-1]["outcome"] == "completed"


@pytest.mark.asyncio
async def test_unknown_flush_keeps_batch_id_and_never_replays_or_sends_media(
    runtime,
):
    rt = await merge_runtime(runtime)
    target, meta = await route(rt)
    await rt.channel.send(target, "uncertain batch", meta)
    await rt.process.call("fixture.fault", {"mode": "unknown"})
    with pytest.raises(ChannelDeliveryError) as raised:
        await rt.channel._flush_response_text(meta["response_handle"])
    assert raised.value.side_effect_possible
    pending = deepcopy(meta["_pending_delivery"])
    with pytest.raises(ChannelDeliveryError):
        await rt.channel._flush_response_text(meta["response_handle"])
    with pytest.raises(ChannelDeliveryError):
        await rt.channel.send_media(
            target,
            {"type": "image", "image_url": "https://asset.test/a.png"},
            meta,
        )
    assert meta["_pending_delivery"] == pending
    rows = await sends(rt)
    assert len(rows) == 1
    assert rows[0]["delivery_id"] == pending["delivery_id"]
    assert rows[0]["content_parts"] == [
        {"type": "text", "text": "uncertain batch"}
    ]
    with pytest.raises(ChannelDeliveryError):
        await rt.channel._on_process_completed(None, target, meta)
    with pytest.raises(ChannelDeliveryError):
        await rt.channel._finish_route(meta, "failed")
    assert meta["response_handle"] in rt.channel._text_merge
    assert meta["_pending_delivery"] == pending


@pytest.mark.asyncio
async def test_aggregate_budget_counts_utf8_across_responses_without_early_flush(
    runtime,
):
    rt = await merge_runtime(runtime)
    ta, a = await route(rt)
    tb, b = await route(rt, "room-B")
    text = "界" * 100000  # Each block is 300000 UTF-8 bytes, not 100000 bytes.
    await rt.channel.send(ta, text, a)
    await rt.channel.send(tb, text, b)
    with pytest.raises(ValueError, match="TEXT_MERGE_CAPACITY"):
        await rt.channel.send(ta, text, a)
    assert await sends(rt) == []
    with pytest.raises(ValueError, match="TEXT_MERGE_CAPACITY"):
        await rt.channel._finish_route(a, "completed")
    await rt.channel._flush_response_text(b["response_handle"])
    assert [row["content_parts"] for row in await sends(rt)] == [
        [{"type": "text", "text": text}]
    ]
    await rt.channel._cancel_response_text(a["response_handle"])


@pytest.mark.asyncio
async def test_adjacent_timer_flush_error_is_visible_to_next_send_and_finish(
    runtime,
):
    rt = await merge_runtime(runtime, delay=20)
    target, meta = await route(rt)
    await rt.process.call("fixture.fault", {"mode": "unknown"})
    await rt.channel.send(target, "timed batch", meta)
    async with asyncio.timeout(3):
        while not await sends(rt):
            await asyncio.sleep(0.01)
    with pytest.raises(ChannelDeliveryError):
        await rt.channel.send(target, "must not replace unknown", meta)
    with pytest.raises(ChannelDeliveryError):
        await rt.channel._finish_route(meta, "completed")
    assert len(await sends(rt)) == 1


@pytest.mark.asyncio
async def test_cancel_discards_unattempted_text_and_settles_its_timer(runtime):
    rt = await merge_runtime(runtime, delay=20)
    target, meta = await route(rt)
    await rt.channel.send(target, "cancel before attempt", meta)
    assert await sends(rt) == []
    await rt.channel._cancel_response_text(meta["response_handle"])
    await asyncio.sleep(0.06)
    assert await sends(rt) == []
    assert "_last_delivery_id" not in meta
    assert "_pending_delivery" not in meta
    await rt.channel._finish_route(meta, "cancelled")
    assert (await inspect(rt))["finish_calls"][-1]["outcome"] == "cancelled"


@pytest.mark.asyncio
async def test_stream_operation_retains_immediate_semantics(runtime):
    rt = await merge_runtime(runtime)
    target, meta = await route(rt)
    delivery = await rt.channel._send_operation(
        target,
        meta,
        "stream.start",
        stream_type="message",
        sequence=0,
        accumulated_text="stream exact",
    )
    assert delivery
    effects = (await inspect(rt))["effects"]
    assert [(row["operation"], row["delivery_id"]) for row in effects] == [
        ("stream.start", delivery)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "structured",
    [
        {
            "approval": {
                "request_id": "request-A",
                "tool_name": "shell",
                "severity": "medium",
            }
        },
        {
            "approval_resolution": {
                "request_id": "request-A",
                "outcome": "approved",
                "actor_user_id": "actor-A",
                "tool_name": "shell",
            }
        },
    ],
)
async def test_structured_approval_text_keeps_immediate_send_semantics(
    runtime, structured
):
    rt = await merge_runtime(
        runtime, extra_capabilities=[APPROVAL_RESOLUTION_CAPABILITY]
    )
    target, meta = await route(rt)
    delivery = await rt.channel._send_operation(
        target,
        meta,
        "message.create",
        **structured,
        content_parts=[{"type": "text", "text": "structured exact"}],
    )
    rows = await sends(rt)
    assert delivery and len(rows) == 1
    assert rows[0]["delivery_id"] == delivery
    assert rows[0]["content_parts"] == [
        {"type": "text", "text": "structured exact"}
    ]


@pytest.mark.asyncio
async def test_actual_agent_completion_callback_observes_flushed_platform_effect(
    runtime,
    monkeypatch,
):
    from extension_process_suite import emit, eventually
    from real_host_runtime import bind_real_runtime

    rt = await merge_runtime(runtime)
    host = await bind_real_runtime(rt, monkeypatch, reply="real merged answer")
    observed = []

    async def on_reply_sent(*args):
        observed.append(await sends(rt))

    rt.channel._on_reply_sent = on_reply_sent
    ack = await emit(rt, text="real merge input")
    assert ack["accepted_event_ids"] == ["event-one"]
    await eventually(lambda: bool(observed))
    assert observed[0][0]["content_parts"] == [
        {"type": "text", "text": "real merged answer"}
    ]
    assert len(observed[0]) == 1
    assert host.calls and host.builds


@pytest.mark.asyncio
async def test_smaller_actual_transport_frame_spills_complete_batch_once(
    runtime, monkeypatch
):
    from dataclasses import replace

    rt = await merge_runtime(runtime)
    target, meta = await route(rt)
    first, second = "甲" * 600, "乙" * 600
    await rt.channel.send(target, first, meta)
    await rt.channel.send(target, second, meta)
    assert await sends(rt) == []
    transport = rt.process._peer._transport
    original = transport._limits
    monkeypatch.setattr(
        transport, "_limits", replace(original, max_frame_bytes=1024)
    )
    staged = []
    stage = transport._payloads.stage

    async def observe_stage(message, **kwargs):
        reference, token = await stage(message, **kwargs)
        if token is not None:
            staged.append((message, reference, token))
        return reference, token

    monkeypatch.setattr(transport._payloads, "stage", observe_stage)
    await rt.channel._flush_response_text(meta["response_handle"])
    rows = await sends(rt)
    assert len(rows) == 1
    assert rows[0]["content_parts"] == [
        {"type": "text", "text": first + "\n" + second}
    ]
    assert rows[0]["delivery_id"] == meta["_last_delivery_id"]
    assert len(staged) == 1
    message, reference, token = staged[0]
    assert len(message.encode()) > 1024 >= len(reference.encode())
    assert token and "$qwenpaw_payload" in reference
    await rt.channel._flush_response_text(meta["response_handle"])
    await rt.channel._finish_route(meta, "completed")
    assert await sends(rt) == rows


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["logical-limit", "replaced-spill-directory"]
)
async def test_smaller_actual_transport_rejects_unsafe_spill_before_effect(
    runtime, monkeypatch, failure
):
    from dataclasses import replace
    from qwenpaw.plugins.execution.errors import (
        FrameLimitError,
        FrameProtocolError,
    )

    rt = await merge_runtime(runtime)
    target, meta = await route(rt)
    await rt.channel.send(target, "a" * 600, meta)
    await rt.channel.send(target, "b" * 600, meta)
    transport = rt.process._peer._transport
    monkeypatch.setattr(
        transport, "_limits", replace(transport._limits, max_frame_bytes=1024)
    )
    payloads = transport._payloads
    original_limits = payloads.limits
    directory = payloads.root / "h2w"
    saved = payloads.root / "original-h2w"
    if failure == "logical-limit":
        monkeypatch.setattr(
            payloads,
            "limits",
            replace(original_limits, max_message_bytes=1024),
        )
        expected = FrameLimitError
    else:
        directory.rename(saved)
        directory.mkdir()
        expected = FrameProtocolError
    try:
        with pytest.raises(expected):
            await rt.channel._flush_response_text(meta["response_handle"])
        assert await sends(rt) == []
        assert "_last_delivery_id" not in meta
        with pytest.raises(expected):
            await rt.channel._finish_route(meta, "completed")
        assert await sends(rt) == []
        assert "_last_delivery_id" not in meta
    finally:
        if saved.exists():
            directory.rmdir()
            saved.rename(directory)
        monkeypatch.setattr(payloads, "limits", original_limits)
    assert await sends(rt) == []
    await rt.channel._cancel_response_text(meta["response_handle"])
    assert await sends(rt) == []


@pytest.mark.asyncio
async def test_stop_settles_timer_and_old_generation_cannot_reach_new_child(
    runtime,
):
    import psutil

    rt = await merge_runtime(runtime, delay=200)
    target, meta = await route(rt)
    old = rt.channel
    old_pid = rt.process.health_snapshot()["pid"]
    await old.send(target, "must die with old generation", meta)
    state = old._text_merge[meta["response_handle"]]
    assert await sends(rt) == []
    await rt.loader.lifecycle.set_enabled(rt.key, False)
    assert old.last_stop_result.exited
    assert not psutil.pid_exists(old_pid)
    assert old._text_merge == {} and old._text_merge_bytes == 0
    with pytest.raises(ValueError, match="STALE_GENERATION"):
        old._check_text_state(state)
    await rt.loader.lifecycle.set_enabled(rt.key, True)
    rt.channel = await rt.manager.get_channel(rt.key)
    rt.process = rt.channel.channel_process
    assert rt.process.health_snapshot()["pid"] != old_pid
    await asyncio.sleep(0.25)
    assert await sends(rt) == []
    target, fresh = await route(rt)
    await rt.channel.send(target, "only fresh generation", fresh)
    await rt.channel._flush_response_text(fresh["response_handle"])
    assert [r["content_parts"] for r in await sends(rt)] == [
        [{"type": "text", "text": "only fresh generation"}]
    ]


@pytest.mark.asyncio
async def test_unknown_immediate_operation_rejects_new_text_before_buffer(
    runtime,
):
    rt = await merge_runtime(runtime)
    target, meta = await route(rt)
    await rt.process.call("fixture.fault", {"mode": "unknown"})
    with pytest.raises(ChannelDeliveryError):
        await rt.channel.send_media(
            target,
            {"type": "image", "image_url": "https://asset.test/a.png"},
            meta,
        )
    pending = deepcopy(meta["_pending_delivery"])
    with pytest.raises(ChannelDeliveryError):
        await rt.channel.send(target, "must not be accepted", meta)
    assert meta["response_handle"] not in rt.channel._text_merge
    assert meta["_pending_delivery"] == pending
    assert len(await sends(rt)) == 1


@pytest.mark.asyncio
async def test_consume_error_flushes_text_before_error_notification(runtime):
    from qwenpaw.schemas import AgentRequest

    rt = await merge_runtime(runtime)
    target, meta = await route(rt)
    request = AgentRequest(
        session_id="room-A", user_id="member", input=[], channel=rt.key
    )
    request.channel_meta = meta
    await rt.channel.send(target, "partial before provider error", meta)
    assert await sends(rt) == []
    await rt.channel._on_consume_error(request, target, "provider failed")
    rows = await sends(rt)
    assert len(rows) == 2
    assert rows[0]["content_parts"] == [
        {"type": "text", "text": "partial before provider error"}
    ]
    assert "provider failed" in rows[1]["content_parts"][0]["text"]
    assert meta["_reply_failed"] is True
    await rt.channel._finish_route(meta, "failed")
    assert (await inspect(rt))["finish_calls"][-1]["outcome"] == "failed"


@pytest.mark.asyncio
async def test_consume_error_does_not_send_after_unknown_partial_batch(
    runtime,
):
    from qwenpaw.schemas import AgentRequest

    rt = await merge_runtime(runtime)
    target, meta = await route(rt)
    request = AgentRequest(
        session_id="room-A", user_id="member", input=[], channel=rt.key
    )
    request.channel_meta = meta
    await rt.channel.send(target, "uncertain partial", meta)
    await rt.process.call("fixture.fault", {"mode": "unknown"})
    with pytest.raises(ChannelDeliveryError):
        await rt.channel._on_consume_error(request, target, "provider failed")
    assert len(await sends(rt)) == 1
    assert meta["_reply_unknown"] and "_last_delivery_id" not in meta


@pytest.mark.asyncio
async def test_definite_sdk_rejection_reports_failure_but_settles_route(
    runtime,
):
    from wechat_sdk_fault_source import sdk_fault_source

    rt = await merge_runtime(runtime, source_factory=sdk_fault_source)
    target, meta = await route(rt)
    await rt.channel.send(target, "definitely refused", meta)
    await rt.process.call("fixture.fault", {"mode": "sdk-refused"})
    with pytest.raises(ChannelDeliveryError) as failure:
        await rt.channel._flush_response_text(meta["response_handle"])
    assert not failure.value.side_effect_possible
    assert failure.value.state == "failed"
    assert await sends(rt) == []
    assert "_last_delivery_id" not in meta
    assert rt.channel._text_merge_bytes == 0
    await rt.channel._finish_route(meta, "failed")
    assert (await inspect(rt))["finish_calls"][-1]["outcome"] == "failed"
    assert meta["response_handle"] not in rt.channel._text_merge
    assert rt.channel._text_merge_bytes == 0


@pytest.mark.asyncio
async def test_repeated_cancellation_keeps_scope_cleanup_owned_until_settled(
    runtime,
):
    from wechat_sdk_fault_source import sdk_fault_source

    rt = await merge_runtime(runtime, source_factory=sdk_fault_source)
    target, meta = await route(rt)
    root = rt.source.parent
    (root / "finish-block").touch()
    body_waiting = asyncio.Event()

    async def scope_owner():
        async with rt.channel._response_scope(meta):
            await rt.channel.send(target, "cancel before dispatch", meta)
            body_waiting.set()
            await asyncio.Event().wait()

    owner = asyncio.create_task(scope_owner())
    try:
        async with asyncio.timeout(3):
            await body_waiting.wait()
        assert await sends(rt) == []
        owner.cancel()
        async with asyncio.timeout(3):
            while not (root / "finish-started").exists():
                await asyncio.sleep(0.01)
        owner.cancel()
        # Observe the actual context-manager generator suspended in its
        # cancellation cleanup, rather than guessing a network delay.
        async with asyncio.timeout(3):
            while True:
                exit_call = owner.get_coro().cr_await
                frame = getattr(exit_call, "cr_frame", None)
                context = frame.f_locals.get("self") if frame else None
                generator = getattr(context, "gen", None)
                if owner.cancelling() == 2 and generator is not None:
                    import inspect as inspect_source

                    suspended = generator.ag_frame
                    lines, first = inspect_source.getsourcelines(
                        rt.channel._response_scope.__wrapped__
                    )
                    shield_lines = [
                        first + index
                        for index, line in enumerate(lines)
                        if "await asyncio.shield(task)" in line
                    ]
                    if suspended and suspended.f_lineno == shield_lines[1]:
                        break
                await asyncio.sleep(0)
        owner.cancel()
        await asyncio.wait({owner}, timeout=0.02)
        assert not owner.done(), "scope abandoned its pending finish task"
        (root / "finish-release").touch()
        with pytest.raises(asyncio.CancelledError):
            await owner
        assert await sends(rt) == []
        assert rt.channel._text_merge == {}
        assert (await inspect(rt))["finish_calls"][-1]["outcome"] == (
            "cancelled"
        )
    finally:
        (root / "finish-release").touch()
        if not owner.done():
            owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)


@pytest.mark.asyncio
async def test_capability_without_policy_field_keeps_immediate_delivery(
    runtime,
):
    rt = await merge_runtime(runtime, delay=None)
    target, meta = await route(rt)
    policy = await rt.channel._response_policy(target, meta)
    assert "text_merge_delay_ms" not in policy.to_mapping()
    await rt.channel.send(target, "original exact direct body", meta)
    rows = await sends(rt)
    assert len(rows) == 1
    assert rows[0]["delivery_id"] == meta["_last_delivery_id"]
    assert rows[0]["content_parts"] == [
        {"type": "text", "text": "original exact direct body"}
    ]
    assert rt.channel._text_merge == {}
