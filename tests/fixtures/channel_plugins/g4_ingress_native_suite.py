"""Actual native local traffic through an owned shared-worker endpoint."""

import os

from aiohttp import WSMsgType
import pytest
from yarl import URL

from g4_ingress_support import listener, start

pytest_plugins = ["extension_process_suite", "g4_ingress_support"]


@pytest.mark.asyncio
async def test_native_http_preserves_raw_request_and_response(
    ingress, monkeypatch
):
    rt, info = await start(ingress)
    assert info["pid"] != os.getpid()
    selector = info["forwarding"]["route_selector"]
    query = "?a=%2F&a=two+words&blank=&_qp_endpoint=" + selector
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    body = b"raw\x00body\xff"
    async with ingress.client.post(
        URL(ingress.base + "/sample/http" + query, encoded=True),
        data=body,
        headers=[
            ("X-Duplicate", "one"),
            ("X-Duplicate", "two"),
            ("X-Qwenpaw-Ingress-Token", "forged"),
            ("X-Qwenpaw-Ingress-Original-URL", "https://forged/"),
            ("Connection", "X-Remove"),
            ("X-Remove", "no"),
        ],
    ) as response:
        assert response.status == 201
        assert response.headers.getall("X-Reply") == ["first", "second"]
        assert response.headers["Content-Type"] == "application/x-test"
        assert await response.read() == body
    row = (await listener(rt))["rows"][0]
    assert row["method"] == "POST"
    assert row["raw_path"] == "/sample/http" + query
    assert row["body_hex"] == body.hex()
    assert row["authenticated"] is True
    headers = [(key.lower(), value) for key, value in row["headers"]]
    assert [v for k, v in headers if k == "x-duplicate"] == ["one", "two"]
    assert not any(k == "x-remove" for k, _ in headers)
    assert (
        "x-qwenpaw-ingress-original-url",
        ingress.base + "/sample/http" + query,
    ) in headers
    async with ingress.client.post(
        ingress.base + "/sample/redirect", allow_redirects=False
    ) as response:
        assert response.status == 307
        assert response.headers["Location"] == "/sample/target"
    assert [
        row["raw_path"].split("?")[0] for row in (await listener(rt))["rows"]
    ] == ["/sample/http", "/sample/redirect"]


@pytest.mark.asyncio
async def test_native_websocket_handshake_frames_and_close(ingress):
    rt, info = await start(ingress)
    selector = info["forwarding"]["route_selector"]
    async with ingress.client.ws_connect(
        ingress.base + "/sample/ws?_qp_endpoint=" + selector,
        protocols=("sample.v1",),
    ) as socket:
        assert socket.protocol == "sample.v1"
        await socket.send_str("hello")
        message = await socket.receive(timeout=5)
        assert message.type == WSMsgType.TEXT and message.data == "hello"
        await socket.send_bytes(b"\x00\xff")
        message = await socket.receive(timeout=5)
        assert message.type == WSMsgType.BINARY and message.data == b"\x00\xff"
        await socket.send_str("close")
        message = await socket.receive(timeout=5)
        assert message.type == WSMsgType.CLOSE and message.data == 1000
        assert message.extra == "done"
    assert (await listener(rt))["rows"][0]["authenticated"] is True


@pytest.mark.parametrize(
    "name", ["connect_timeout", "http_timeout", "shutdown_timeout"]
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_ingress_limits_reject_nonfinite(name, value):
    from qwenpaw.app.channels.ingress import IngressLimits

    with pytest.raises(ValueError, match="invalid ingress limit"):
        IngressLimits(**{name: value})
