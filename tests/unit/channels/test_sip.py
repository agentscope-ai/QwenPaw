# -*- coding: utf-8 -*-
"""SIP pyVoIP backend: native callbacks, PCM conversion and TTS cleanup."""
import asyncio
from contextlib import asynccontextmanager
import json
import sys
import threading
from types import ModuleType, SimpleNamespace as NS
import pytest
from qwenpaw.channel_protocol.models import SendParams, ResponseFinishParams
from tests.channel_support.driver import ROOT, bind, module

pytestmark = pytest.mark.asyncio


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


class Vendor:
    def __init__(self):
        (
            self.phones,
            self.asrs,
            self.synths,
        ) = ([], [], [])
        self.tts_release = None

    def modules(self):
        owner = self

        class Phone:
            def __init__(self, *args, **kwargs):
                self.args, self.kwargs = args, kwargs
                self.calls, self.threads = [], []
                owner.phones.append(self)

            def start(self):
                pass

            def stop(self):
                for call in self.calls:
                    call.hangup()

            def incoming(
                self,
                call_id="call-1",
                sender="sip:alice@example.test",
            ):
                call = Call(call_id, sender)
                self.calls.append(call)
                thread = threading.Thread(
                    target=self.kwargs["callCallback"],
                    args=(call,),
                )
                self.threads.append(thread)
                thread.start()
                return call

        class Call:
            def __init__(self, call_id, sender):
                self.request = NS(
                    headers={
                        "Call-ID": call_id,
                        "From": sender,
                        "To": "sip:bot@example.test",
                    },
                )
                self.state, self.writes, self.hangups = "ringing", [], 0

            def answer(self):
                self.state = "answered"

            def read_audio(self, **kwargs):
                return b""

            def write_audio(self, data):
                self.writes.append(bytes(data))

            def hangup(self):
                self.hangups += 1
                self.state = "ended"

        class ASR:
            def __init__(self, **kwargs):
                self.kwargs, self.audio, self.closed = kwargs, [], False
                owner.asrs.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                self.closed = True

            async def send_audio(self, chunk):
                self.audio.append(chunk)

            async def finish(self):
                pass

            def sentence(self, text):
                self.kwargs["on_sentence_end"](text)

            def partial(self, text):
                self.kwargs["on_partial"](text)

        class Synth:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.text = None
                owner.synths.append(self)

            def call(self, text):
                self.text = text
                if owner.tts_release:
                    owner.tts_release.wait()
                callback = self.kwargs["callback"]
                assert self.kwargs["format"] == 8000
                callback.on_data(b"\0" * 320)
                callback.on_complete()

        def module(name, **attrs):
            value = ModuleType(name)
            value.__dict__.update(attrs)
            return value

        voip = module(
            "pyVoIP.VoIP",
            VoIPPhone=Phone,
            CallState=NS(ANSWERED="answered"),
            InvalidStateError=type("InvalidStateError", (Exception,), {}),
        )
        realtime = module("dashscope_realtime", DashScopeRealtimeASR=ASR)
        config = module(
            "dashscope_realtime.asr",
            ASRConfig=lambda **kwargs: NS(**kwargs),
        )
        tts = module(
            "dashscope.audio.tts_v2",
            AudioFormat=NS(
                **{
                    f"PCM_{rate}HZ_MONO_16BIT": rate
                    for rate in (8000, 16000, 22050, 24000)
                },
            ),
            ResultCallback=object,
            SpeechSynthesizer=Synth,
        )
        return {
            "pyVoIP": module("pyVoIP", VoIP=voip),
            "pyVoIP.VoIP": voip,
            "dashscope_realtime": realtime,
            "dashscope_realtime.asr": config,
            "dashscope": module("dashscope"),
            "dashscope.audio": module("dashscope.audio"),
            "dashscope.audio.tts_v2": tts,
        }


@pytest.fixture
def vendor(monkeypatch, unused_tcp_port):
    value = Vendor()
    value.sip_port = unused_tcp_port
    for name, sdk in value.modules().items():
        monkeypatch.setitem(sys.modules, name, sdk)
    yield value
    if value.tts_release:
        value.tts_release.set()


@asynccontextmanager
async def running(vendor, tmp_path):
    driver = module("sip").SIPDriver()
    peer, identity = bind("sip", driver, tmp_path)
    try:
        defaults = {
            k: v["default"]
            for k, v in json.loads(
                (ROOT / "plugins/channel/sip/channel.json").read_text(),
            )["config_schema"]["properties"].items()
            if "default" in v
        }
        await driver.start(
            {
                **defaults,
                "enabled": True,
                "sip_mode": "dev",
                "sip_server": "registrar.test",
                "sip_port": vendor.sip_port,
                "dashscope_api_key": "test-key",
                "welcome_greeting": "",
            },
        )
        await until(lambda: driver._connected)
        yield driver, peer, identity.to_mapping()
    finally:
        if vendor.tts_release:
            vendor.tts_release.set()
        await driver.stop()


async def incoming(vendor):
    call = vendor.phones[-1].incoming()
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
        },
    )


async def test_real_backend_transcript_sender_turn_delivery_and_finish(
    vendor,
    tmp_path,
):
    async with running(vendor, tmp_path) as (driver, peer, identity):
        call = await incoming(vendor)
        asr = vendor.asrs[-1]
        asr.sentence("same prompt")
        await until(lambda: len(peer.batches) == 1)
        event = peer.batches[0]["events"][0]
        assert (
            event["sender_id"]
            == event["acl_sender_id"]
            == "sip:alice@example.test"
        )
        assert event["conversation"]["id"] == "sip:call-1"
        assert event["metadata"]["user_id"] == event["sender_id"]
        result = await driver._send(send_params(identity, event), None)
        assert result["state"] == "acknowledged"
        assert vendor.synths[-1].text == "spoken answer"
        assert call.writes == [bytes([128]) * 160]
        finish = ResponseFinishParams.from_mapping(
            {
                **identity,
                "response_handle": event["response_handle"],
                "outcome": "completed",
            },
        )
        await driver._finish(finish, None)
        assert len(driver._platform._calls) == 1
        assert call.hangups == 0
        asr.sentence("same prompt")
        await until(lambda: len(peer.batches) == 2)
        second = peer.batches[1]["events"][0]
        assert second["event_id"] != event["event_id"]
        assert second["response_handle"] != event["response_handle"]
        assert (
            second["metadata"]["debounce_key"]
            != event["metadata"]["debounce_key"]
        )


async def test_new_turn_and_speech_interrupt_retire_only_tts(vendor, tmp_path):
    async with running(vendor, tmp_path) as (driver, peer, identity):
        await incoming(vendor)
        asr = vendor.asrs[-1]
        asr.sentence("first")
        await until(lambda: peer.batches)
        event = peer.batches[0]["events"][0]
        old = driver._route_attrs(event["response_handle"])
        asr.partial("interrupt")
        await until(
            lambda: next(
                iter(driver._platform._calls.values()),
            ).abort.is_set(),
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
            peer.batches[1]["events"][0]["response_handle"],
        )
        assert old["connection_epoch"] == new["connection_epoch"]
        assert int(new["turn_id"]) == int(old["turn_id"]) + 1
        assert not vendor.asrs[-1].closed


async def test_active_tts_interrupt_joins_native_synth_and_retains_call(
    vendor,
    tmp_path,
):
    async with running(vendor, tmp_path) as (driver, peer, identity):
        call = await incoming(vendor)
        vendor.asrs[-1].sentence("first")
        await until(lambda: peer.batches)
        vendor.tts_release = threading.Event()
        task = asyncio.create_task(
            driver._send(
                send_params(identity, peer.batches[0]["events"][0]),
                None,
            ),
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


async def test_stop_closes_asr_call_and_backend(vendor, tmp_path, monkeypatch):
    async with running(vendor, tmp_path) as (driver, peer, identity):
        call = await incoming(vendor)
        asr = vendor.asrs[-1]
        platform = driver._platform
        ended = asyncio.Event()
        callbacks = []
        on_ended = platform.backend.on_call_ended
        close_asr = type(asr).__aexit__

        async def notify_ended(call_id):
            callbacks.append(asyncio.current_task())
            ended.set()
            await on_ended(call_id)

        async def exit_asr(self, *args):
            await asyncio.wait_for(ended.wait(), 3)
            await close_asr(self, *args)

        monkeypatch.setattr(platform.backend, "on_call_ended", notify_ended)
        monkeypatch.setattr(type(asr), "__aexit__", exit_asr)
        stop = asyncio.create_task(driver.stop())
        done, _ = await asyncio.wait({stop}, timeout=3)
        if not done:
            # Release the native callback even when the regression returns.
            for task in callbacks:
                task.cancel()
        await stop
        assert done, "Native ended callback and driver.stop mutually waited"
        assert ended.is_set()
        assert call.hangups >= 1 and asr.closed
        assert not platform._calls and driver._platform is None
        assert all(
            not thread.is_alive() for thread in vendor.phones[-1].threads
        )
