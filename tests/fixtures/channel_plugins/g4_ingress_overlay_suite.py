"""Narrow canonical-origin and inclusive-frame Source overlay controls."""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

from aiohttp import WSMsgType
import pytest
from yarl import URL

from g4_ingress_support import listener, start
from qwenpaw.plugins.execution.errors import RpcError

pytest_plugins = ["extension_process_suite", "g4_ingress_support"]


async def post(ingress, selector, host, *, forged=False):
    headers = {"Host": host}
    if forged:
        headers.update(
            {
                "X-Forwarded-Host": "attacker.invalid",
                "X-Forwarded-Proto": "http",
                "X-Qwenpaw-Ingress-Original-URL": "https://attacker.invalid/",
            }
        )
    async with ingress.client.post(
        URL(
            ingress.base + "/sample/http?x=%2f&x=a+b&_qp_endpoint=" + selector,
            encoded=True,
        ),
        headers=headers,
        data=b"canonical",
    ) as response:
        await response.read()
        return response.status


@pytest.mark.asyncio
async def test_canonical_origin_is_exact_owner_revision_and_host_scoped(
    ingress,
):
    first, one = await start(ingress)
    second, two = await start(
        ingress, existing_loader=first.loader, workspace_name="two"
    )
    await listener(
        first, "canonical", public_base_url="https://first.test:9443"
    )
    await listener(
        second, "canonical", public_base_url="https://second.test:9443"
    )
    a, b = [info["forwarding"]["route_selector"] for info in (one, two)]
    assert await post(ingress, a, "first.test:9443", forged=True) == 201
    rows = (await listener(first))["rows"]
    original = dict(
        (key.lower(), value) for key, value in rows[-1]["headers"]
    )["x-qwenpaw-ingress-original-url"]
    suffix = "/sample/http?x=%2f&x=a+b&_qp_endpoint=" + a
    assert original == "https://first.test:9443" + suffix
    assert await post(ingress, a, "second.test:9443") == 403
    assert await post(ingress, b, "first.test:9443") == 403
    assert (await listener(first))["rows"] == rows
    assert (await listener(second))["rows"] == []
    old = first.channel.endpoint_service.resolve(forwarding=True)
    updated = await listener(
        first, "canonical", public_base_url="https://new.test:9443"
    )
    assert updated["forwarding"] == one["forwarding"]
    current = first.channel.endpoint_service.resolve(forwarding=True)
    assert current.revision > old.revision
    assert not first.channel.endpoint_service.is_current(old, forwarding=True)
    assert await post(ingress, a, "first.test:9443") == 403
    assert await post(ingress, a, "new.test:9443") == 201
    original = {
        key.lower(): value
        for key, value in (await listener(first))["rows"][-1]["headers"]
    }["x-qwenpaw-ingress-original-url"]
    assert original == "https://new.test:9443" + suffix
    assert await post(ingress, b, "second.test:9443") == 201


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:secret@example.test",
        "https://example.test/path",
        "https://example.test?x=1",
        "https://example.test#fragment",
        "file://example.test",
        "https://example.test:0",
        "https://example.test:65536",
        "https://example.test\\evil",
    ],
)
def test_canonical_origin_parser_rejects_nonorigins(origin):
    from qwenpaw.app.channels.ingress import ChannelIngressService

    reference = SimpleNamespace(
        endpoint=SimpleNamespace(public_base_url=origin)
    )
    with pytest.raises(
        RuntimeError, match="HOST_INGRESS_PUBLIC_ORIGIN_INVALID"
    ):
        ChannelIngressService._canonical_origin(reference)


@pytest.mark.asyncio
async def test_native_exact_utf8_and_upstream_binary_text_overlimits(
    ingress, tmp_path, monkeypatch
):
    rt, _info = await start(ingress)
    relays = []
    original_from_child = ingress.service._from_child

    async def observe_from_child(forward):
        done = asyncio.Event()
        row = {
            "forward_id": id(forward),
            "upstream_id": id(forward.upstream),
            "owner_matches": (
                forward.binding.service is rt.channel.endpoint_service
            ),
            "finished": False,
        }
        relays.append((row, done))
        try:
            return await original_from_child(forward)
        finally:
            row.update(
                finished=True,
                upstream_close_code=forward.upstream.close_code,
                forward_close_code=forward.close_code,
            )
            done.set()

    monkeypatch.setattr(ingress.service, "_from_child", observe_from_child)
    maximum = 1024 * 1024
    async with ingress.client.ws_connect(
        ingress.base + "/sample/ws", max_msg_size=2 * maximum
    ) as socket:
        await socket.send_str("é" * (maximum // 2))
        result = await socket.receive(timeout=5)
        assert result.type == WSMsgType.TEXT and result.data == "é" * (
            maximum // 2
        )
        result = await listener(rt, "ws_emit", kind="binary", size=maximum)
        assert result["sockets"] == 1
        message = await socket.receive(timeout=5)
        assert (
            message.type == WSMsgType.BINARY and message.data == b"z" * maximum
        )
        result = await listener(rt, "ws_emit", kind="text", size=maximum // 2)
        assert result["sockets"] == 1
        message = await socket.receive(timeout=5)
        assert message.type == WSMsgType.TEXT and message.data == "é" * (
            maximum // 2
        )
    for kind, size in (("binary", maximum + 1), ("text", maximum // 2 + 1)):
        # Client close handshake may finish before the real child handler
        # leaves its finally block. Await that resource before a new case.
        async with asyncio.timeout(5):
            while (await listener(rt))["ws_count"]:
                await asyncio.sleep(0.01)
        async with ingress.client.ws_connect(
            ingress.base + "/sample/ws", max_msg_size=2 * maximum
        ) as socket:
            await socket.send_str("ready")
            assert (await socket.receive(timeout=5)).data == "ready"
            active = [(row, done) for row, done in relays if not done.is_set()]
            assert len(active) == 1
            host_report, relay_done = active[0]
            assert host_report["owner_matches"] is True
            attempt_id = uuid4().hex
            emission = asyncio.create_task(
                listener(
                    rt,
                    "ws_emit",
                    kind=kind,
                    size=size,
                    attempt_id=attempt_id,
                )
            )
            try:
                # A receiver enforcing its limit may close during sender
                # drain. The real downstream result must be observed first.
                message = await socket.receive(timeout=5)
                assert message.type == WSMsgType.CLOSE and message.data == 1013
                rpc_error = None
                try:
                    result = await emission
                except RpcError as error:
                    rpc_error = error
                await asyncio.wait_for(relay_done.wait(), timeout=5)
                report = await listener(rt, "ws_emit_report")
                report["host_relay"] = host_report
                (tmp_path / f"overlimit-{kind}-observation.json").write_text(
                    json.dumps(report, indent=2)
                )
                assert host_report["finished"] is True
                assert host_report["upstream_close_code"] == 1009
                assert host_report["forward_close_code"] == 1013
                assert report["attempt_id"] == attempt_id
                assert (report["kind"], report["size"]) == (kind, size)
                assert len(report["selected_socket_ids"]) == 1
                assert len(report["attempts"]) == 1
                attempt = report["attempts"][0]
                assert attempt["socket_id"] == report["selected_socket_ids"][0]
                assert attempt["open_before"] is True
                assert attempt["payload_bytes"] == (
                    size if kind == "binary" else 2 * size
                )
                if rpc_error is None:
                    assert result["sockets"] == 1
                    assert attempt["completed"] is True
                    assert "error" not in attempt
                else:
                    assert rpc_error.code == -32603
                    assert attempt["completed"] is False
                    error = attempt["error"]
                    assert error["exception_module"] == "builtins"
                    assert error["exception_type"] == "ConnectionError"
                    assert error["exception"] == "Connection lost"
                    # Child read-loop state at write failure is diagnostic.
                    # The actual host parser rejection above proves 1009.
            finally:
                if not emission.done():
                    emission.cancel()
                await asyncio.gather(emission, return_exceptions=True)
    async with ingress.client.ws_connect(
        ingress.base + "/sample/ws"
    ) as socket:
        await socket.send_bytes(b"z" * (maximum + 1))
        message = await socket.receive(timeout=5)
        assert message.type == WSMsgType.CLOSE and message.data == 1013
