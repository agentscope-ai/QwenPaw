# -*- coding: utf-8 -*-
"""Bounded response route lifecycle state."""

from qwenpaw.channel_protocol.response_lifecycle import (
    ResponseRouteAggregate,
    ResponseRouteKind,
    ResponseRouteSnapshot,
)


def test_active_route_records_and_filters_by_open_time():
    now = [1_000]
    routes = ResponseRouteAggregate(
        max_entries=3,
        clock_ms=lambda: now[0],
    )

    old, _ = routes.open("route:old")
    now[0] += 999
    fresh, _ = routes.open("route:fresh")
    now[0] += 1

    assert old.opened_at_ms == 1_000
    assert fresh.opened_at_ms == 1_999
    assert routes.stale_active(1_000) == (old,)


def test_legacy_active_snapshot_without_open_time_remains_readable():
    now = [1_000]
    routes = ResponseRouteAggregate(
        max_entries=1,
        clock_ms=lambda: now[0],
    )
    snapshot, _ = routes.open("route:legacy")
    legacy = snapshot.to_mapping()
    legacy.pop("opened_at_ms")

    restored = ResponseRouteAggregate(max_entries=1, clock_ms=lambda: now[0])
    parsed = ResponseRouteSnapshot.from_mapping(legacy)

    assert parsed.kind is ResponseRouteKind.ACTIVE
    assert parsed.opened_at_ms is None
    assert restored.restore(parsed)
    assert restored.stale_active(0) == ()
