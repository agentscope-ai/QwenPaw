"""SIP native conformance with real shared delivery, callbacks and cleanup."""
import asyncio
import importlib.abc
import sys
import threading
from types import SimpleNamespace as NS

import pytest

from sip_native_support import vendor, running, incoming, send_params, until

__all__ = ["vendor"]
from qwenpaw_channel_sip.pyvoip_backend import _ThreadAudioBridge
from qwenpaw_channel_sip.runtime import ResourceClaim
from qwenpaw_channel_sip.stt_engine import AliyunSTTStream
from qwenpaw.channel_protocol.models import ResponseFinishParams


@pytest.mark.parametrize("mode", ["dev", "livekit"])
async def test_real_backend_transcript_sender_turn_delivery_and_finish(
    vendor, mode
):
    async with running(vendor, mode) as (driver, peer, identity):
        call = await incoming(vendor, mode)
        asr = vendor.asrs[-1]
        asr.sentence("same prompt")
        await until(lambda: len(peer.batches) == 1)
        event = peer.batches[0]["events"][0]
        assert (
            event["sender_id"]
            == event["acl_sender_id"]
            == "sip:alice@example.test"
        )
        assert event["conversation"]["id"] == (
            "sip:call-1" if mode == "dev" else "sip:sip-inbound"
        )
        assert event["metadata"]["user_id"] == event["sender_id"]
        result = await driver._send(send_params(identity, event), None)
        assert result["state"] == "acknowledged"
        assert vendor.synths[-1].text == "spoken answer"
        if mode == "dev":
            assert call.writes == [bytes([128]) * 160]
        else:
            assert vendor.sources[-1].frames[0].data == b"\0" * 960
            assert vendor.sources[-1].frames[0].sample_rate == 24000
        finish = ResponseFinishParams.from_mapping(
            {
                **identity,
                "response_handle": event["response_handle"],
                "outcome": "completed",
            }
        )
        await driver._finish(finish, None)
        assert len(driver._platform._calls) == 1
        assert (
            (call.hangups == 0)
            if mode == "dev"
            else not vendor.rooms[-1].disconnected
        )
        asr.sentence("same prompt")
        await until(lambda: len(peer.batches) == 2)
        second = peer.batches[1]["events"][0]
        assert second["event_id"] != event["event_id"]
        assert second["response_handle"] != event["response_handle"]
        assert (
            second["metadata"]["debounce_key"]
            != event["metadata"]["debounce_key"]
        )


@pytest.mark.parametrize("mode", ["dev", "livekit"])
async def test_unknown_audio_receipt_is_not_replayed(vendor, mode):
    async with running(vendor, mode) as (driver, peer, identity):
        call = await incoming(vendor, mode)
        vendor.asrs[-1].sentence("question")
        await until(lambda: peer.batches)
        params = send_params(identity, peer.batches[0]["events"][0])
        vendor.fail_write = True
        first = await driver._send(params, None)
        assert first["state"] == "unknown"
        assert first["reason_code"] == "SIP_TTS_PLAYBACK_FAILED"
        vendor.fail_write = False
        assert await driver._send(params, None) == first
        assert len(vendor.synths) == 1
        assert (
            len(call.writes if mode == "dev" else vendor.sources[-1].frames)
            == 1
        )


@pytest.mark.parametrize("mode", ["dev", "livekit"])
async def test_new_turn_and_speech_interrupt_retire_only_tts(vendor, mode):
    async with running(vendor, mode) as (driver, peer, identity):
        await incoming(vendor, mode)
        asr = vendor.asrs[-1]
        asr.sentence("first")
        await until(lambda: peer.batches)
        event = peer.batches[0]["events"][0]
        old = driver._route_attrs(event["response_handle"])
        asr.partial("interrupt")
        await until(
            lambda: next(iter(driver._platform._calls.values())).abort.is_set()
        )
        assert len(driver._platform._calls) == 1
        stale = await driver._send(send_params(identity, event), None)
        assert (
            stale["state"] == "failed"
            and stale["reason_code"] == "CALL_CLOSED"
        )
        assert not vendor.synths
        asr.sentence("second")
        await until(lambda: len(peer.batches) == 2)
        new = driver._route_attrs(
            peer.batches[1]["events"][0]["response_handle"]
        )
        assert old["connection_epoch"] == new["connection_epoch"]
        assert int(new["turn_id"]) == int(old["turn_id"]) + 1
        assert not vendor.asrs[-1].closed


async def test_active_tts_interrupt_joins_native_synth_and_retains_call(
    vendor,
):
    async with running(vendor) as (driver, peer, identity):
        call = await incoming(vendor, "dev")
        vendor.asrs[-1].sentence("first")
        await until(lambda: peer.batches)
        vendor.tts_release = threading.Event()
        task = asyncio.create_task(
            driver._send(
                send_params(identity, peer.batches[0]["events"][0]), None
            )
        )
        await until(lambda: vendor.synths)
        vendor.asrs[-1].partial("barge in")
        await asyncio.sleep(0.02)
        assert (
            not task.done()
        ), "native SDK custody must remain until its call returns"
        vendor.tts_release.set()
        result = await task
        assert result["state"] == "failed"
        assert result["reason_code"] == "CALL_INTERRUPTED"
        assert not call.writes and not call.hangups
        assert len(driver._platform._calls) == 1


@pytest.mark.parametrize("mode", ["dev", "livekit"])
async def test_stop_failure_retains_native_resource_claim_until_retry(
    vendor, mode
):
    async with running(vendor, mode) as (driver, _, _):
        platform, backend = driver._platform, driver._platform.backend
        claim = backend._claim
        vendor.fail_stop = True
        with pytest.raises(RuntimeError, match="SIP_PLATFORM_STOP_INCOMPLETE"):
            await driver.stop()
        assert driver._platform is platform and platform.backend is backend
        assert claim._fd is not None
        other = (
            ResourceClaim("sip://localhost:15061", "dev-listener")
            if mode == "dev"
            else ResourceClaim("https://livekit.test:443/", "sip-inbound")
        )
        with pytest.raises(RuntimeError):
            other.acquire()
        vendor.fail_stop = False
        await driver.stop()
        assert driver._platform is None and claim._fd is None
        other.acquire()
        other.close()


@pytest.mark.parametrize("mode", ["dev", "livekit"])
async def test_same_port_or_room_second_backend_cannot_steal_resource(
    vendor, mode
):
    async with running(vendor, mode) as (first, _, _):
        with pytest.raises(RuntimeError, match="ALREADY_(IN_USE|OWNED)"):
            async with running(vendor, mode):
                pass
        assert (
            first._connected and first._platform.backend._claim._fd is not None
        )


async def test_livekit_foreign_participant_track_and_disconnect_are_ignored(
    vendor,
):
    async with running(vendor, "livekit") as (driver, peer, identity):
        accepted = await incoming(vendor, "livekit", "real-caller")
        room, backend = vendor.rooms[-1], driver._platform.backend
        foreign = room.participant("foreign-caller")
        await asyncio.sleep(0.01)
        room.handlers["track_subscribed"](NS(kind=1), None, foreign)
        room.handlers["participant_disconnected"](foreign)
        await asyncio.sleep(0.01)
        assert backend._accepted["participant"] is accepted
        assert len(vendor.asrs) == 1 and not backend._readers
        assert not room.disconnected and len(driver._platform._calls) == 1
        vendor.asrs[0].sentence("real text")
        await until(lambda: peer.batches)
        assert peer.batches[0]["events"][0]["sender_id"] == "real-caller"


async def test_welcome_timeout_and_native_max_calls(vendor):
    async with running(
        vendor,
        welcome_greeting="hello caller",
        call_timeout=0.15,
        max_concurrent_calls=1,
    ) as (driver, peer, _):
        call = await incoming(vendor, "dev")
        await until(lambda: call.writes)
        assert vendor.synths[0].text == "hello caller"
        assert not peer.batches
        refused = vendor.phones[-1].incoming("extra-call")
        await until(lambda: refused.hangups)
        assert len(vendor.asrs) == 1
        await until(lambda: call.hangups)
        await until(lambda: not driver._platform._calls)
        assert vendor.asrs[0].closed


async def test_welcome_failure_diagnosed_without_discarding_call(vendor):
    vendor.fail_tts = True
    async with running(vendor, welcome_greeting="hello caller") as (
        driver,
        peer,
        _,
    ):
        call = await incoming(vendor, "dev")
        await until(
            lambda: any(
                "SIP_WELCOME_FAILED" in str(row) for row in peer.notifications
            )
        )
        assert len(driver._platform._calls) == 1 and not call.hangups


async def test_pcm_thread_bridge_has_exact_150_drop_oldest_and_one_wakeup():
    callbacks = []
    queue = asyncio.Queue(maxsize=150)
    bridge = _ThreadAudioBridge(
        NS(call_soon_threadsafe=callbacks.append), queue
    )
    for i in range(200):
        bridge.put(bytes([i]))
    assert len(callbacks) == 1 and len(bridge.frames) == 150
    callbacks.pop()()
    assert list(queue._queue) == [bytes([i]) for i in range(50, 200)]
    bridge.put(None)
    callbacks.pop()()
    assert queue.qsize() == 150 and list(queue._queue)[-1] is None


@pytest.mark.parametrize("mode", ["dev", "livekit"])
async def test_actual_backend_pcm_queue_is_bounded_at_150(vendor, mode):
    async with running(vendor, mode) as (driver, peer, _):
        await incoming(vendor, mode)
        binding = next(iter(driver._platform._calls.values()))
        assert binding.audio_in.maxsize == 150


async def test_asr_32_queue_overload_terminates_call_and_reports(vendor):
    async with running(vendor) as (driver, peer, _):
        call = await incoming(vendor, "dev")
        asr = vendor.asrs[-1]
        engine = next(iter(driver._platform._calls.values())).stt
        # Deliver in one native burst, before the event loop can consume.
        for i in range(33):
            asr.sentence(str(i))
        assert engine._transcript_queue.maxsize == 32
        assert engine._transcript_queue.qsize() == 32
        await until(
            lambda: any(
                "STT_TRANSCRIPT_BACKPRESSURE" in str(row)
                for row in peer.notifications
            )
        )
        assert call.hangups and not driver._platform._calls
        assert asr.closed


async def test_sdk_stop_error_preserves_asr_for_retry(vendor):
    engine = AliyunSTTStream(api_key="explicit")
    await engine.start()
    native = vendor.asrs[-1]
    original = native.finish

    async def failed():
        raise OSError("finish refused")

    native.finish = failed
    with pytest.raises(RuntimeError, match="SIP_STT_STOP_INCOMPLETE"):
        await engine.stop()
    assert engine._asr is native
    native.finish = original
    await engine.stop()
    assert engine._asr is None


@pytest.mark.parametrize(
    "mode,forbidden", [("dev", "livekit"), ("livekit", "pyVoIP")]
)
async def test_selected_backend_never_imports_unselected_sdk(
    vendor, monkeypatch, mode, forbidden
):
    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == forbidden or fullname.startswith(forbidden + "."):
                raise AssertionError("unselected SDK import: " + fullname)

    for name in tuple(sys.modules):
        if name == forbidden or name.startswith(forbidden + "."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [Guard(), *sys.meta_path])
    async with running(vendor, mode):
        await incoming(vendor, mode)


@pytest.mark.parametrize("mode", ["dev", "livekit"])
async def test_legacy_empty_caller_transcript_remains_deliverable(
    vendor, mode
):
    async with running(vendor, mode) as (driver, peer, identity):
        await incoming(vendor, mode, "")
        call = next(iter(driver._platform._calls.values()))
        assert (
            call.from_uri == ""
        )  # Native legacy callback preserves this value.
        vendor.asrs[-1].sentence("caller without identity")
        await until(lambda: peer.batches or peer.rejections)
        assert (
            peer.batches
        ), "legacy empty-caller call must still reach host admission"
        event = peer.batches[0]["events"][0]
        assert event["content_parts"] == [
            {"type": "text", "text": "caller without identity"}
        ]
        assert event["metadata"]["session_id"] == call.session_id
        # A host unknown-identity contract is pending; never invent an ACL sender.
        assert event["acl_sender_id"] == ""
