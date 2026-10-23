"""Observe the exact Original-URL at a real child websocket listener."""

import json

from aiohttp import WSMsgType
import pytest
from yarl import URL

from g4_ingress_support import listener, start

pytest_plugins = ["extension_process_suite", "g4_ingress_support"]


@pytest.mark.asyncio
async def test_canonical_https_original_url_at_native_websocket_listener(
    ingress, tmp_path
):
    rt, info = await start(ingress)
    await listener(
        rt, "canonical", public_base_url="https://websocket.test:9443"
    )
    suffix = (
        "/sample/ws?x=%2f&x=a+b&_qp_endpoint="
        + info["forwarding"]["route_selector"]
    )
    async with ingress.client.ws_connect(
        URL(ingress.base + suffix, encoded=True),
        headers={"Host": "websocket.test:9443"},
    ) as socket:
        await socket.send_str("native-original-url-probe")
        message = await socket.receive(timeout=5)
        assert message.type == WSMsgType.TEXT
        assert message.data == "native-original-url-probe"
        rows = (await listener(rt))["rows"]
        assert len(rows) == 1
        (tmp_path / "native-ws-original-url.json").write_text(
            json.dumps(rows, indent=2)
        )
        headers = {key.lower(): value for key, value in rows[0]["headers"]}
        assert rows[0]["authenticated"] is True
        assert headers["x-qwenpaw-ingress-original-url"] == (
            "https://websocket.test:9443" + suffix
        )
