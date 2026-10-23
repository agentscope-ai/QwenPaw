"""Unmodified official Voice worker through production A3/Router/Core/Agent."""

import base64
import json
import os
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

import aiohttp
import psutil
import pytest
from yarl import URL

from extension_process_suite import eventually
from real_host_runtime import bind_real_runtime
from voice_closeout_support import (
    AUTH,
    fault_runtime,
    PUBLIC,
    official_voice_source,
    signature,
    voice_external,
    voice_host,
    voice_host_guard,
    runtime,
)

__all__ = [
    "voice_external",
    "voice_host",
    "voice_host_guard",
    "runtime",
    "fault_runtime",
]


@pytest.mark.asyncio
async def test_official_voice_host_a3_signature_token_actual_agent_and_session(
    voice_host, voice_external, monkeypatch
):
    from qwenpaw.runtime._state_utils import StateProxy

    gateway = voice_host
    external = voice_external
    rt = await gateway.runtime(
        "voice",
        source_factory=official_voice_source,
        dependency_paths=(external.sdk,),
        python_executable=external.python,
        runtime_identity=external.identity,
        twilio_account_sid="AC-formal",
        twilio_auth_token=AUTH,
        phone_number_sid="PN-formal",
        welcome_greeting="Formal welcome",
    )
    host = await bind_real_runtime(
        rt, monkeypatch, reply="actual Voice answer"
    )
    await rt.channel._wait_connected()
    pid = rt.process.health_snapshot()["pid"]
    assert pid and pid != os.getpid()
    reference = rt.channel.endpoint_service.resolve(forwarding=True)
    assert reference is not None
    assert reference.plugin_id == "voice"
    assert reference.workspace_id == str(rt.ws.workspace_dir.resolve())
    assert reference.endpoint.public_base_url == PUBLIC
    assert reference.endpoint.protocol == "http+ws"
    tunnels = [
        json.loads(line)
        for line in external.tunnel_log.read_text().splitlines()
    ]
    assert len(tunnels) == 2
    assert all(
        row["args"] == ["tunnel", "--url", f"http://localhost:{gateway.port}"]
        for row in tunnels
    )
    assert not psutil.pid_exists(tunnels[0]["pid"])
    assert psutil.pid_exists(tunnels[-1]["pid"])
    assert external.current["voice_url"].startswith(
        PUBLIC + "/voice/incoming?"
    )
    assert external.current["status_callback"].startswith(
        PUBLIC + "/voice/status-callback?"
    )
    selector = parse_qs(urlsplit(external.current["voice_url"]).query)
    assert len(selector["_qp_endpoint"]) == 1
    suffix = "?" + urlsplit(external.current["voice_url"]).query
    original_url = PUBLIC + "/voice/incoming" + suffix
    target = gateway.base + "/voice/incoming" + suffix
    fields = {"CallSid": "CA-formal", "From": "+15550001", "To": "+15550002"}
    headers = {"Host": urlsplit(PUBLIC).netloc}
    async with gateway.client.post(
        URL(target, encoded=True),
        data=fields,
        headers={**headers, "X-Twilio-Signature": "invalid"},
    ) as response:
        assert response.status == 403
    async with gateway.client.post(
        URL(target, encoded=True),
        data=fields,
        headers={
            **headers,
            "X-Twilio-Signature": signature(original_url, fields),
        },
    ) as response:
        assert response.status == 200
        assert response.content_type == "application/xml"
        xml = await response.text()
    relay = ElementTree.fromstring(xml).find("./Connect/ConversationRelay")
    assert (
        relay is not None
        and relay.attrib["welcomeGreeting"] == "Formal welcome"
    )
    parsed = urlsplit(relay.attrib["url"])
    assert parsed.scheme == "wss" and parsed.netloc == urlsplit(PUBLIC).netloc
    params = parse_qs(parsed.query)
    assert params["_qp_endpoint"] == selector["_qp_endpoint"]
    assert len(params["token"]) == 1 and params["token"][0]
    ws_url = URL(gateway.base + parsed.path + "?" + parsed.query, encoded=True)
    async with gateway.client.ws_connect(ws_url, headers=headers) as ws:
        # Upstream must admit once before host accepts; the same exact token
        # cannot open a second real host→worker connection.
        with pytest.raises(aiohttp.WSServerHandshakeError) as duplicate:
            await gateway.client.ws_connect(ws_url, headers=headers)
        assert duplicate.value.status == 403
        await ws.send_json(
            {
                "type": "setup",
                "callSid": "CA-formal",
                "from": fields["From"],
                "to": fields["To"],
            }
        )
        await ws.send_json(
            {"type": "prompt", "voicePrompt": "voice formal question"}
        )
        assert await ws.receive_json(timeout=8) == {
            "type": "text",
            "token": "actual Voice answer",
            "last": False,
        }
        assert await ws.receive_json(timeout=8) == {
            "type": "text",
            "token": "",
            "last": True,
        }
        assert await rt.ws.task_tracker.wait_all_done(timeout=8)
        assert len(rt.ws.requests) == len(host.calls) == len(host.builds) == 1
        request = rt.ws.requests[0]
        assert request.channel == "voice" and request.user_id == fields["From"]
        assert request.session_id == "voice:CA-formal"
        assert host.builds[0]["session_id"] == "voice:CA-formal"
        assert request.channel_meta["connection_id"]
        assert host.calls[0]["pid"] == os.getpid()
        assert host.builds[0]["agent"] == "QwenPawAgent"
        saved = StateProxy()
        await host.session.load_session_state(
            session_id="voice:CA-formal",
            user_id=fields["From"],
            channel="voice",
            agent=saved,
        )
        stored = json.dumps(saved.data, ensure_ascii=False)
        assert (
            "voice formal question" in stored
            and "actual Voice answer" in stored
        )
    expected_auth = (
        "Basic " + base64.b64encode(("AC-formal:" + AUTH).encode()).decode()
    )
    assert external.calls and all(
        row["auth"] == expected_auth for row in external.calls
    )
    receipt = await rt.manager.stop_one("voice")
    assert receipt.stopped and receipt.exited and not receipt.forced
    assert receipt.residual == () and not psutil.pid_exists(pid)
    assert not psutil.pid_exists(tunnels[-1]["pid"])
    assert rt.channel.endpoint_service.resolve(forwarding=True) is None
    assert not rt.loader.registry.runtime_owners.leases("voice")
