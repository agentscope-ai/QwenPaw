"""Native private listener/WS controls; no actual Core or public forwarding."""

import asyncio
from urllib.parse import urlsplit

import aiohttp
from yarl import URL
import pytest
from qwenpaw.channel_protocol.models import ResponseFinishParams
from voice_native_support import (
    voice,
    BINDING,
    bridge_headers,
    form_request,
    incoming,
    connect,
    prompt,
    send,
    eventually,
    VoiceWebhookSnapshot,
)

pytestmark = pytest.mark.asyncio


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
        assert (
            committed.voice_url
            == "https://voice.example/voice/incoming?_qp_endpoint=voice%2Fprivate%3Ascope"
        )
        assert committed.status_callback.endswith(
            "/voice/status-callback?_qp_endpoint=voice%2Fprivate%3Ascope"
        )
        await r.driver.stop()
        assert r.manager.current == committed and len(r.manager.applied) == 1
        assert r.manager.closed == 1 and r.tunnel.stops == 1
        assert r.platform.cleanup_complete and r.platform.listen_port is None
        assert not r.platform._tokens and not r.platform._connections


@pytest.mark.parametrize(
    "change", ["signature", "original-query", "bridge", "selector", "forwarded-header"]
)
async def test_untrusted_or_mismatched_forwarding_rejected(voice, change):
    async with voice() as r:
        kwargs = {}
        if change == "signature":
            kwargs["headers"] = {"X-Twilio-Signature": "wrong"}
        if change == "original-query":
            kwargs["signed_url"] = "https://voice.example/voice/incoming"
        if change == "bridge":
            kwargs["headers"] = {"X-Qwenpaw-Ingress-Token": "wrong"}
        if change == "selector":
            kwargs["suffix"] = "?_qp_endpoint=another"
        if change == "forwarded-header":
            kwargs["headers"] = {
                "X-Qwenpaw-Ingress-Original-URL": "",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "voice.example",
            }
        assert (await form_request(r, **kwargs))[0] == 403
        assert not r.platform._tokens


async def test_token_atomic_single_use_expiry_and_capacity(voice):
    now = [10.0]
    async with voice(
        platform_options={"clock": lambda: now[0], "token_ttl_s": 1.0, "max_tokens": 2}
    ) as r:
        relay = await incoming(r)
        url = relay.attrib["url"]
        parts = urlsplit(url)
        local = (
            "http://127.0.0.1:"
            + str(r.platform.listen_port)
            + parts.path
            + "?"
            + parts.query
        )

        async def attempt():
            try:
                ws = await r.session.ws_connect(
                    URL(local, encoded=True), headers=bridge_headers(url)
                )
            except aiohttp.WSServerHandshakeError as exc:
                return exc.status
            await ws.close()
            return 101

        assert sorted(await asyncio.gather(attempt(), attempt())) == [101, 403]
        expired = await incoming(r, call="CA-expired")
        now[0] = 12.0
        parts = urlsplit(expired.attrib["url"])
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
                headers=bridge_headers(expired.attrib["url"]),
            )
        assert exc.value.status == 403
        for i in range(3):
            await incoming(r, call="CA-cap-" + str(i))
        assert len(r.platform._tokens) == 2


@pytest.mark.parametrize("change", ["callSid", "from", "to"])
async def test_signed_identity_must_match_setup(voice, change):
    async with voice() as r:
        ws, _ = await connect(r, setup=False)
        setup = {
            "type": "setup",
            "callSid": "CA-one",
            "from": "+15550001",
            "to": "+15550002",
        }
        setup[change] = "different"
        await ws.send_json(setup)
        frame = await ws.receive(timeout=2)
        assert frame.type == aiohttp.WSMsgType.CLOSE and frame.data == 1008
        assert not r.peer.events and not r.platform._calls


async def test_calls_turns_ack_retry_and_phone_acl_are_isolated(voice):
    async with voice(host_options={"lose_ack": True}) as r:
        ws, _ = await connect(r)
        first = await prompt(r, ws)
        await eventually(lambda: len(r.peer.batches) == 2)
        assert r.peer.batches[0] == r.peer.batches[1]
        second = await prompt(r, ws)
        other, _ = await connect(r, call="CA-two", caller="+15550003")
        third = await prompt(r, other)
        assert len({e.event_id for e in [first, second, third]}) == 3
        assert len({e.response_handle for e in [first, second, third]}) == 3
        assert first.sender_id == first.acl_sender_id == "+15550001"
        assert first.conversation["id"] == second.conversation["id"] == "voice:CA-one"
        assert (
            third.conversation["id"] == "voice:CA-two"
            and third.acl_sender_id == "+15550003"
        )
        assert (
            first.metadata["connection_id"]
            == second.metadata["connection_id"]
            != third.metadata["connection_id"]
        )
        assert first.metadata["turn_id"] != second.metadata["turn_id"]
        await ws.close()
        await other.close()


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
                }
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


@pytest.mark.parametrize("role", ["reasoning", "rendered"])
async def test_legacy_completed_text_all_message_types_remains_speakable(voice, role):
    # Legacy relay selects TEXT/REFUSAL from every completed message. This
    # exact compatibility expectation intentionally exposes the known gap.
    async with voice() as r:
        ws, _ = await connect(r)
        event = await prompt(r, ws)
        result = await send(
            r, event, [{"type": "text", "text": "  original text  ", "role": role}]
        )
        assert result["state"] == "acknowledged", result
        assert await ws.receive_json(timeout=2) == {
            "type": "text",
            "token": "original text",
            "last": False,
        }
        assert await ws.receive_json(timeout=2) == {
            "type": "text",
            "token": "",
            "last": True,
        }
        await ws.close()


async def test_legacy_empty_caller_prompt_still_reaches_admission(voice):
    async with voice() as r:
        ws, _ = await connect(r, caller="")
        await ws.send_json({"type": "prompt", "voicePrompt": "anonymous caller"})
        try:
            await eventually(lambda: bool(r.peer.events))
        except TimeoutError:
            pytest.fail(
                "Legacy empty caller was rejected instead of reaching event admission"
            )
        assert r.peer.events[0].content_parts == (
            {"type": "text", "text": "anonymous caller"},
        )
        await ws.close()


@pytest.mark.parametrize("external_change", [False, True])
async def test_failed_ready_ack_rolls_back_only_still_owned_webhook(
    voice, external_change
):
    async with voice(start=False, host_options={"fail_update": True}) as r:
        changed = VoiceWebhookSnapshot("https://user.example/new")
        if external_change:
            r.peer.on_update = lambda: setattr(r.manager, "current", changed)
        with pytest.raises(RuntimeError, match="endpoint ready ACK failure"):
            await r.driver.start(r.config)
        assert r.manager.current == (changed if external_change else r.manager.original)
        assert len(r.manager.applied) == (1 if external_change else 2)
        assert r.platform.cleanup_complete and r.platform.listen_port is None
        assert r.manager.closed == 1 and r.tunnel.stops == 1


async def test_failed_connected_notification_still_rolls_back(voice):
    async with voice(start=False, host_options={"fail_connected": True}) as r:
        with pytest.raises(RuntimeError, match="connected notification"):
            await r.driver.start(r.config)
        assert r.manager.current == r.manager.original
        assert r.platform.cleanup_complete and not r.platform._accepting


async def test_a1_only_ack_fails_before_tunnel_or_webhook_effect(voice):
    async with voice(start=False, host_options={"forwarding": False}) as r:
        with pytest.raises(RuntimeError, match="VOICE_HOST_FORWARDING_UNAVAILABLE"):
            await r.driver.start(r.config)
        assert not r.tunnel.ports and not r.manager.applied
        assert r.platform.cleanup_complete and r.platform.listen_port is None


async def test_turn_capacity_closes_only_affected_call(voice):
    async with voice() as r:
        ws, _ = await connect(r)
        for _ in range(8):
            await prompt(r, ws)
        other, _ = await connect(r, call="CA-other")
        await ws.send_json({"type": "prompt", "voicePrompt": "over capacity"})
        frame = await ws.receive(timeout=2)
        assert frame.type == aiohttp.WSMsgType.CLOSE and frame.data == 1013
        assert len(r.peer.events) == 8
        event = await prompt(r, other)
        assert event.conversation["id"] == "voice:CA-other"
        await other.close()


async def test_partial_native_write_unknown_is_never_replayed(voice, monkeypatch):
    async with voice() as r:
        ws, _ = await connect(r)
        event = await prompt(r, ws)
        connection = r.platform._calls["CA-one"]
        actual = connection.websocket.send_json
        calls = []

        async def fail_last(value, *args, **kwargs):
            calls.append(value)
            if len(calls) == 2:
                raise ConnectionResetError("independent final frame lost")
            return await actual(value, *args, **kwargs)

        monkeypatch.setattr(connection.websocket, "send_json", fail_last)
        parts = [{"type": "text", "text": "once", "role": "message"}]
        result = await send(r, event, parts)
        assert result["state"] == "unknown"
        assert await ws.receive_json(timeout=2) == {
            "type": "text",
            "token": "once",
            "last": False,
        }
        assert await send(r, event, parts) == result and len(calls) == 2
        await r.driver._finish(
            ResponseFinishParams.from_mapping(
                {
                    **r.driver._context.identity.to_mapping(),
                    "response_handle": event.response_handle,
                    "outcome": "completed",
                }
            ),
            None,
        )
        assert await send(r, event, parts) == result and len(calls) == 2
        await ws.close()
