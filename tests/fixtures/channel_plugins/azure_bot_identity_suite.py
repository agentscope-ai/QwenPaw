"""Private native identity regression; the host boundary is not Core/Agent."""

import json

import pytest

from qwenpaw.channel_protocol.models import (
    EventBatchAck,
    EventBatchParams,
    ResponseFinishParams,
    SendParams,
)

from azure_bot_native_support import activity, azure, connector, post, rsa_material

pytestmark = pytest.mark.asyncio


def observe_admission(peer, monkeypatch, *, lose_first_ack=False):
    """Record real DTO calls; model only the allowed host ACK boundary."""
    original = peer.call
    calls, accepted, acknowledgments = [], set(), []

    async def call(method, params):
        if method != "event.batch":
            return await original(method, params)
        batch = EventBatchParams.from_mapping(params)
        # Compare the entire protocol payload, excluding per-call RPC envelopes.
        calls.append(json.dumps(params, ensure_ascii=False).encode("utf-8"))
        await original(method, params)
        new = tuple(
            event.event_id for event in batch.events if event.event_id not in accepted
        )
        duplicates = tuple(
            event.event_id for event in batch.events if event.event_id in accepted
        )
        accepted.update(new)
        ack = EventBatchAck(
            batch_id=batch.batch_id,
            accepted_event_ids=new,
            duplicate_event_ids=duplicates,
        ).to_mapping()
        acknowledgments.append(ack)
        if lose_first_ack and len(calls) == 1:
            raise TimeoutError("independent host ACK lost after admission")
        return ack

    monkeypatch.setattr(peer, "call", call)
    return calls, accepted, acknowledgments


async def test_exact_native_id_survives_repeat_and_distinct_ids_keep_same_text(
    azure, connector, monkeypatch
):
    async with azure() as (driver, peer):
        calls, accepted, acks = observe_admission(peer, monkeypatch)
        native_id = "provider/id:%same"
        assert (await post(driver, connector, activity(id=native_id)))[0] == 200
        assert (
            await post(driver, connector, activity(id=native_id, text="changed body"))
        )[0] == 200
        assert (await post(driver, connector, activity(id="provider/different")))[
            0
        ] == 200
        first, duplicate, distinct = peer.events
        expected = "msteams:conversation-ABCDEFGHIJ:" + native_id
        assert first.event_id == duplicate.event_id == expected
        assert first.response_handle == duplicate.response_handle
        assert distinct.event_id == "msteams:conversation-ABCDEFGHIJ:provider/different"
        assert distinct.response_handle != first.response_handle
        assert first.content_parts == distinct.content_parts
        assert duplicate.content_parts != first.content_parts
        assert acks[1]["duplicate_event_ids"] == [expected]
        assert acks[1]["accepted_event_ids"] == []
        assert accepted == {expected, distinct.event_id}
        assert len(calls) == 3
        assert len(driver._routes.snapshots()) == 2


@pytest.mark.parametrize(
    "native_id", ["provider/retry-id", ""], ids=["native-id", "idless"]
)
async def test_one_admission_retry_preserves_complete_event_batch_and_handle_bytes(
    azure, connector, monkeypatch, native_id
):
    async with azure() as (driver, peer):
        calls, accepted, acks = observe_admission(
            peer, monkeypatch, lose_first_ack=True
        )
        assert (await post(driver, connector, activity(id=native_id)))[0] == 200
        assert len(calls) == 2
        assert calls[0] == calls[1]
        first, retry = (json.loads(value) for value in calls)
        assert first["batch_id"] == retry["batch_id"]
        assert first["events"] == retry["events"]
        (event,) = peer.events[:1]
        assert event.event_id and event.response_handle
        if native_id:
            assert event.event_id == "msteams:conversation-ABCDEFGHIJ:" + native_id
        assert len(accepted) == 1
        assert acks[0]["accepted_event_ids"] == [event.event_id]
        assert acks[1]["duplicate_event_ids"] == [event.event_id]
        assert acks[1]["accepted_event_ids"] == []
        assert len(driver._routes.snapshots()) == 1
        assert not any(
            params["reason_code"] == "HOST_ADMISSION_EXHAUSTED"
            for method, params in peer.notifications
            if method == "channel.diagnostic"
        )


async def test_idless_reply_after_admission_retry_retains_unknown_effect_without_replay(
    azure, connector, monkeypatch
):
    async with azure() as (driver, peer):
        calls, _, _ = observe_admission(peer, monkeypatch, lose_first_ack=True)
        assert (await post(driver, connector, activity(id="")))[0] == 200
        assert len(calls) == 2 and calls[0] == calls[1]
        event = peer.events[0]
        connector.activity_status = 500
        mapping = {
            **driver._context.identity.to_mapping(),
            "delivery_id": "uncertain-idless-text",
            "to_handle": event.response_handle,
            "operation": "message.create",
            "content_parts": [{"type": "text", "text": "outgoing"}],
            "content_source": "direct",
        }
        result = await driver._send(SendParams.from_mapping(mapping), None)
        assert result["state"] == "unknown"
        assert len(connector.requests) == 1
        assert connector.requests[0][0].endswith("/activities")
        assert connector.requests[0][1]["text"] == "outgoing"
        assert await driver._send(SendParams.from_mapping(mapping), None) == result
        await driver._finish(
            ResponseFinishParams.from_mapping(
                {
                    **driver._context.identity.to_mapping(),
                    "response_handle": event.response_handle,
                    "outcome": "completed",
                }
            ),
            None,
        )
        assert await driver._send(SendParams.from_mapping(mapping), None) == result
        assert len(connector.requests) == 1
        attempts = [
            ref
            for ref in driver._routes.snapshot(event.response_handle).resource_refs
            if ref.kind == "azure_bot.attempt"
            and ref.resource_id == mapping["delivery_id"]
        ]
        assert len(attempts) == 1
        assert dict(attempts[0].attributes)["state"] == "unknown"
