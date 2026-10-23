"""Strict API/journal/lifecycle controls for Matrix's ordinary-event policy."""
import asyncio

import pytest

from extension_process_suite import eventually, runtime
from matrix_formal_agent_suite import assert_original_archive, formal_source
from matrix_formal_support import BOT, ROOM, SENDER, hs, matrix_host_guard

__all__ = ["runtime", "hs", "matrix_host_guard"]


async def connected(runtime, hs):
    rt = await runtime(
        "matrix",
        source_factory=formal_source,
        homeserver=hs.url,
        user_id=BOT,
        access_token="formal-matrix-token",
        streaming_enabled=False,
    )
    assert_original_archive(rt)
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] == "connected"
    )
    return rt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,state,reason",
    [
        (403, "failed", "MATRIX_SEND_REJECTED"),
        (503, "unknown", "MATRIX_SEND_UNKNOWN"),
    ],
)
async def test_formal_api_failure_and_unknown_journal_stay_strict(
    runtime, hs, status, state, reason
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await connected(runtime, hs)
    target = rt.channel.to_handle_from_target(
        user_id=ROOM, session_id="matrix:" + ROOM
    )
    meta = {"room_id": ROOM}
    policy = await rt.channel._response_policy(target, meta)
    assert policy.continue_on_delivery_error is True
    hs.send.append(
        (
            {
                "errcode": "M_FORBIDDEN" if status == 403 else "M_UNKNOWN",
                "error": "controlled refusal",
            },
            status,
        )
    )
    with pytest.raises(ChannelDeliveryError) as caught:
        await rt.channel.send(target, "strict API answer", meta)
    assert caught.value.state == state
    assert caught.value.reason_code == reason
    assert caught.value.side_effect_possible is (state == "unknown")
    assert len(hs.sent) == 1
    assert hs.sent[0]["body"]["body"] == "strict API answer"
    assert "_last_delivery_id" not in meta
    if state == "unknown":
        pending = dict(meta["_pending_delivery"])
        assert meta["_reply_unknown"] is True
        for body in ("strict API answer", "different API answer"):
            with pytest.raises(ChannelDeliveryError) as repeated:
                await rt.channel.send(target, body, meta)
            assert repeated.value.state == "unknown"
            assert repeated.value.side_effect_possible is True
            assert meta["_pending_delivery"] == pending
        assert len(hs.sent) == 1
    else:
        assert "_pending_delivery" not in meta
        assert not meta.get("_reply_unknown")


@pytest.mark.asyncio
async def test_formal_disable_after_real_policy_receipt_remains_strict(
    runtime, hs, monkeypatch
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    from qwenpaw.schemas import Message, TextContent

    rt = await connected(runtime, hs)
    actual = rt.channel._response_policy
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause_after_policy(target, meta):
        policy = await actual(target, meta)
        assert policy.continue_on_delivery_error is True
        entered.set()
        await release.wait()
        return policy

    monkeypatch.setattr(rt.channel, "_response_policy", pause_after_policy)
    request = rt.channel.build_agent_request_from_native(
        {
            "sender_id": SENDER,
            "session_id": "matrix:" + ROOM,
            "content_parts": [{"type": "text", "text": "question"}],
            "meta": {"room_id": ROOM},
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
        rt.channel.enabled = False
        release.set()
        with pytest.raises(ChannelDeliveryError) as caught:
            await sending
        assert caught.value.reason_code == "CHANNEL_DISABLED"
        assert "_continued_event_delivery_error" not in meta
        assert hs.sent == []
    finally:
        release.set()
        await asyncio.gather(sending, return_exceptions=True)
