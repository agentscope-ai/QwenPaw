# -*- coding: utf-8 -*-
"""Shared Channel event acknowledgement and bounded retry policy."""

from __future__ import annotations

from dataclasses import dataclass

from .models import EventBatchAck, EventBatchParams, InboundEvent


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded deterministic exponential retry policy."""

    initial_delay: float = 0.1
    max_delay: float = 5.0
    max_attempts: int = 5

    def __post_init__(self) -> None:
        """Reject policies that cannot make progress."""
        if self.initial_delay <= 0:
            raise ValueError("initial_delay must be positive")
        if self.max_delay < self.initial_delay:
            raise ValueError(
                "max_delay must not be smaller than initial_delay",
            )
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")

    def delay_for(self, attempt: int) -> float:
        """Return the bounded delay before a one-based retry attempt."""
        if attempt <= 0:
            raise ValueError("attempt must be positive")
        return min(self.initial_delay * (2 ** (attempt - 1)), self.max_delay)


def events_for_retry(
    batch: EventBatchParams,
    ack: EventBatchAck | None,
    *,
    attempt: int,
    policy: RetryPolicy,
) -> tuple[tuple[InboundEvent, ...], float | None]:
    """Return retryable events and their next backoff delay."""
    if attempt >= policy.max_attempts:
        return (), None
    if ack is None:
        return batch.events, policy.delay_for(attempt)
    if ack.batch_id is not None and ack.batch_id != batch.batch_id:
        raise ValueError("ACK batch_id does not match the submitted batch")
    rejected = {item.event_id: item.retryable for item in ack.rejected_events}
    acknowledged = set(ack.accepted_event_ids)
    acknowledged.update(ack.duplicate_event_ids)
    retry_events = tuple(
        event
        for event in batch.events
        if rejected.get(event.event_id, False)
        or (
            event.event_id not in acknowledged
            and event.event_id not in rejected
        )
    )
    if not retry_events:
        return (), None
    return retry_events, policy.delay_for(attempt)


__all__ = ["RetryPolicy", "events_for_retry"]
