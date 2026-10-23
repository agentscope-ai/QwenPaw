"""Selection, revision and bounded native transport through real owners."""

import asyncio

import aiohttp
from aiohttp import WSMsgType
import pytest

from extension_process_suite import eventually
from g4_ingress_support import listener, start

pytest_plugins = ["extension_process_suite", "g4_ingress_support"]


async def status(ingress, path, body=b"x"):
    async with ingress.client.post(ingress.base + path, data=body) as response:
        await response.read()
        return response.status


@pytest.mark.asyncio
async def test_actual_two_workspaces_select_exact_owner_and_legacy_ambiguity(
    ingress,
):
    first, one = await start(ingress)
    selector = one["forwarding"]["route_selector"]
    assert await status(ingress, "/sample/http") == 201
    second, two = await start(
        ingress, existing_loader=first.loader, workspace_name="second"
    )
    other = two["forwarding"]["route_selector"]
    assert selector != other
    assert (
        one["forwarding"]["bridge_token"] != two["forwarding"]["bridge_token"]
    )
    assert one["pid"] != two["pid"]
    assert await status(ingress, "/sample/http") == 409
    assert await status(ingress, "/sample/http?_qp_endpoint=unknown") == 503
    assert await status(ingress, "/sample/http?_qp_endpoint=") == 400
    assert (
        await status(
            ingress,
            "/sample/http?_qp_endpoint="
            + selector
            + "&_qp_endpoint="
            + selector,
        )
        == 400
    )
    for value, body in ((selector, b"first-only"), (other, b"second-only")):
        assert (
            await status(ingress, "/sample/http?_qp_endpoint=" + value, body)
            == 201
        )
    assert [row["body_hex"] for row in (await listener(first))["rows"]] == [
        b"x".hex(),
        b"first-only".hex(),
    ]
    assert [row["body_hex"] for row in (await listener(second))["rows"]] == [
        b"second-only".hex()
    ]


@pytest.mark.asyncio
async def test_actual_same_generation_update_closes_old_flow_reuses_selector(
    ingress,
):
    rt, before = await start(ingress)
    wire = before["forwarding"]
    endpoint = rt.channel.endpoint_service.resolve(forwarding=True)
    async with ingress.client.ws_connect(
        ingress.base + "/sample/ws?_qp_endpoint=" + wire["route_selector"]
    ) as socket:
        await socket.send_str("before")
        assert (await socket.receive(timeout=5)).data == "before"
        after = await listener(rt, "rebind")
        assert after["port"] != before["port"]
        assert after["forwarding"] == wire
        current = rt.channel.endpoint_service.resolve(forwarding=True)
        assert current.endpoint.generation == endpoint.endpoint.generation
        assert current.revision > endpoint.revision
        assert not rt.channel.endpoint_service.is_current(
            endpoint, forwarding=True
        )
        message = await socket.receive(timeout=5)
        assert message.type == WSMsgType.CLOSE and message.data == 1013
    assert (
        await status(
            ingress,
            "/sample/http?_qp_endpoint=" + wire["route_selector"],
            b"new-port",
        )
        == 201
    )
    assert (await listener(rt))["rows"][-1]["body_hex"] == b"new-port".hex()


@pytest.mark.asyncio
async def test_actual_worker_crash_fences_and_restart_does_not_fallback_old_selector(  # noqa: E501
    ingress,
):
    from qwenpaw.app.channels.process_supervisor import ChannelCallUnknown

    rt, before = await start(ingress)
    old = before["forwarding"]["route_selector"]
    with pytest.raises(ChannelCallUnknown):
        await listener(rt, "crash")
    assert rt.channel.endpoint_service.resolve(forwarding=True) is None
    assert await status(ingress, "/sample/http?_qp_endpoint=" + old) == 503
    await rt.loader.lifecycle.set_enabled(rt.key, False)
    await rt.loader.lifecycle.set_enabled(rt.key, True)
    rt.channel = await rt.manager.get_channel(rt.key)
    rt.process = rt.channel.channel_process
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] == "connected"
    )
    after = await listener(rt)
    assert after["forwarding"]["route_selector"] != old
    assert (
        after["forwarding"]["bridge_token"]
        != before["forwarding"]["bridge_token"]
    )
    assert await status(ingress, "/sample/http?_qp_endpoint=" + old) == 503
    assert await status(ingress, "/sample/http") == 201


@pytest.mark.asyncio
@pytest.mark.parametrize("gate", ["enabled", "ingress"])
async def test_actual_gate_fences_open_websocket_and_new_requests(
    ingress, gate
):
    rt, info = await start(ingress)
    path = "/sample/ws?_qp_endpoint=" + info["forwarding"]["route_selector"]
    async with ingress.client.ws_connect(ingress.base + path) as socket:
        await socket.send_str("live")
        assert (await socket.receive(timeout=5)).data == "live"
        if gate == "enabled":
            rt.channel.enabled = False
        else:
            rt.channel.set_enqueue_async(None)
        assert rt.channel.endpoint_service.resolve(forwarding=True) is None
        message = await socket.receive(timeout=5)
        assert message.type == WSMsgType.CLOSE and message.data == 1013
    assert await status(ingress, "/sample/http") == 503


@pytest.mark.asyncio
async def test_actual_upstream_rejects_handshake_before_external_accept(
    ingress,
):
    rt, _info = await start(ingress)
    with pytest.raises(aiohttp.WSServerHandshakeError) as caught:
        await ingress.client.ws_connect(ingress.base + "/sample/ws-reject")
    assert caught.value.status == 403
    assert (await listener(rt))["rows"][0]["raw_path"] == "/sample/ws-reject"


@pytest.mark.asyncio
async def test_actual_body_and_websocket_frame_boundaries(ingress):
    rt, _info = await start(ingress)
    maximum = 1024 * 1024
    assert ingress.service.limits.http_body_bytes == maximum
    assert ingress.service.limits.ws_frame_bytes == maximum
    assert await status(ingress, "/sample/http", b"a" * maximum) == 201
    assert await status(ingress, "/sample/http", b"a" * (maximum + 1)) == 413

    async def chunks():
        yield b"b" * maximum
        yield b"b"

    async with ingress.client.post(
        ingress.base + "/sample/http", data=chunks()
    ) as response:
        assert response.status == 413
    async with ingress.client.ws_connect(
        ingress.base + "/sample/ws", max_msg_size=2 * maximum
    ) as socket:
        await socket.send_bytes(b"c" * maximum)
        message = await socket.receive(timeout=5)
        assert (
            message.type == WSMsgType.BINARY and message.data == b"c" * maximum
        )
        await socket.send_str("é" * (maximum // 2 + 1))
        message = await socket.receive(timeout=5)
        assert message.type == WSMsgType.CLOSE and message.data == 1013
    # Observations use the control RPC's existing 1MiB frame budget. Compare
    # the same exact bytes in the child, rather than return 2MiB body.hex.
    observed = await listener(rt, "body_count", byte=ord("a"), size=maximum)
    assert observed["exact_body_count"] == 1


@pytest.mark.asyncio
async def test_actual_default_owner_concurrency_64_is_shared_by_http_and_ws(
    ingress,
):
    rt, _info = await start(ingress)
    assert ingress.service.limits.owner_concurrency == 64
    sockets = []
    try:
        for _ in range(64):
            sockets.append(
                await ingress.client.ws_connect(ingress.base + "/sample/ws")
            )
        assert (await listener(rt))["ws_count"] == 64
        assert await status(ingress, "/sample/http") == 503
        with pytest.raises(aiohttp.WSServerHandshakeError) as caught:
            await ingress.client.ws_connect(ingress.base + "/sample/ws")
        assert caught.value.status == 503
        await sockets.pop().close()
        async with asyncio.timeout(5):
            while (await listener(rt))["ws_count"] != 63:
                await asyncio.sleep(0.01)
        assert await status(ingress, "/sample/http") == 201
    finally:
        await asyncio.gather(*(socket.close() for socket in sockets))
