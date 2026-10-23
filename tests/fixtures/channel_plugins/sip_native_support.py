"""External SDK doubles only; private platform/ASR/TTS/shared driver stay real."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/channel/sip"))
from qwenpaw_channel_sip.driver import SIPDriver
from g2_shared_response_suite import Peer
from qwenpaw.channel_protocol.models import (
    IdentityParams,
    SendParams,
    EventBatchParams,
)
from qwenpaw.channel_protocol.shared_worker import DriverContext
from sip_artifact_suite import CONFIG_DEFAULTS


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


from sip_vendor_boundary import Vendor


@pytest.fixture
def vendor(monkeypatch):
    boundary = Vendor()
    for name, value in boundary.modules().items():
        monkeypatch.setitem(sys.modules, name, value)
    yield boundary
    boundary.fail_stop = False
    if boundary.tts_release:
        boundary.tts_release.set()


class HostBoundary(Peer):
    """RPC observation boundary; not a Core Agent or registry substitute."""

    def __init__(self):
        super().__init__()
        self.methods, self.state, self.batches, self.notifications = (
            {},
            {},
            [],
            [],
        )
        self.reject = 0
        self.rejections = []

    def register_method(self, method, handler):
        self.methods[method] = handler

    async def notify(self, method, params):
        self.notifications.append((method, params))

    async def call(self, method, params):
        if method.startswith("host.receipt."):
            return await super().call(method, params)
        if method == "host.state.get":
            return {"value": self.state.get(params["key"])}
        if method == "host.state.put":
            self.state[params["key"]] = json.loads(json.dumps(params["value"]))
            return {}
        assert method == "event.batch", method
        parsed = EventBatchParams.from_mapping(params)
        if parsed.invalid_events:
            self.rejections.extend(parsed.invalid_events)
            return {
                "batch_id": parsed.batch_id,
                "accepted_event_ids": [],
                "rejected_events": [
                    row.to_mapping() for row in parsed.invalid_events
                ],
            }
        self.batches.append(json.loads(json.dumps(params)))
        if self.reject:
            self.reject -= 1
            return {
                "batch_id": params["batch_id"],
                "accepted_event_ids": [],
                "rejected_event_ids": [
                    event["event_id"] for event in params["events"]
                ],
            }
        return {
            "batch_id": params["batch_id"],
            "accepted_event_ids": [
                event["event_id"] for event in params["events"]
            ],
        }


@asynccontextmanager
async def running(vendor, mode="dev", **overrides):
    driver, peer = SIPDriver(), HostBoundary()
    identity = IdentityParams("sip", "sip-native", 1)
    capabilities = tuple(
        json.loads((ROOT / "plugins/channel/sip/channel.json").read_text())[
            "capabilities"
        ]
    )
    driver.bind(DriverContext(peer, identity, capabilities))
    config = {
        **CONFIG_DEFAULTS,
        "enabled": True,
        "sip_server": "registrar.test",
        "sip_port": 15061,
        "sip_mode": mode,
        "dashscope_api_key": "test-key",
        "livekit_url": "wss://livekit.test",
        "livekit_api_key": "key",
        "livekit_api_secret": "secret",
        "welcome_greeting": "",
        **overrides,
    }
    try:
        await driver.start(config)
        await until(lambda: driver._connected)
        yield driver, peer, identity.to_mapping()
    finally:
        vendor.fail_stop = False
        if vendor.tts_release:
            vendor.tts_release.set()
        await driver.stop()


async def incoming(vendor, mode, sender="sip:alice@example.test"):
    if mode == "dev":
        call = vendor.phones[-1].incoming(sender=sender)
    else:
        call = vendor.rooms[-1].participant(sender)
    await until(lambda: vendor.asrs)
    return call


def send_params(identity, event, delivery="delivery-1", text="spoken answer"):
    return SendParams.from_mapping(
        {
            **identity,
            "delivery_id": delivery,
            "to_handle": event["response_handle"],
            "operation": "message.create",
            "content_parts": [{"type": "text", "text": text}],
        }
    )
