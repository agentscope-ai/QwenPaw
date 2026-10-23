"""Real private Voice HTTP/WS; only tunnel, Twilio REST and host RPC are doubles."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit
from xml.etree import ElementTree

import aiohttp
from yarl import URL
import pytest_asyncio
from multidict import MultiDict
from twilio.request_validator import RequestValidator

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/channel/voice"))
from qwenpaw_channel_voice import driver as driver_module
from qwenpaw_channel_voice.platform import VoicePlatform, TunnelInfo
from qwenpaw_channel_voice.runner_twilio_manager import VoiceWebhookSnapshot
from g2_shared_response_suite import Peer
from qwenpaw.channel_protocol.models import (
    IdentityParams,
    EventBatchParams,
    EventBatchAck,
    SendParams,
)
from qwenpaw.channel_protocol.shared_worker import DriverContext

AUTH = "independent-voice-signature-secret"
BINDING = {
    "route_query_key": "_qp_endpoint",
    "route_selector": "voice/private:scope",
    "host_port": 18433,
    "paths": ["/voice/incoming", "/voice/ws", "/voice/status-callback"],
    "bridge_token": "independent-private-bridge-token",
}


async def eventually(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.005)


class Tunnel:
    def __init__(self):
        self.ports, self.stops = [], 0

    async def start(self, port):
        self.ports.append(port)
        return TunnelInfo("https://voice.example", "wss://voice.example")

    async def stop(self):
        self.stops += 1


class Manager:
    def __init__(self):
        self.original = VoiceWebhookSnapshot(
            "https://old.example/incoming", "GET", "https://old.example/status", "GET"
        )
        self.current = self.original
        self.applied = []
        self.closed = 0

    async def fetch_voice_webhook(self, sid):
        assert sid == "PN-private"
        return self.current

    async def apply_voice_webhook(self, sid, snapshot):
        assert sid == "PN-private"
        self.applied.append(snapshot)
        self.current = snapshot

    async def close(self):
        self.closed += 1


class HostBoundary(Peer):
    """A frozen A3 binding contract input, not a real host forwarding service."""

    def __init__(
        self,
        *,
        forwarding=True,
        fail_update=False,
        fail_connected=False,
        lose_ack=False,
        block_events=None,
    ):
        super().__init__()
        self.forwarding, self.fail_update, self.fail_connected = (
            forwarding,
            fail_update,
            fail_connected,
        )
        self.lose_ack, self.block_events = lose_ack, block_events
        (
            self.state,
            self.events,
            self.batches,
            self.methods,
            self.notifications,
            self.calls,
        ) = ({}, [], [], {}, [], [])
        self.accepted = set()
        self.on_update = None

    def register_method(self, name, handler):
        self.methods[name] = handler

    async def notify(self, name, params):
        self.notifications.append((name, params))
        if self.fail_connected and params.get("platform_state") == "connected":
            raise RuntimeError("independent connected notification failure")

    async def call(self, name, params):
        if name.startswith("host.receipt."):
            return await super().call(name, params)
        self.calls.append((name, params))
        if name == "host.state.get":
            return {"value": self.state.get(params["key"])}
        if name == "host.state.put":
            self.state[params["key"]] = params["value"]
            return {"status": "stored"}
        if name == "event.batch":
            batch = EventBatchParams.from_mapping(params)
            self.batches.append(params)
            if self.block_events is not None:
                await self.block_events.wait()
            new = tuple(
                e.event_id for e in batch.events if e.event_id not in self.accepted
            )
            duplicate = tuple(
                e.event_id for e in batch.events if e.event_id in self.accepted
            )
            self.events.extend(
                e for e in batch.events if e.event_id not in self.accepted
            )
            self.accepted.update(new)
            if self.lose_ack and len(self.batches) == 1:
                raise TimeoutError("ACK lost after acceptance")
            return EventBatchAck(
                batch_id=batch.batch_id,
                accepted_event_ids=new,
                duplicate_event_ids=duplicate,
            ).to_mapping()
        if name.startswith("ingress.endpoint."):
            op = name.rsplit(".", 1)[1]
            if op == "update":
                if self.on_update:
                    self.on_update()
                if self.fail_update:
                    raise RuntimeError("independent endpoint ready ACK failure")
            result = {
                "status": {
                    "register": "registered",
                    "update": "updated",
                    "unregister": "unregistered",
                }[op],
                "generation": params["generation"],
            }
            if op != "unregister":
                result["readiness"] = params["readiness"]
            if op == "register" and self.forwarding:
                result["forwarding"] = dict(BINDING)
            return result
        raise AssertionError(name)


@pytest_asyncio.fixture
async def voice(monkeypatch):
    resources = []

    @asynccontextmanager
    async def create(
        *, start=True, platform_options=None, host_options=None, config=None
    ):
        manager, tunnel, peer = (
            Manager(),
            Tunnel(),
            HostBoundary(**(host_options or {})),
        )
        platform = VoicePlatform(
            tunnel_factory=lambda: tunnel,
            twilio_manager_factory=lambda *args: manager,
            **(platform_options or {}),
        )
        monkeypatch.setattr(driver_module, "VoicePlatform", lambda: platform)
        driver = driver_module.VoiceDriver()
        identity = IdentityParams("voice", "private-voice-" + str(len(resources)), 1)
        driver.bind(
            DriverContext(
                peer,
                identity,
                tuple(
                    json.loads(
                        (ROOT / "plugins/channel/voice/channel.json").read_text()
                    )["capabilities"]
                ),
            )
        )
        values = {
            "enabled": True,
            "twilio_account_sid": "AC-private",
            "twilio_auth_token": AUTH,
            "phone_number_sid": "PN-private",
            "welcome_greeting": "Hello & welcome",
            "language": "en-US",
        }
        values.update(config or {})
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3))
        r = SimpleNamespace(
            driver=driver,
            platform=platform,
            manager=manager,
            tunnel=tunnel,
            peer=peer,
            session=session,
            config=values,
        )
        resources.append(r)
        try:
            if start:
                await driver.start(values)
            yield r
        finally:
            if peer.block_events is not None:
                peer.block_events.set()
            if driver._platform is not None:
                await driver.stop()
            await session.close()

    yield create


def bridge_headers(original):
    return {
        "X-Qwenpaw-Ingress-Token": BINDING["bridge_token"],
        "X-Qwenpaw-Ingress-Original-URL": original,
    }


async def form_request(
    r,
    path="/voice/incoming",
    *,
    fields=None,
    suffix="?x=one%2Ftwo&x=three&_qp_endpoint=voice%2Fprivate%3Ascope",
    headers=None,
    signed_url=None,
):
    original = "https://voice.example" + path + suffix
    data = MultiDict(
        fields
        if fields is not None
        else [("CallSid", "CA-one"), ("From", "+15550001"), ("To", "+15550002")]
    )
    signed = RequestValidator(AUTH).compute_signature(signed_url or original, data)
    h = {**bridge_headers(original), "X-Twilio-Signature": signed, **(headers or {})}
    async with r.session.post(
        URL(
            "http://127.0.0.1:" + str(r.platform.listen_port) + path + suffix,
            encoded=True,
        ),
        data=data,
        headers=h,
    ) as response:
        return response.status, await response.text()


async def incoming(r, *, call="CA-one", caller="+15550001", callee="+15550002"):
    status, text = await form_request(
        r, fields=[("CallSid", call), ("From", caller), ("To", callee)]
    )
    assert status == 200, text
    relay = ElementTree.fromstring(text).find("./Connect/ConversationRelay")
    assert relay is not None
    return relay


async def connect(
    r, *, call="CA-one", caller="+15550001", callee="+15550002", setup=True
):
    relay = await incoming(r, call=call, caller=caller, callee=callee)
    parsed = urlsplit(relay.attrib["url"])
    target = parsed.path + "?" + parsed.query
    ws = await r.session.ws_connect(
        URL("http://127.0.0.1:" + str(r.platform.listen_port) + target, encoded=True),
        headers=bridge_headers(relay.attrib["url"]),
    )
    if setup:
        await ws.send_json(
            {"type": "setup", "callSid": call, "from": caller, "to": callee}
        )
        await eventually(lambda: call in r.platform._calls)
    return ws, relay


async def prompt(r, ws, text="same text"):
    previous = len(r.peer.events)
    await ws.send_json({"type": "prompt", "voicePrompt": text})
    await eventually(lambda: len(r.peer.events) > previous)
    return r.peer.events[-1]


async def send(r, event, parts, *, source="event", delivery="delivery-one"):
    return await r.driver._send(
        SendParams.from_mapping(
            {
                **r.driver._context.identity.to_mapping(),
                "delivery_id": delivery,
                "to_handle": event.response_handle,
                "operation": "message.create",
                "content_parts": parts,
                "content_source": source,
            }
        ),
        None,
    )
