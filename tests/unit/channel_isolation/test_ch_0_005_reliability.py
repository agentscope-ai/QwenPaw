# -*- coding: utf-8 -*-
"""Current reliable event DTO validation and shared-worker retry policy."""

from __future__ import annotations

import pytest

from qwenpaw.channel_protocol import (
    DeliveryUpdateParams,
    EventBatchAck,
    EventBatchParams,
    InboundEvent,
    ProtocolValidationError,
    RetryPolicy,
    events_for_retry,
)


def _event(event_id: str = "event-1") -> dict[str, object]:
    """Return a stable inbound event fixture."""
    return {
        "event_id": event_id,
        "channel_key": "voice",
        "instance_id": "instance-1",
        "generation": 7,
        "event_kind": "message.query",
        "conversation": {"id": "chat-1", "type": "dm", "thread_id": None},
        "sender_id": "display-id",
        "acl_sender_id": "stable-id",
        "sender_name": "Alice",
        "content_parts": [{"type": "text", "text": "hello"}],
        "metadata": {},
    }


def _batch(*event_ids: str) -> EventBatchParams:
    """Return a batch containing the requested event IDs."""
    return EventBatchParams.from_mapping(
        {
            "batch_id": "generation-7-batch-1",
            "events": [_event(event_id) for event_id in event_ids],
        },
    )


def test_event_batch_and_ack_are_closed_and_round_trip() -> None:
    """Event batches and ACKs retain stable per-event classifications."""
    batch = _batch("event-1", "event-2")
    assert batch.to_mapping()["batch_id"] == "generation-7-batch-1"
    ack = EventBatchAck.from_mapping(
        {
            "batch_id": batch.batch_id,
            "accepted_event_ids": ["event-1"],
            "duplicate_event_ids": ["event-2"],
            "rejected_events": [
                {
                    "event_id": "event-3",
                    "reason_code": "TEMPORARY_UNAVAILABLE",
                    "retryable": True,
                },
            ],
        },
    )
    assert ack.rejected_events[0].retryable is True
    with pytest.raises(ProtocolValidationError):
        EventBatchAck.from_mapping(
            {
                "accepted_event_ids": [],
                "duplicate_event_ids": [],
                "rejected_events": [],
                "extra": True,
            },
        )


def test_malformed_event_does_not_poison_valid_events() -> None:
    """A malformed event becomes a permanent per-event rejection."""
    batch = EventBatchParams.from_mapping(
        {
            "batch_id": "batch-1",
            "events": [
                _event("valid"),
                {**_event("invalid"), "content_parts": "not-an-array"},
            ],
        },
    )
    assert [event.event_id for event in batch.events] == ["valid"]
    assert batch.invalid_events[0].event_id == "invalid"
    assert batch.invalid_events[0].retryable is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("generation", 6),
        ("channel_key", "other"),
        ("instance_id", "other-instance"),
    ],
)
def test_event_batch_rejects_mixed_identity(
    field: str,
    value: object,
) -> None:
    """A batch cannot mix generation or instance identity."""
    second = {**_event("event-2"), field: value}
    with pytest.raises(ProtocolValidationError):
        EventBatchParams.from_mapping(
            {
                "batch_id": "batch-1",
                "events": [_event("event-1"), second],
            },
        )


def test_event_kind_is_required_and_round_trips() -> None:
    """Every event carries a stable, non-empty kind."""
    event = _event()
    assert (
        EventBatchParams.from_mapping(
            {"batch_id": "batch-1", "events": [event]},
        )
        .events[0]
        .to_mapping()["event_kind"]
        == "message.query"
    )
    for value in (None, ""):
        invalid = event.copy()
        invalid["event_kind"] = value
        with pytest.raises(ProtocolValidationError):
            InboundEvent.from_mapping(invalid)


def test_event_batch_rejects_duplicate_event_ids() -> None:
    """A legal and malformed duplicate ID cannot form one ACK."""
    duplicate = {**_event("event-1"), "content_parts": "invalid"}
    for events in (
        [_event("event-1"), _event("event-1")],
        [_event("event-1"), duplicate],
    ):
        with pytest.raises(ProtocolValidationError):
            EventBatchParams.from_mapping(
                {"batch_id": "batch-1", "events": events},
            )


def test_all_invalid_events_can_return_rejected_ack() -> None:
    """A batch with stable identity can reject every event individually."""
    batch = EventBatchParams.from_mapping(
        {
            "batch_id": "batch-1",
            "events": [
                {**_event("invalid"), "content_parts": "not-an-array"},
            ],
        },
    )
    assert batch.events == ()
    ack = EventBatchAck.from_mapping(
        {
            "batch_id": batch.batch_id,
            "accepted_event_ids": [],
            "duplicate_event_ids": [],
            "rejected_events": [
                event.to_mapping() for event in batch.invalid_events
            ],
        },
    )
    assert not ack.accepted_event_ids
    assert ack.rejected_events[0].event_id == "invalid"
    assert ack.rejected_events[0].reason_code == "INVALID_PARAMS"
    assert ack.rejected_events[0].retryable is False
    assert ack.batch_id == batch.batch_id
    assert events_for_retry(
        batch,
        ack,
        attempt=1,
        policy=RetryPolicy(),
    ) == ((), None)


def test_retry_policy_retries_unacknowledged_and_retryable_events() -> None:
    """ACK loss and retryable rejection share the same batch ID."""
    policy = RetryPolicy(initial_delay=0.25, max_delay=0.75, max_attempts=4)
    batch = _batch("accepted", "retry", "permanent", "missing")
    ack = EventBatchAck.from_mapping(
        {
            "batch_id": batch.batch_id,
            "accepted_event_ids": ["accepted"],
            "duplicate_event_ids": [],
            "rejected_events": [
                {
                    "event_id": "retry",
                    "reason_code": "TEMPORARY_UNAVAILABLE",
                    "retryable": True,
                },
                {
                    "event_id": "permanent",
                    "reason_code": "CONFIG_INVALID",
                    "retryable": False,
                },
            ],
        },
    )
    retry, delay = events_for_retry(batch, ack, attempt=1, policy=policy)
    assert [event.event_id for event in retry] == ["retry", "missing"]
    assert delay == 0.25
    lost_ack, lost_delay = events_for_retry(
        batch,
        None,
        attempt=2,
        policy=policy,
    )
    assert [event.event_id for event in lost_ack] == [
        "accepted",
        "retry",
        "permanent",
        "missing",
    ]
    assert lost_delay == 0.5
    assert events_for_retry(
        batch,
        ack,
        attempt=4,
        policy=policy,
    ) == ((), None)


def test_delivery_update_rejects_requested_state() -> None:
    """Only Core can create the requested delivery state."""
    with pytest.raises(ProtocolValidationError):
        DeliveryUpdateParams.from_mapping(
            {
                "channel_key": "voice",
                "instance_id": "instance-1",
                "generation": 7,
                "delivery_id": "delivery-1",
                "state": "requested",
            },
        )
