# -*- coding: utf-8 -*-
"""Tests for DAG SSE event streaming heartbeat behavior."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_iter_dag_sse_events_yields_heartbeat_when_idle(monkeypatch):
    from plugin_datapaw.core.orchestration.dag_store import DAGBroadcaster
    from plugin_datapaw.core.routers.tasks import _iter_dag_sse_events

    monkeypatch.setattr(
        "plugin_datapaw.core.routers.tasks.DAG_SSE_HEARTBEAT_SECONDS",
        0.05,
    )

    sid = "s-heartbeat"
    queue = DAGBroadcaster.subscribe(sid)
    request = SimpleNamespace()
    request.is_disconnected = AsyncMock(return_value=False)

    dag_store = SimpleNamespace()
    dag_store.read = AsyncMock(return_value=None)

    stream = _iter_dag_sse_events(
        request=request,
        session_id=sid,
        dag_store=dag_store,
        queue=queue,
    )

    try:
        chunk = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
        assert chunk == ": heartbeat\n\n"
    finally:
        await stream.aclose()
        DAGBroadcaster.unsubscribe(sid, queue)


@pytest.mark.asyncio
async def test_iter_dag_sse_events_yields_snapshot_before_heartbeat():
    from plugin_datapaw.core.orchestration.dag_store import (
        DAGBroadcaster,
        format_sse,
    )
    from plugin_datapaw.core.routers.tasks import _iter_dag_sse_events

    sid = "s-snapshot"
    queue = DAGBroadcaster.subscribe(sid)
    request = SimpleNamespace()
    request.is_disconnected = AsyncMock(return_value=False)

    snapshot = {"sequence_number": 1, "current_plan": {"id": "g1"}}
    dag_store = SimpleNamespace()
    dag_store.read = AsyncMock(return_value=snapshot)

    stream = _iter_dag_sse_events(
        request=request,
        session_id=sid,
        dag_store=dag_store,
        queue=queue,
    )

    try:
        first = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
        assert first == format_sse(snapshot)

        DAGBroadcaster.push(sid, {"sequence_number": 2, "current_plan": {"id": "g2"}})
        second = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
        assert second == format_sse(
            {"sequence_number": 2, "current_plan": {"id": "g2"}},
        )
    finally:
        await stream.aclose()
        DAGBroadcaster.unsubscribe(sid, queue)


@pytest.mark.asyncio
async def test_iter_dag_sse_events_unsubscribes_on_close():
    from plugin_datapaw.core.orchestration.dag_store import DAGBroadcaster
    from plugin_datapaw.core.routers.tasks import _iter_dag_sse_events

    sid = "s-unsub"
    queue = DAGBroadcaster.subscribe(sid)
    request = SimpleNamespace()
    request.is_disconnected = AsyncMock(return_value=True)

    dag_store = SimpleNamespace()
    dag_store.read = AsyncMock(return_value=None)

    stream = _iter_dag_sse_events(
        request=request,
        session_id=sid,
        dag_store=dag_store,
        queue=queue,
    )

    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()

    assert sid not in DAGBroadcaster._queues_by_sid
