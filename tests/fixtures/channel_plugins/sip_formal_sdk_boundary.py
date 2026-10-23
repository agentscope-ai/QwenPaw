"""File-controlled external SIP/ASR/TTS SDK boundary, never an IPC substitute.

Copied only onto a test dependency path. The official plugin stays byte-exact.
"""

import asyncio
from collections import deque
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS

from sip_vendor_boundary import Vendor

WORK = Path(__file__).with_name("boundary-work.txt").read_text().strip()
vendor = Vendor()
modules = vendor.modules()


def record(kind, **values):
    with (Path(WORK) / "ledger.jsonl").open("a") as stream:
        stream.write(
            json.dumps({"kind": kind, "pid": os.getpid(), **values}) + "\n"
        )


_original_synth = modules["dashscope.audio.tts_v2"].SpeechSynthesizer.call


def synthesize(self, text):
    record("synthesis", text=text, sample_rate=self.kwargs["format"])
    return _original_synth(self, text)


modules["dashscope.audio.tts_v2"].SpeechSynthesizer.call = synthesize
_original_stop = modules["pyVoIP.VoIP"].VoIPPhone.stop


def phone_stop(self):
    result = _original_stop(self)
    record("phone-stopped", calls=len(self.calls))
    return result


modules["pyVoIP.VoIP"].VoIPPhone.stop = phone_stop


class AudioStream:
    """One controlled SDK packet then wait; real backend owns reader cancel."""

    def __init__(self, track):
        self.track = track
        self.pending = asyncio.Queue()
        self.pending.put_nowait(NS(frame=NS(data=track.data)))
        self.closed = False
        record("reader-open")

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.pending.get()

    async def aclose(self):
        if not self.closed:
            self.closed = True
            record("reader-closed")


modules["livekit.rtc"].AudioStream = AudioStream
for owner, method, kind in [
    (modules["livekit.rtc"].Room, "disconnect", "room-disconnected"),
    (modules["livekit.rtc"].AudioSource, "aclose", "source-closed"),
    (modules["livekit.api"].LiveKitAPI, "aclose", "api-closed"),
]:
    original = getattr(owner, method)

    def instrument(original, kind):
        async def observed(self, *args, **kwargs):
            result = await original(self, *args, **kwargs)
            record(kind)
            return result

        return observed

    setattr(owner, method, instrument(original, kind))


async def commands():
    count, seen = 0, set()
    old_room = old_participant = None
    try:
        while not (Path(WORK) / "stop-boundary").exists():
            inbox = Path(WORK) / f"inbox-{os.getpid()}.jsonl"
            lines = inbox.read_text().splitlines() if inbox.exists() else []
            for line in lines[count:]:
                value = json.loads(line)
                if value["kind"] == "incoming":
                    call = vendor.phones[0].incoming(
                        value["call_id"], value["sender"]
                    )
                    frames = deque([bytes.fromhex(value["audio_hex"])])
                    call.read_audio = lambda **kwargs: (
                        frames.popleft() if frames else b""
                    )
                elif value["kind"] == "livekit-incoming":
                    room = vendor.rooms[-1]
                    participant = room.participant(value["sender"])
                    participant.track_publications["audio"] = NS(
                        track=NS(
                            kind=1, data=bytes.fromhex(value["audio_hex"])
                        )
                    )
                    old_room, old_participant = room, participant
                elif value["kind"] == "disconnect-room":
                    vendor.rooms[-1].handlers["disconnected"]()
                elif value["kind"] == "late-old-room":
                    old_room.handlers["participant_connected"](old_participant)
                    old_room.handlers["participant_disconnected"](
                        old_participant
                    )
                    old_room.handlers["disconnected"]()
                elif value["kind"] == "transcript":
                    vendor.asrs[-1].sentence(value["text"])
                elif value["kind"] == "inspect":
                    record(
                        "call-state",
                        calls=[
                            {"state": c.state, "hangups": c.hangups}
                            for p in vendor.phones
                            for c in p.calls
                        ],
                    )
                count += 1
                record("command", number=count)
            for i, asr in enumerate(vendor.asrs):
                if ("asr", i) not in seen:
                    seen.add(("asr", i))
                    record("asr", key=asr.kwargs["api_key"])
                for j, audio in enumerate(asr.audio):
                    if ("asr-audio", i, j) not in seen:
                        seen.add(("asr-audio", i, j))
                        record("asr-audio", hex=audio.hex())
            for i, room in enumerate(vendor.rooms):
                if ("room", i) not in seen and room.handlers:
                    seen.add(("room", i))
                    record("room", index=i)
            for i, source in enumerate(vendor.sources):
                for j, frame in enumerate(source.frames):
                    if ("source", i, j) not in seen:
                        seen.add(("source", i, j))
                        record("audio", hex=bytes(frame.data).hex(), source=i)
            for phone in vendor.phones:
                for call in phone.calls:
                    for i, data in enumerate(call.writes):
                        if (id(call), i) not in seen:
                            seen.add((id(call), i))
                            record("audio", hex=data.hex())
            await asyncio.sleep(0.005)
    finally:
        record("boundary-stopped")


record("loaded", fixture=__file__)
boundary_task = asyncio.create_task(commands())
