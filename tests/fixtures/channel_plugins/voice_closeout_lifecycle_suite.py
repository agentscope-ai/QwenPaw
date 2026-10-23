"""Actual Voice Manager phone ownership, workspace/session and rollback."""

import json
import os
from urllib.parse import urlsplit
from xml.etree import ElementTree

import psutil
import pytest
from yarl import URL

from extension_process_suite import identity
from real_host_runtime import bind_real_runtime
from voice_closeout_support import (
    AUTH,
    fault_runtime,
    official_voice_source,
    signature,
    voice_external,
    voice_host,
    voice_host_guard,
    runtime,
)

__all__ = [
    "fault_runtime",
    "voice_external",
    "voice_host",
    "voice_host_guard",
    "runtime",
]


def settings(external, sid):
    return {
        "dependency_paths": (external.sdk,),
        "python_executable": external.python,
        "runtime_identity": external.identity,
        "twilio_account_sid": "AC-formal",
        "twilio_auth_token": AUTH,
        "phone_number_sid": sid,
    }


async def ready(rt):
    rt.channel = await rt.manager.get_channel("voice")
    assert rt.channel is not None and rt.channel.enabled
    rt.process = rt.channel.channel_process
    await rt.channel._wait_connected()
    return rt.process.health_snapshot()["pid"]


async def call(gateway, external, sid, call_sid):
    original = external.phones[sid]["voice_url"]
    parsed = urlsplit(original)
    fields = {"CallSid": call_sid, "From": "+15550001", "To": "+15550002"}
    headers = {"Host": parsed.netloc}
    async with gateway.client.post(
        URL(gateway.base + parsed.path + "?" + parsed.query, encoded=True),
        data=fields,
        headers={**headers, "X-Twilio-Signature": signature(original, fields)},
    ) as response:
        assert response.status == 200
        relay = ElementTree.fromstring(await response.text()).find(
            "./Connect/ConversationRelay"
        )
    assert relay is not None
    ws = urlsplit(relay.attrib["url"])
    return await gateway.client.ws_connect(
        URL(gateway.base + ws.path + "?" + ws.query, encoded=True),
        headers=headers,
    )


async def question(ws, rt, host, text, call_sid, *, setup=False):
    before = len(host.builds)
    if setup:
        await ws.send_json(
            {
                "type": "setup",
                "callSid": call_sid,
                "from": "+15550001",
                "to": "+15550002",
            }
        )
    await ws.send_json({"type": "prompt", "voicePrompt": text})
    assert await ws.receive_json(timeout=8) == {
        "type": "text",
        "token": "voice owned answer",
        "last": False,
    }
    assert await ws.receive_json(timeout=8) == {
        "type": "text",
        "token": "",
        "last": True,
    }
    assert await rt.ws.task_tracker.wait_all_done(timeout=8)
    assert len(host.builds) == before + 1
    assert host.builds[-1]["agent"] == "QwenPawAgent"
    assert host.builds[-1]["session_id"] == "voice:" + call_sid
    assert rt.ws.requests[-1].user_id == "+15550001"
    return {
        p: p.read_bytes()
        for p in (rt.ws.workspace_dir / "sessions").rglob("*.json")
    }


def tunnel_rows(external):
    return [
        json.loads(line)
        for line in external.tunnel_log.read_text().splitlines()
    ]


@pytest.mark.asyncio
async def test_distinct_sids_same_call_isolate_and_same_sid_has_no_effect(
    voice_host, voice_external, monkeypatch, tmp_path
):
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.config.config import Config

    gateway, external = voice_host, voice_external
    first = await gateway.runtime(
        "voice",
        source_factory=official_voice_source,
        workspace_name="voice-A",
        **settings(external, "PN-A"),
    )
    host_a = await bind_real_runtime(
        first, monkeypatch, reply="voice owned answer"
    )
    second = await gateway.runtime(
        "voice",
        existing_loader=first.loader,
        workspace_name="voice-B",
        **settings(external, "PN-B"),
    )
    host_b = await bind_real_runtime(
        second, monkeypatch, reply="voice owned answer"
    )
    pid_a, pid_b = await ready(first), await ready(second)
    assert len({pid_a, pid_b, os.getpid()}) == 3
    owners = first.loader.registry.runtime_owners
    leases = [r for r in owners.leases("voice") if r.key.kind == "channel"]
    assert len(leases) == 2
    assert {id(owners.resource(r)) for r in leases} == {
        id(first.channel),
        id(second.channel),
    }
    # Same account/different SID succeeded. Same SID is refused synchronously
    # by the actual reservation before a factory/worker/REST/tunnel can run.
    before = (
        len(external.calls),
        tunnel_rows(external),
        owners.leases("voice"),
    )
    denied_config = Config.model_validate(
        {
            "channels": {
                "voice": {
                    "enabled": True,
                    "twilio_account_sid": "AC-formal",
                    "twilio_auth_token": AUTH,
                    "phone_number_sid": "PN-A",
                }
            }
        }
    )
    denied = ChannelManager.from_config(
        first.ws.stream_query,
        denied_config,
        workspace_dir=tmp_path / "denied",
    )
    try:
        assert all(ch.channel != "voice" for ch in denied.channels)
        with pytest.raises(
            RuntimeError, match="RUNTIME_IDENTITY_ALREADY_OWNED"
        ):
            await denied.start_one("voice", denied_config)
        assert (
            len(external.calls),
            tunnel_rows(external),
            owners.leases("voice"),
        ) == before
    finally:
        await denied.stop_all()
    a = await call(gateway, external, "PN-A", "CA-shared")
    b = await call(gateway, external, "PN-B", "CA-shared")
    try:
        state_a = await question(
            a, first, host_a, "A only", "CA-shared", setup=True
        )
        state_b = await question(
            b, second, host_b, "B only", "CA-shared", setup=True
        )
        assert state_a and state_b and set(state_a).isdisjoint(state_b)
        assert all(
            b"A only" in v and b"B only" not in v for v in state_a.values()
        )
        assert all(
            b"B only" in v and b"A only" not in v for v in state_b.values()
        )
        assert len(first.ws.requests) == len(second.ws.requests) == 1
        receipt = await first.manager.stop_one("voice")
        assert receipt.stopped and receipt.exited and not receipt.forced
        assert not receipt.residual and not psutil.pid_exists(pid_a)
        assert psutil.pid_exists(pid_b)
        remaining = [
            r for r in owners.leases("voice") if r.key.kind == "channel"
        ]
        assert (
            len(remaining) == 1
            and owners.resource(remaining[0]) is second.channel
        )
        await question(b, second, host_b, "B survives", "CA-shared")
        assert len(host_a.builds) == 1 and len(host_b.builds) == 2
        assert {p: p.read_bytes() for p in state_a} == state_a
    finally:
        await a.close()
        await b.close()
    receipt = await second.manager.stop_one("voice")
    assert receipt.stopped and receipt.exited and not receipt.residual
    assert not psutil.pid_exists(pid_b) and not owners.leases("voice")
    assert all(not psutil.pid_exists(r["pid"]) for r in tunnel_rows(external))


@pytest.mark.asyncio
async def test_activated_failure_restores_voice_config_session_reply(
    voice_host, voice_external, monkeypatch, tmp_path
):
    gateway, external = voice_host, voice_external
    rt = await gateway.runtime(
        "voice",
        source_factory=official_voice_source,
        **settings(external, "PN-A"),
    )
    host = await bind_real_runtime(rt, monkeypatch, reply="voice owned answer")
    old_pid = await ready(rt)
    old_identity = identity(rt)
    old_reference = rt.channel.endpoint_service.resolve(forwarding=True)
    config = dict(rt.channel._launch_spec.config)
    ws = await call(gateway, external, "PN-A", "CA-rollback")
    try:
        sessions = await question(
            ws, rt, host, "before update", "CA-rollback", setup=True
        )
    finally:
        await ws.close()
    assert sessions
    original = {
        p.relative_to(rt.source): p.read_bytes()
        for p in rt.source.rglob("*")
        if p.is_file()
    }
    candidate = official_voice_source(tmp_path / "candidate", "voice")
    manifest_path = candidate / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = "99.0.0"
    manifest_path.write_text(json.dumps(manifest))
    witness = tmp_path / "activated-candidate.json"
    with (candidate / "qwenpaw_channel_voice/driver.py").open("a") as f:
        f.write(
            "\nimport json as _test_json\n"
            "import os as _test_os\n"
            "from pathlib import Path as _TestPath\n"
            "_RealVoiceDriver = VoiceDriver\n"
            "class VoiceDriver(_RealVoiceDriver):\n"
            "    async def _state_changed(self, state):\n"
            "        if state != 'connected':\n"
            "            await super()._state_changed(state)\n"
            "    async def start(self, config):\n"
            "        await super().start(config)\n"
            f"        witness = _TestPath({str(witness)!r})\n"
            "        witness.write_text(_test_json.dumps({\n"
            "            'pid': _test_os.getpid(),\n"
            "            'port': self._platform.listen_port,\n"
            "            'accepting': self._platform._accepting,\n"
            "        }))\n"
            "        raise RuntimeError('CONTROLLED_AFTER_ACTIVATION')\n"
        )
    before = len(tunnel_rows(external))
    updates = len([r for r in external.calls if r["method"] == "POST"])
    report = await rt.loader.lifecycle.reload("voice", new_source=candidate)
    assert not report.ok and report.errors
    assert witness.exists()
    observed = json.loads(witness.read_text())
    assert observed["accepting"] is True and observed["port"] > 0
    assert observed["pid"] != old_pid and not psutil.pid_exists(
        observed["pid"]
    )
    tunnels = tunnel_rows(external)
    assert len(tunnels) == before + 2
    assert not psutil.pid_exists(tunnels[before]["pid"])
    assert (
        len([r for r in external.calls if r["method"] == "POST"])
        == updates + 2
    )
    assert {
        p.relative_to(rt.source): p.read_bytes()
        for p in rt.source.rglob("*")
        if p.is_file()
    } == original
    assert {p: p.read_bytes() for p in sessions} == sessions
    pid = await ready(rt)
    assert pid != old_pid and not psutil.pid_exists(old_pid)
    assert identity(rt)["generation"] > old_identity["generation"]
    assert dict(rt.channel._launch_spec.config) == config
    assert not rt.channel.endpoint_service.is_current(
        old_reference, forwarding=True
    )
    ws = await call(gateway, external, "PN-A", "CA-rollback")
    try:
        await question(
            ws, rt, host, "after rollback", "CA-rollback", setup=True
        )
    finally:
        await ws.close()
    assert len(rt.ws.requests) == len(host.builds) == 2
    assert all(
        "before update" in p.read_text() and "after rollback" in p.read_text()
        for p in sessions
    )
    receipt = await rt.manager.stop_one("voice")
    assert receipt.stopped and receipt.exited and not receipt.residual
    assert not psutil.pid_exists(
        pid
    ) and not rt.loader.registry.runtime_owners.leases("voice")
    assert all(not psutil.pid_exists(r["pid"]) for r in tunnel_rows(external))
