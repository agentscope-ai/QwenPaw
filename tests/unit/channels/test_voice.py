# -*- coding: utf-8 -*-
"""Signed Twilio call admission and real ConversationRelay turn lifecycle."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import urlsplit
from xml.etree import ElementTree
import aiohttp
from multidict import MultiDict
from twilio.request_validator import RequestValidator
from yarl import URL
import pytest
import pytest_asyncio
from qwenpaw.channel_protocol.models import (
    InboundEvent,
    SendParams,
    ResponseFinishParams,
)
from tests.channel_support.driver import bind, module

VoicePlatform = module("voice", "platform").VoicePlatform
TunnelInfo = module("voice", "platform").TunnelInfo
VoiceWebhookSnapshot = module(
    "voice",
    "runner_twilio_manager",
).VoiceWebhookSnapshot
AUTH = "independent-voice-signature-secret"
BINDING = {
    "route_query_key": "_qp_endpoint",
    "route_selector": "voice/private:scope",
    "host_port": 18433,
    "paths": ["/voice/incoming", "/voice/ws", "/voice/status-callback"],
    "bridge_token": "private-bridge-token",
}
pytestmark = pytest.mark.asyncio


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
            "https://old.example/incoming",
            "GET",
            "https://old.example/status",
            "GET",
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
        else [
            ("CallSid", "CA-one"),
            ("From", "+15550001"),
            ("To", "+15550002"),
        ],
    )
    signed = RequestValidator(AUTH).compute_signature(
        signed_url or original,
        data,
    )
    h = {
        **bridge_headers(original),
        "X-Twilio-Signature": signed,
        **(headers or {}),
    }
    async with r.session.post(
        URL(
            "http://127.0.0.1:" + str(r.platform.listen_port) + path + suffix,
            encoded=True,
        ),
        data=data,
        headers=h,
    ) as response:
        return response.status, await response.text()


async def incoming(
    r,
    *,
    call="CA-one",
    caller="+15550001",
    callee="+15550002",
):
    status, text = await form_request(
        r,
        fields=[("CallSid", call), ("From", caller), ("To", callee)],
    )
    assert status == 200, text
    relay = ElementTree.fromstring(text).find("./Connect/ConversationRelay")
    assert relay is not None
    return relay


async def connect(
    r,
    *,
    call="CA-one",
    caller="+15550001",
    callee="+15550002",
    setup=True,
):
    relay = await incoming(r, call=call, caller=caller, callee=callee)
    parsed = urlsplit(relay.attrib["url"])
    target = parsed.path + "?" + parsed.query
    ws = await r.session.ws_connect(
        URL(
            "http://127.0.0.1:" + str(r.platform.listen_port) + target,
            encoded=True,
        ),
        headers=bridge_headers(relay.attrib["url"]),
    )
    if setup:
        await ws.send_json(
            {"type": "setup", "callSid": call, "from": caller, "to": callee},
        )
        await eventually(lambda: call in r.platform._calls)
    return ws, relay


async def prompt(r, ws, text="same text"):
    previous = len(r.peer.batches)
    await ws.send_json({"type": "prompt", "voicePrompt": text})
    await eventually(lambda: len(r.peer.batches) > previous)
    return InboundEvent.from_mapping(r.peer.batches[-1]["events"][0])


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
            },
        ),
        None,
    )


@pytest_asyncio.fixture
async def voice(monkeypatch, tmp_path):
    @asynccontextmanager
    async def create():
        manager, tunnel = Manager(), Tunnel()
        platform = VoicePlatform(
            tunnel_factory=lambda: tunnel,
            twilio_manager_factory=lambda *args: manager,
        )
        driver_module = module("voice")
        monkeypatch.setattr(driver_module, "VoicePlatform", lambda: platform)
        driver = driver_module.VoiceDriver()
        peer, identity = bind("voice", driver, tmp_path)
        call = peer.call

        async def forwarding(name, params):
            result = await call(name, params)
            if name == "ingress.endpoint.register":
                result["forwarding"] = dict(BINDING)
            return result

        peer.call = forwarding
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3))
        r = SimpleNamespace(
            driver=driver,
            platform=platform,
            manager=manager,
            tunnel=tunnel,
            peer=peer,
            session=session,
        )
        try:
            await driver.start(
                {
                    "enabled": True,
                    "twilio_account_sid": "AC-private",
                    "twilio_auth_token": AUTH,
                    "phone_number_sid": "PN-private",
                    "welcome_greeting": "Hello & welcome",
                    "language": "en-US",
                },
            )
            yield r
        finally:
            await driver.stop()
            await session.close()

    yield create


async def test_signed_full_original_query_twiml_and_committed_cleanup(voice):
    async with voice() as r:
        relay = await incoming(r)
        assert relay.attrib["welcomeGreeting"] == "Hello & welcome"
        assert relay.attrib["ttsProvider"] == "google"
        assert relay.attrib["voice"] == "en-US-Journey-D"
        assert relay.attrib["transcriptionProvider"] == "deepgram"
        assert relay.attrib["language"] == "en-US"
        assert r.tunnel.ports == [BINDING["host_port"]]
        committed = r.manager.current
        assert committed.voice_url == (
            "https://voice.example/voice/incoming?"
            "_qp_endpoint=voice%2Fprivate%3Ascope"
        )
        assert committed.status_callback.endswith(
            "/voice/status-callback?_qp_endpoint=voice%2Fprivate%3Ascope",
        )
        await r.driver.stop()
        assert r.manager.current == committed and len(r.manager.applied) == 1
        assert r.manager.closed == 1 and r.tunnel.stops == 1
        assert r.platform.cleanup_complete and r.platform.listen_port is None
        assert not r.platform._tokens and not r.platform._connections


async def test_completed_fragments_and_finish_do_not_hang_up(voice):
    async with voice() as r:
        ws, _ = await connect(r)
        event = await prompt(r, ws)
        result = await send(
            r,
            event,
            [
                {"type": "text", "text": "  alpha  ", "role": "message"},
                {"type": "text", "text": "  no  ", "role": "refusal"},
            ],
        )
        assert result["state"] == "acknowledged"
        assert await ws.receive_json(timeout=2) == {
            "type": "text",
            "token": "alpha no",
            "last": False,
        }
        assert await ws.receive_json(timeout=2) == {
            "type": "text",
            "token": "",
            "last": True,
        }
        await r.driver._finish(
            ResponseFinishParams.from_mapping(
                {
                    **r.driver._context.identity.to_mapping(),
                    "response_handle": event.response_handle,
                    "outcome": "completed",
                },
            ),
            None,
        )
        assert not ws.closed and "CA-one" in r.platform._calls
        next_event = await prompt(r, ws, "next turn")
        result = await send(
            r,
            next_event,
            [{"type": "text", "text": "  direct  "}],
            source="direct",
            delivery="next",
        )
        assert result["state"] == "acknowledged"
        assert await ws.receive_json(timeout=2) == {
            "type": "text",
            "token": "  direct  ",
            "last": True,
        }
        await ws.close()


async def test_transcription_maps_caller_and_new_turn(voice):
    async with voice() as r:
        ws, _ = await connect(r)
        first = await prompt(r, ws, "first question")
        second = await prompt(r, ws, "second question")
        assert first.sender_id == first.acl_sender_id == "+15550001"
        assert (
            first.conversation["id"]
            == second.conversation["id"]
            == "voice:CA-one"
        )
        assert first.content_parts == (
            {"type": "text", "text": "first question"},
        )
        assert first.event_id != second.event_id
        assert first.response_handle != second.response_handle
        await ws.close()
        await eventually(lambda: not r.platform._calls)
        assert not r.platform._connections


async def test_status_callback_cleans_hung_up_call(voice):
    async with voice() as r:
        ws, _ = await connect(r)
        await prompt(r, ws)
        status, _ = await form_request(
            r,
            "/voice/status-callback",
            fields=[("CallSid", "CA-one"), ("CallStatus", "completed")],
        )
        assert status == 204
        await eventually(lambda: not r.platform._calls)
        assert (await ws.receive(timeout=2)).type == aiohttp.WSMsgType.CLOSE


async def test_stop_cleans_live_socket_and_listener(voice):
    async with voice() as r:
        ws, _ = await connect(r)
        await prompt(r, ws)
        await r.driver.stop()
        assert r.platform.cleanup_complete and r.platform.listen_port is None
        assert not r.platform._calls and not r.platform._connections
        assert r.tunnel.stops == 1 and r.manager.closed == 1
        await ws.close()
