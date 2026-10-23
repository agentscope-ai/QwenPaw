"""Rejected manager drains restore actual worker HTTP and WebSocket ingress."""

import asyncio

import aiohttp
import pytest

from extension_process_suite import emit, eventually
from g4_ingress_support import listener, start

pytest_plugins = ["extension_process_suite", "g4_ingress_support"]


async def assert_closed(ingress):
    async with ingress.client.post(
        ingress.base + "/sample/http", data=b"closed"
    ) as response:
        assert response.status == 503
    with pytest.raises(aiohttp.WSServerHandshakeError) as caught:
        await ingress.client.ws_connect(ingress.base + "/sample/ws")
    assert caught.value.status == 503


async def assert_open(ingress):
    async with ingress.client.post(
        ingress.base + "/sample/http", data=b"resumed"
    ) as response:
        assert response.status == 201
        assert await response.read() == b"resumed"
    async with ingress.client.ws_connect(
        ingress.base + "/sample/ws"
    ) as socket:
        await socket.send_str("resumed")
        assert (await socket.receive(timeout=5)).data == "resumed"


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["timeout", "cancel"])
@pytest.mark.parametrize("stage", ["enqueue", "channel"])
async def test_actual_rejected_quiesce_restores_same_endpoint(
    ingress, interruption, stage, monkeypatch
):
    from qwenpaw.channel_protocol.errors import RpcError

    rt, info = await start(ingress, capture_ingress=True)
    service = rt.channel.endpoint_service
    reference = service.resolve(forwarding=True)
    assert reference is not None
    endpoint = reference.endpoint.to_mapping()
    identity = rt.channel._identity()
    binding = ingress.service._bindings[service]
    queues = rt.manager._queue_manager
    await assert_open(ingress)
    before = len((await listener(rt))["rows"])
    assert (await emit(rt))["accepted_event_ids"] == ["event-one"]
    (payload,) = rt.ws.received
    entered, release = asyncio.Event(), asyncio.Event()
    lock_held = stage == "enqueue"
    if lock_held:
        # Exercise the pending-enqueue branch with actual admitted work.
        await queues._lock.acquire()
    else:
        # Exercise _drain_channel with a real dequeued batch still running
        # its agent; the queue and manager drain implementations stay intact.
        original = rt.channel._process

        async def blocked_agent(request):
            entered.set()
            await release.wait()
            async for event in original(request):
                yield event

        monkeypatch.setattr(rt.channel, "_process", blocked_agent)
    rt.manager.enqueue(rt.key, payload)
    if lock_held:
        await eventually(lambda: rt.manager._enqueue_tasks)
    else:
        await asyncio.wait_for(entered.wait(), 5)
        await eventually(lambda: not rt.manager._enqueue_tasks)
        assert not await queues.drain(rt.key, timeout=0)
    quiescing = asyncio.create_task(
        rt.manager.quiesce(timeout=1 if interruption == "timeout" else 10)
    )
    try:
        await eventually(lambda: rt.key in rt.manager._paused_channels)
        assert not rt.channel._ingress_open
        assert service.resolve(forwarding=True) is None
        await assert_closed(ingress)
        # Cross more than one production custody-watch interval while paused.
        # Otherwise a resume could conceal a watcher that revokes the binding.
        await asyncio.sleep(0.15)
        await assert_closed(ingress)
        assert len((await listener(rt))["rows"]) == before
        if interruption == "cancel":
            quiescing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await quiescing
        else:
            assert not await asyncio.wait_for(quiescing, 5)
        if lock_held:
            queues._lock.release()
            lock_held = False
        release.set()
        await eventually(lambda: not rt.manager._enqueue_tasks)
        assert await queues.drain(rt.key, timeout=5)
        assert await rt.manager.get_channel(rt.key) is rt.channel
        assert rt.manager._queue_manager is queues
        assert rt.channel._ingress_open
        assert rt.channel._identity() == identity
        assert rt.process.health_snapshot()["pid"] == info["pid"]
        await assert_open(ingress)
        restored = service.resolve(forwarding=True)
        assert restored is not None
        assert restored.endpoint.to_mapping() == endpoint
        assert ingress.service._bindings[service] is binding
        assert not binding.fenced
        # A final authority fence must remain irreversible even if manager
        # admission resumes and the original endpoint is registered again.
        service.fence()
        rt.manager.resume_ingress()
        await assert_closed(ingress)
        with pytest.raises(RpcError) as caught:
            await service.register(endpoint)
        assert caught.value.data["reason_code"] == "GENERATION_REVOKED"
        stopped = await rt.manager.stop_one(rt.key)
        assert stopped.stopped and stopped.exited and not stopped.residual
        rt.manager.resume_ingress()
        assert service.resolve(forwarding=True) is None
        await assert_closed(ingress)
    finally:
        release.set()
        if lock_held:
            queues._lock.release()
        if not quiescing.done():
            quiescing.cancel()
        await asyncio.gather(quiescing, return_exceptions=True)
