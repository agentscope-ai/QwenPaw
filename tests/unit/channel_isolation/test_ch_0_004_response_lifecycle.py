# -*- coding: utf-8 -*-
"""Current shared-driver response aggregate and checkpoint DTO contracts."""

import pytest

from qwenpaw.channel_protocol import ResponseOutcome
from qwenpaw.channel_protocol.response_lifecycle import (
    ResponseCleanupState,
    ResponseResourceRef,
    ResponseRouteAggregate,
    ResponseRouteKind,
    ResponseRouteSnapshot,
)


def test_revoked_snapshot_cannot_be_replaced_by_old_active() -> None:
    """Restore never reopens a route after its revocation fence."""
    aggregate = ResponseRouteAggregate(max_entries=2)
    active, _ = aggregate.open("monotonic")
    revoked = aggregate.begin_revocation("monotonic")
    assert revoked is not None
    assert revoked.version == active.version + 1
    assert not aggregate.restore(active)
    assert aggregate.snapshot("monotonic") == revoked


def test_snapshot_is_closed_and_deterministic() -> None:
    """Aggregate snapshots reject open-ended state and sort collections."""
    ref = ResponseResourceRef.create(
        "feishu.delivery",
        "delivery-1",
        {"message_id": "message-1"},
    )
    snapshot = ResponseRouteSnapshot(
        response_handle="response-1",
        kind=ResponseRouteKind.TERMINAL,
        version=2,
        resource_refs=(ref,),
        outcome=ResponseOutcome.FAILED,
        cleanup_state=ResponseCleanupState.PENDING,
        closed_at_ms=1000,
    )
    assert (
        ResponseRouteSnapshot.from_mapping(snapshot.to_mapping()) == snapshot
    )
    revoked = ResponseRouteSnapshot(
        response_handle="revoked-response",
        kind=ResponseRouteKind.REVOKED,
        version=3,
        route_refs=(ref,),
        resource_refs=(ref,),
    )
    assert ResponseRouteSnapshot.from_mapping(revoked.to_mapping()) == revoked
    with pytest.raises(ValueError):
        ResponseRouteSnapshot.from_mapping(
            {**snapshot.to_mapping(), "extra": 1},
        )
