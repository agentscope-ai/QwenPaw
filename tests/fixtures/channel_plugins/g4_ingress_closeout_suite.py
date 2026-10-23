"""Remaining relay barriers with real Loader, worker and native sockets."""

import asyncio
import os
from pathlib import Path

import aiohttp
import pytest

from extension_process_suite import eventually
from g4_ingress_support import listener, listener_source

pytest_plugins = ["extension_process_suite", "g4_ingress_support"]


def barrier_source(directory, key, **kwargs):
    source = listener_source(directory, key, **kwargs)
    child = source / key / "listener.py"
    body = child.read_text()
    anchor = '        if request.path == "/sample/ws-reject":\n'
    assert body.count(anchor) == 1
    body = body.replace(
        anchor,
        """        if request.query.get("barrier") == "opening":
            await self.release.wait()
        if request.query.get("barrier") == "broken":
            request.transport.abort()
            return web.Response(status=204)
""" + anchor,
    )
    child.write_text(body)
    return source


async def start_barrier(ingress):
    rt = await ingress.runtime(source_factory=barrier_source)
    info = await listener(rt)
    assert info["pid"] == rt.process.health_snapshot()["pid"] != os.getpid()
    assert info["forwarding"]["host_port"] == ingress.port
    return rt


def forwards(service):
    return [
        forward
        for binding in (*service._bindings.values(), *service._retired)
        for forward in binding.forwards
    ]


async def row_count(rt, count):
    async with asyncio.timeout(5):
        while len((await listener(rt))["rows"]) != count:
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_actual_opening_handshake_stop_never_accepts(ingress):
    rt = await start_barrier(ingress)
    opening = asyncio.ensure_future(
        ingress.client.ws_connect(ingress.base + "/sample/ws?barrier=opening")
    )
    try:
        await row_count(rt, 1)
        records = forwards(ingress.service)
        assert len(records) == 1
        record = records[0]
        assert record.upstream is None and record.websocket is None
        assert not opening.done()
        receipt = await rt.manager.stop_one(rt.key)
        assert receipt.stopped and receipt.exited and receipt.residual == ()
        assert rt.process.health_snapshot()["pid"] is None
        assert (
            rt.channel._runtime_lease
            not in ingress.registry.runtime_owners.leases()
        )
        with pytest.raises(aiohttp.ClientError):
            await asyncio.wait_for(opening, 5)
        assert record.task.done()
        assert not forwards(ingress.service)
        async with ingress.client.post(
            ingress.base + "/sample/http"
        ) as response:
            assert response.status == 503
    finally:
        if not opening.done():
            opening.cancel()
        await asyncio.gather(opening, return_exceptions=True)


@pytest.mark.asyncio
async def test_actual_stop_receipt_retains_ingress_residual_until_retry(
    ingress, monkeypatch
):
    rt = await start_barrier(ingress)
    socket = await ingress.client.ws_connect(ingress.base + "/sample/ws")
    await socket.send_str("ready")
    assert (await socket.receive(timeout=5)).data == "ready"
    (record,) = forwards(ingress.service)
    entered, release = asyncio.Event(), asyncio.Event()
    original_close = record.upstream.close

    async def blocked_close(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original_close(*args, **kwargs)

    monkeypatch.setattr(record.upstream, "close", blocked_close)
    stop = asyncio.create_task(rt.manager.stop_one(rt.key))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        receipt = await asyncio.wait_for(asyncio.shield(stop), 5)
        assert not receipt.stopped and receipt.exited
        assert receipt.residual == ("CHANNEL_INGRESS_CLEANUP_PENDING",)
        assert receipt.instance_id == rt.channel._runtime_lease.instance_id
        assert receipt.generation == rt.channel._runtime_lease.generation
        assert rt.process.health_snapshot()["pid"] is None
        assert (
            rt.channel._runtime_lease
            in ingress.registry.runtime_owners.leases()
        )
        assert await rt.manager.get_channel(rt.key) is rt.channel
        assert record in forwards(ingress.service)
        assert not record.cleanup.done()
        assert rt.channel.endpoint_service.resolve(forwarding=True) is None
        release.set()
        await asyncio.wait_for(asyncio.shield(record.cleanup), 5)
        retry = await rt.manager.stop_one(rt.key)
        assert retry.stopped and retry.exited and retry.residual == ()
        assert (
            rt.channel._runtime_lease
            not in ingress.registry.runtime_owners.leases()
        )
        assert await rt.manager.get_channel(rt.key) is None
        assert not forwards(ingress.service)
    finally:
        release.set()
        await asyncio.gather(stop, return_exceptions=True)
        await socket.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["to_child", "from_child"])
async def test_actual_writer_backpressure_cancellation_barrier(
    ingress, monkeypatch, direction
):
    rt = await start_barrier(ingress)
    socket = await ingress.client.ws_connect(ingress.base + "/sample/ws")
    await socket.send_str("ready")
    assert (await socket.receive(timeout=5)).data == "ready"
    (record,) = forwards(ingress.service)
    entered, release, cancelled = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    calls, sent = [], []
    target = record.upstream if direction == "to_child" else record.websocket
    method = "send_str" if direction == "to_child" else "send_text"
    original = getattr(target, method)

    async def blocked_send(data, *args, **kwargs):
        calls.append(data)
        entered.set()
        try:
            await release.wait()
            result = await original(data, *args, **kwargs)
            sent.append(data)
            return result
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(target, method, blocked_send)
    try:
        if direction == "to_child":
            await socket.send_str("first")
            await socket.send_str("second")
        else:
            assert (await listener(rt, "ws_emit", kind="text", size=1))[
                "sockets"
            ] == 1
            assert (await listener(rt, "ws_emit", kind="text", size=2))[
                "sockets"
            ] == 1
        await asyncio.wait_for(entered.wait(), 5)
        # Native receive queues may hold the second frame, but the relay must
        # await the first actual writer: no parallel writer / unbounded tasks.
        for _ in range(10):
            await asyncio.sleep(0)
        assert calls == (["first"] if direction == "to_child" else ["é"])
        assert sent == [] and len(record.pumps) == 2
        receipt = await rt.manager.stop_one(rt.key)
        assert receipt.stopped and receipt.exited and receipt.residual == ()
        assert cancelled.is_set() and sent == []
        assert all(task.done() for task in record.pumps)
        assert all(task.done() for task in record.closers)
        assert not forwards(ingress.service)
        assert rt.process.health_snapshot()["pid"] is None
    finally:
        release.set()
        await socket.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["http", "ws"])
async def test_actual_broken_upstream_is_attempted_once(ingress, protocol):
    rt = await start_barrier(ingress)
    path = f"/sample/{protocol}?barrier=broken"
    if protocol == "http":
        async with ingress.client.post(
            ingress.base + path, data=b"one-effect"
        ) as response:
            assert response.status == 502
            await response.read()
    else:
        with pytest.raises(aiohttp.WSServerHandshakeError) as caught:
            await ingress.client.ws_connect(ingress.base + path)
        assert caught.value.status == 502
    rows = (await listener(rt))["rows"]
    assert len(rows) == 1 and rows[0]["raw_path"] == path
    assert rows[0]["authenticated"] is True
    await eventually(lambda: not forwards(ingress.service))
    # A second explicit caller operation works; the failed operation was not
    # transparently reissued on a fresh connection by the host client.
    async with ingress.client.post(
        ingress.base + "/sample/http", data=b"next"
    ) as response:
        assert response.status == 201 and await response.read() == b"next"
    rows = (await listener(rt))["rows"]
    assert [row["raw_path"] for row in rows] == [path, "/sample/http"]
