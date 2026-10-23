"""Additional private native boundedness/fencing/cleanup controls."""

import asyncio
from urllib.parse import urlsplit
import aiohttp
import pytest
from yarl import URL
from voice_native_support import (
    voice,
    connect,
    prompt,
    send,
    incoming,
    form_request,
    bridge_headers,
    eventually,
)

pytestmark = pytest.mark.asyncio


async def test_connection_limit_releases_capacity_and_duplicate_sid_keeps_original(
    voice,
):
    async with voice(platform_options={"max_connections": 2}) as r:
        first, _ = await connect(r)
        original = r.platform._calls["CA-one"]
        duplicate, _ = await connect(r, setup=False)
        await duplicate.send_json(
            {
                "type": "setup",
                "callSid": "CA-one",
                "from": "+15550001",
                "to": "+15550002",
            }
        )
        frame = await duplicate.receive(timeout=2)
        assert frame.type == aiohttp.WSMsgType.CLOSE and frame.data == 1008
        assert r.platform._calls["CA-one"] is original
        await eventually(lambda: len(r.platform._connections) == 1)
        second, _ = await connect(r, call="CA-two")
        relay = await incoming(r, call="CA-three")
        parts = urlsplit(relay.attrib["url"])
        with pytest.raises(aiohttp.WSServerHandshakeError) as exc:
            await r.session.ws_connect(
                URL(
                    "http://127.0.0.1:"
                    + str(r.platform.listen_port)
                    + parts.path
                    + "?"
                    + parts.query,
                    encoded=True,
                ),
                headers=bridge_headers(relay.attrib["url"]),
            )
        assert exc.value.status == 503 and r.platform._connection_overload_total == 1
        await first.close()
        await eventually(lambda: len(r.platform._connections) == 1)
        third, _ = await connect(r, call="CA-three")
        assert len(r.platform._connections) == 2
        await second.close()
        await third.close()


async def test_native_default_queue32_overload_explicit_not_silent(voice):
    release = asyncio.Event()
    async with voice(host_options={"block_events": release}) as r:
        ws, _ = await connect(r)
        connection = r.platform._calls["CA-one"]
        assert connection.queue.maxsize == 32
        assert r.platform._max_connections == 64 and r.platform._max_tokens == 100
        await ws.send_json({"type": "prompt", "voicePrompt": "blocked"})
        await eventually(lambda: bool(r.peer.batches))
        for i in range(33):
            await ws.send_json({"type": "prompt", "voicePrompt": str(i)})
        frame = await ws.receive(timeout=2)
        assert frame.type == aiohttp.WSMsgType.CLOSE and frame.data == 1013
        assert r.platform._runner_backpressure_total == 1
        assert connection.queue.qsize() <= 32
        release.set()


async def test_terminal_status_fences_old_binding_without_touching_next_call(voice):
    async with voice() as r:
        ws, _ = await connect(r)
        old = await prompt(r, ws)
        assert (
            await form_request(
                r,
                "/voice/status-callback",
                fields=[("CallSid", "CA-one"), ("CallStatus", "completed")],
            )
        )[0] == 204
        frame = await ws.receive(timeout=2)
        assert frame.type == aiohttp.WSMsgType.CLOSE
        await eventually(lambda: "CA-one" not in r.platform._calls)
        newws, _ = await connect(r)
        new = await prompt(r, newws)
        assert new.response_handle != old.response_handle
        failed = await send(r, old, [{"type": "text", "text": "old"}], source="direct")
        assert failed["state"] == "failed" and failed["reason_code"] == "CALL_CLOSED"
        result = await send(
            r,
            new,
            [{"type": "text", "text": "new"}],
            source="direct",
            delivery="new-delivery",
        )
        assert result["state"] == "acknowledged"
        assert await newws.receive_json(timeout=2) == {
            "type": "text",
            "token": "new",
            "last": True,
        }
        assert (
            await form_request(
                r,
                "/voice/status-callback",
                fields=[("CallSid", "CA-unknown"), ("CallStatus", "completed")],
            )
        )[0] == 204
        assert r.platform._unknown_status_total == 1
        await newws.close()


async def test_stop_end_once_awaits_resources_and_retains_failed_tunnel_for_retry(
    voice, monkeypatch
):
    async with voice() as r:
        ws, _ = await connect(r)
        await prompt(r, ws)
        connection = r.platform._calls["CA-one"]
        worker = connection.worker
        original = r.tunnel.stop
        calls = []

        async def stop_once_failed():
            calls.append("stop")
            if len(calls) == 1:
                raise RuntimeError("independent tunnel stop failure")
            await original()

        monkeypatch.setattr(r.tunnel, "stop", stop_once_failed)
        with pytest.raises(RuntimeError, match="VOICE_STOP_INCOMPLETE"):
            await r.driver.stop()
        assert r.driver._platform is r.platform and r.platform._tunnel is r.tunnel
        assert not r.platform.cleanup_complete and connection.end_attempted
        assert await ws.receive_json(timeout=2) == {"type": "end"}
        assert (await ws.receive(timeout=2)).type == aiohttp.WSMsgType.CLOSE
        assert worker.done()
        await r.driver.stop()
        assert r.platform.cleanup_complete and r.driver._platform is None
        assert calls == ["stop", "stop"] and r.manager.closed == 1
        assert (
            not r.platform._connections
            and not r.platform._bindings
            and not r.platform._admissions
        )


async def test_original_url_explicit_port_and_duplicate_form_fields(voice):
    from voice_native_support import AUTH, BINDING
    from multidict import MultiDict
    from twilio.request_validator import RequestValidator

    async with voice() as r:
        target = "/voice/incoming?_qp_endpoint=voice%2Fprivate%3Ascope&a=%2F"
        original = "https://voice.example:8443" + target
        fields = MultiDict(
            [
                ("CallSid", "CA-multi"),
                ("From", "+15550001"),
                ("Tag", "one"),
                ("Tag", "two"),
            ]
        )
        headers = bridge_headers(original)
        headers["X-Twilio-Signature"] = RequestValidator(AUTH).compute_signature(
            original, fields
        )
        async with r.session.post(
            URL(
                "http://127.0.0.1:" + str(r.platform.listen_port) + target, encoded=True
            ),
            data=fields,
            headers=headers,
        ) as response:
            assert response.status == 200
            assert "ConversationRelay" in await response.text()
        assert len(r.platform._tokens) == 1


@pytest.mark.parametrize(
    "payload,code",
    [("not-json", 1003), ('{"type":"prompt","voicePrompt":"before setup"}', 1008)],
)
async def test_invalid_or_premature_native_frames_are_rejected(voice, payload, code):
    async with voice() as r:
        ws, _ = await connect(r, setup=False)
        await ws.send_str(payload)
        frame = await ws.receive(timeout=2)
        assert frame.type == aiohttp.WSMsgType.CLOSE and frame.data == code
        assert not r.peer.events


async def test_token_mint_cannot_cross_stop_accepting_fence(voice, monkeypatch):
    async with voice() as r:
        entered, release = asyncio.Event(), asyncio.Event()
        original = r.platform._mint_token

        async def gated(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(r.platform, "_mint_token", gated)
        task = asyncio.create_task(form_request(r))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await r.platform.stop_accepting()
            release.set()
            assert (await task)[0] == 503
            assert not r.platform._tokens and not r.platform._accepting
        finally:
            release.set()
            await task


@pytest.mark.parametrize(
    "stage,state,reason",
    [
        ("ownership", "rollback_unknown", "WEBHOOK_OWNERSHIP_UNKNOWN"),
        ("restore", "rollback_failed", "WEBHOOK_RESTORE_FAILED"),
    ],
)
async def test_rollback_uncertainty_retains_owner_until_successful_retry(
    voice, monkeypatch, stage, state, reason
):
    async with voice(start=False, host_options={"fail_update": True}) as r:
        failing = [False]
        fetch = r.manager.fetch_voice_webhook
        apply = r.manager.apply_voice_webhook

        async def fetch_boundary(sid):
            if failing[0] and stage == "ownership":
                raise RuntimeError("independent unknown rollback owner")
            return await fetch(sid)

        async def apply_boundary(sid, snapshot):
            if failing[0] and stage == "restore" and snapshot == r.manager.original:
                raise RuntimeError("independent restore failed")
            await apply(sid, snapshot)

        monkeypatch.setattr(r.manager, "fetch_voice_webhook", fetch_boundary)
        monkeypatch.setattr(r.manager, "apply_voice_webhook", apply_boundary)
        r.peer.on_update = lambda: failing.__setitem__(0, True)
        try:
            with pytest.raises(RuntimeError):
                await r.driver.start(r.config)
            health = r.platform.health_snapshot()
            assert health["webhook_transaction_state"] == state
            assert health["webhook_rollback_reason"] == reason
            assert not health["accepting"] and not r.platform.cleanup_complete
            assert (
                r.driver._platform is r.platform
                and r.platform._twilio_manager is r.manager
            )
            assert r.manager.closed == 0
            assert r.platform.listen_port is None
        finally:
            failing[0] = False
        await r.driver.stop()
        assert r.platform.cleanup_complete and r.manager.current == r.manager.original
        assert r.manager.closed == 1
