"""Real MatrixDriver + nio, with only its host RPC endpoint modeled."""
import json
from pathlib import Path

import pytest_asyncio
from matrix_native_support import BOT, ROOM, hs
from qwenpaw_channel_matrix.driver import MatrixDriver
from g2_shared_response_suite import Peer
from qwenpaw.channel_protocol.models import IdentityParams, SendParams
from qwenpaw.channel_protocol.shared_worker import DriverContext


class HostBoundary(Peer):
    def __init__(self):
        super().__init__()
        self.methods, self.state = {}, {}
        self.batches, self.notifications = [], []
        self.admission = "accepted"

    def register_method(self, name, handler):
        self.methods[name] = handler

    async def call(self, method, params):
        if method.startswith("host.receipt."):
            return await super().call(method, params)
        if method == "host.state.get":
            return {"value": self.state.get(params["key"])}
        if method == "host.state.put":
            self.state[params["key"]] = json.loads(json.dumps(params["value"]))
            return {}
        assert method == "event.batch", method
        self.batches.append(params)
        return {"batch_id": params["batch_id"], self.admission + "_event_ids": [params["events"][0]["event_id"]]}

    async def notify(self, method, params):
        self.notifications.append((method, params))


@pytest_asyncio.fixture
async def native_driver(hs, tmp_path):
    driver, peer = MatrixDriver(), HostBoundary()
    identity = IdentityParams("matrix", "matrix-native-A", 1)
    descriptor = json.loads((Path(__file__).resolve().parents[3] / "plugins/channel/matrix/channel.json").read_text())
    driver.bind(DriverContext(peer, identity, descriptor["capabilities"]))
    try:
        await driver.start({"enabled": True, "homeserver": hs.url, "user_id": BOT,
                            "access_token": "explicit-token", "streaming_enabled": True,
                            "workspace_dir": str(tmp_path / "A"), "legacy_state_dir": str(tmp_path / "legacy")})
        assert driver._connected
        yield driver, peer, identity.to_mapping(), hs
    finally:
        await driver.stop()


async def open_route(peer, identity, room=ROOM):
    return (await peer.methods["channel.response.open"]({**identity, "to_handle": "matrix:" + room, "meta": {}}, None))["response_handle"]


async def send(peer, identity, handle, *, delivery="message-1", operation="message.create", parts=None, **extra):
    payload = {**identity, "to_handle": handle, "delivery_id": delivery,
               "operation": operation, **extra}
    if operation == "message.create":
        payload["content_parts"] = parts if parts is not None else [{"type": "text", "text": "hello"}]
    elif operation == "stream.start":
        payload.setdefault("sequence", 0)
        payload.setdefault("accumulated_text", "")
    params = SendParams.from_mapping(payload)
    return await peer.methods["channel.send"](params, None)
