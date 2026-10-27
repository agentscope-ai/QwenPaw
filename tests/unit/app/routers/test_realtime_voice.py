# -*- coding: utf-8 -*-
# Recording lifecycle tests inspect file handles and closed state directly.
# pylint: disable=protected-access
import asyncio
import json
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.app.realtime_voice.contracts import (
    AudioFrame,
    AudioFrameKind,
    decode_audio_frame,
    encode_audio_frame,
)
from qwenpaw.app.routers.realtime_voice import (
    _client_to_coordinator,
    _coordinator_to_client,
    realtime_voice_stream,
)
from qwenpaw.app.realtime_voice.recording import VoiceRecording
from qwenpaw.providers.realtime_voice import ProviderEvent


@pytest.mark.asyncio
async def test_playback_feedback_is_generation_scoped():
    websocket = SimpleNamespace(
        receive=AsyncMock(
            side_effect=[
                {
                    "type": "websocket.receive",
                    "text": '{"type":"output.playback","generation":1,'
                    '"output_id":"old","status":"drained"}',
                },
                {
                    "type": "websocket.receive",
                    "text": '{"type":"output.playback","generation":2,'
                    '"output_id":"current","status":"interrupted"}',
                },
                {"type": "websocket.disconnect"},
            ],
        ),
    )
    coordinator = SimpleNamespace(playback_feedback=Mock())
    await _client_to_coordinator(
        websocket,
        asyncio.Lock(),
        SimpleNamespace(generation=2),
        coordinator,
    )
    coordinator.playback_feedback.assert_called_once_with(
        "current",
        "interrupted",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("record", [False, True])
async def test_client_audio_and_controls_are_relayed_without_semantics(
    tmp_path,
    record,
):
    recording = VoiceRecording(tmp_path) if record else None
    pcm = b"\x01\x02\x03\x04"
    frame = encode_audio_frame(
        AudioFrame(
            kind=AudioFrameKind.INPUT_PCM16,
            sequence=0,
            sample_rate=16000,
            channels=1,
            payload=pcm,
        ),
    )
    websocket = SimpleNamespace(
        receive=AsyncMock(
            side_effect=[
                {"type": "websocket.receive", "bytes": frame},
                {
                    "type": "websocket.receive",
                    "bytes": encode_audio_frame(
                        AudioFrame(
                            kind=AudioFrameKind.INPUT_PCM16,
                            sequence=1,
                            sample_rate=16000,
                            channels=1,
                            payload=pcm,
                        ),
                    ),
                },
                {
                    "type": "websocket.receive",
                    "text": '{"type":"interrupt"}',
                },
                {
                    "type": "websocket.receive",
                    "text": '{"type":"agent.observe"}',
                },
                {
                    "type": "websocket.receive",
                    "text": '{"type":"output.playback","generation":2,'
                    '"output_id":"output-1","status":"interrupted"}',
                },
                {"type": "websocket.receive", "text": '{"type":"stop"}'},
            ],
        ),
        send_json=AsyncMock(),
    )
    coordinator = SimpleNamespace(
        send_audio=AsyncMock(),
        interrupt=AsyncMock(),
        observe_agent_run=AsyncMock(),
        playback_feedback=Mock(),
    )
    live = SimpleNamespace(
        media=SimpleNamespace(input_sample_rate=16000, channels=1),
        generation=2,
    )

    await _client_to_coordinator(
        websocket,
        asyncio.Lock(),
        live,
        coordinator,
        recording,
    )

    assert [
        call.args[0] for call in coordinator.send_audio.await_args_list
    ] == [
        pcm,
        pcm,
    ]
    coordinator.interrupt.assert_awaited_once_with()
    coordinator.observe_agent_run.assert_awaited_once_with()
    coordinator.playback_feedback.assert_called_once_with(
        "output-1",
        "interrupted",
    )
    if recording:
        recording.close()
        with wave.open(str(tmp_path / "input.wav")) as saved:
            assert (
                saved.getframerate(),
                saved.getnchannels(),
                saved.getsampwidth(),
            ) == (16000, 1, 2)
            assert saved.readframes(saved.getnframes()) == pcm + pcm
        events = [
            json.loads(line)
            for line in (tmp_path / "events.jsonl").read_text().splitlines()
        ]
        assert [row["event"]["type"] for row in events] == [
            "audio",
            "audio",
            "interrupt",
            "agent.observe",
            "output.playback",
            "stop",
        ]
        assert events[0]["event"]["sample_offset"] == 0
        assert events[0]["event"]["sample_count"] == 2
        assert events[1]["event"]["sample_offset"] == 2
        assert events[1]["event"]["sequence"] == 1
        assert [row["elapsed_ms"] for row in events] == sorted(
            row["elapsed_ms"] for row in events
        )
    else:
        assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("record", [False, True])
async def test_coordinator_audio_and_state_use_one_renderer_protocol(
    tmp_path,
    record,
):
    recording = VoiceRecording(tmp_path) if record else None
    pcm = b"\x05\x06\x07\x08"

    class Coordinator:
        async def events(self):
            yield ProviderEvent(
                "output.audio",
                "audio-1",
                audio=pcm,
                correlation_id="response-1",
            )
            yield ProviderEvent(
                "agent.task.updated",
                "task-1",
                {
                    "task_id": "task-1",
                    "status": "running",
                    "run_id": "run-1",
                },
            )

    websocket = SimpleNamespace(
        send_bytes=AsyncMock(),
        send_json=AsyncMock(),
    )
    live = SimpleNamespace(
        media=SimpleNamespace(output_sample_rate=24000, channels=1),
        generation=3,
        chat=SimpleNamespace(id="chat-1"),
    )

    await _coordinator_to_client(
        websocket,
        asyncio.Lock(),
        live,
        Coordinator(),
        recording,
    )

    binary = websocket.send_bytes.await_args.args[0]
    decoded = decode_audio_frame(binary)
    assert decoded.kind == AudioFrameKind.OUTPUT_PCM16
    assert decoded.payload == pcm
    websocket.send_json.assert_awaited_once_with(
        {
            "type": "agent.task.updated",
            "event_id": "task-1",
            "generation": 3,
            "chat_id": "chat-1",
            "task_id": "task-1",
            "status": "running",
            "run_id": "run-1",
        },
    )
    if recording:
        recording.close()
        with wave.open(str(tmp_path / "output.wav")) as saved:
            assert (
                saved.getframerate(),
                saved.getnchannels(),
                saved.getsampwidth(),
            ) == (24000, 1, 2)
            assert saved.readframes(saved.getnframes()) == pcm
        events = [
            json.loads(line)
            for line in (tmp_path / "events.jsonl").read_text().splitlines()
        ]
        assert [row["event"]["type"] for row in events] == [
            "audio",
            "agent.task.updated",
        ]
        assert events[1]["event"] == websocket.send_json.await_args.args[0]


def test_voice_recording_is_opt_in_and_does_not_record_credentials(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("QWENPAW_VOICE_RECORDING_DIR", raising=False)
    assert VoiceRecording.from_environment(SimpleNamespace()) is None
    monkeypatch.setenv("QWENPAW_VOICE_RECORDING_DIR", str(tmp_path))
    live = SimpleNamespace(
        session_id="session-1",
        generation=2,
        chat=SimpleNamespace(id="chat-1"),
        config=SimpleNamespace(
            provider_id="provider",
            realtime_model="model",
            voice="voice",
        ),
        media=SimpleNamespace(
            model_dump=lambda: {
                "input_sample_rate": 16000,
                "output_sample_rate": 24000,
                "channels": 1,
            },
        ),
        api_key="do-not-record",
    )
    first = VoiceRecording.from_environment(live)
    second = VoiceRecording.from_environment(live)
    assert first.directory != second.directory
    first.close()
    second.close()
    saved = (first.directory / "events.jsonl").read_text()
    assert "do-not-record" not in saved
    assert json.loads(saved)["event"]["chat_id"] == "chat-1"


@pytest.mark.asyncio
async def test_recording_write_failure_does_not_interrupt_audio(tmp_path):
    recording = VoiceRecording(tmp_path)
    recording._events = Mock(wraps=recording._events)
    recording._events.write.side_effect = OSError("disk full")
    frame = encode_audio_frame(
        AudioFrame(
            kind=AudioFrameKind.INPUT_PCM16,
            sequence=0,
            sample_rate=16000,
            channels=1,
            payload=b"\x01\x02",
        ),
    )
    websocket = SimpleNamespace(
        receive=AsyncMock(
            side_effect=[
                {"type": "websocket.receive", "bytes": frame},
                {"type": "websocket.receive", "text": '{"type":"stop"}'},
            ],
        ),
    )
    coordinator = SimpleNamespace(send_audio=AsyncMock())
    live = SimpleNamespace(
        media=SimpleNamespace(input_sample_rate=16000, channels=1),
    )
    await _client_to_coordinator(
        websocket,
        asyncio.Lock(),
        live,
        coordinator,
        recording,
    )
    coordinator.send_audio.assert_awaited_once_with(b"\x01\x02")
    recording._events.close.assert_called_once()
    recording.close()
    recording._events.close.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_audio_sequence_is_rejected():
    frames = [
        encode_audio_frame(
            AudioFrame(
                kind=AudioFrameKind.INPUT_PCM16,
                sequence=0,
                sample_rate=16000,
                channels=1,
                payload=b"a",
            ),
        ),
        encode_audio_frame(
            AudioFrame(
                kind=AudioFrameKind.INPUT_PCM16,
                sequence=2,
                sample_rate=16000,
                channels=1,
                payload=b"b",
            ),
        ),
    ]
    websocket = SimpleNamespace(
        receive=AsyncMock(
            side_effect=[
                {"type": "websocket.receive", "bytes": frames[0]},
                {"type": "websocket.receive", "bytes": frames[1]},
            ],
        ),
        send_json=AsyncMock(),
    )
    coordinator = SimpleNamespace(send_audio=AsyncMock())

    with pytest.raises(ValueError, match="not contiguous"):
        await _client_to_coordinator(
            websocket,
            asyncio.Lock(),
            SimpleNamespace(
                media=SimpleNamespace(
                    input_sample_rate=16000,
                    channels=1,
                ),
                generation=1,
            ),
            coordinator,
        )


@pytest.mark.asyncio
async def test_clean_coordinator_close_ignores_late_input_send_failure():
    closed = asyncio.Event()

    class Coordinator:
        async def events(self):
            closed.set()
            yield ProviderEvent(
                "session.closed",
                "closed-1",
                {"reason": "idle_timeout", "recoverable": True},
            )

        async def send_audio(self, _payload):
            await closed.wait()
            raise ConnectionError("provider socket is already closed")

    frame = encode_audio_frame(
        AudioFrame(
            kind=AudioFrameKind.INPUT_PCM16,
            sequence=0,
            sample_rate=16000,
            channels=1,
            payload=b"pcm",
        ),
    )
    live = SimpleNamespace(
        generation=2,
        media=SimpleNamespace(
            input_sample_rate=16000,
            output_sample_rate=24000,
            channels=1,
        ),
        config=SimpleNamespace(max_session_seconds=60),
        chat=SimpleNamespace(id="chat-1"),
    )
    service = SimpleNamespace(
        consume_grant=AsyncMock(return_value=live),
        connect=AsyncMock(return_value=Coordinator()),
        end_session=AsyncMock(),
    )
    websocket = SimpleNamespace(
        query_params={"token": "ticket"},
        app=SimpleNamespace(
            state=SimpleNamespace(realtime_voice_service=service),
        ),
        accept=AsyncMock(),
        receive=AsyncMock(
            return_value={"type": "websocket.receive", "bytes": frame},
        ),
        send_json=AsyncMock(),
        send_bytes=AsyncMock(),
        close=AsyncMock(),
    )

    await realtime_voice_stream(websocket, "session-1")

    events = [call.args[0] for call in websocket.send_json.await_args_list]
    assert [event["type"] for event in events] == [
        "session.connected",
        "session.closed",
    ]
    assert events[-1]["reason"] == "idle_timeout"
    websocket.close.assert_awaited_once_with(code=1000)
    service.end_session.assert_awaited_once_with(live)


@pytest.mark.asyncio
async def test_coordinator_failure_remains_an_upstream_error():
    class Coordinator:
        async def events(self):
            if False:  # pylint: disable=using-constant-test
                yield
            raise RuntimeError("provider failed")

    async def receive():
        await asyncio.Event().wait()

    live = SimpleNamespace(
        generation=1,
        media=SimpleNamespace(output_sample_rate=24000, channels=1),
        config=SimpleNamespace(max_session_seconds=60),
        chat=SimpleNamespace(id="chat-1"),
    )
    service = SimpleNamespace(
        consume_grant=AsyncMock(return_value=live),
        connect=AsyncMock(return_value=Coordinator()),
        end_session=AsyncMock(),
    )
    websocket = SimpleNamespace(
        query_params={"token": "ticket"},
        app=SimpleNamespace(
            state=SimpleNamespace(realtime_voice_service=service),
        ),
        accept=AsyncMock(),
        receive=receive,
        send_json=AsyncMock(),
        send_bytes=AsyncMock(),
        close=AsyncMock(),
    )

    await realtime_voice_stream(websocket, "session-1")

    events = [call.args[0] for call in websocket.send_json.await_args_list]
    assert [event["type"] for event in events] == [
        "session.connected",
        "error",
    ]
    assert events[-1]["code"] == "upstream_unavailable"
    websocket.close.assert_awaited_once_with(code=1011)
    service.end_session.assert_awaited_once_with(live)


@pytest.mark.asyncio
async def test_closed_ack_waits_for_durable_cleanup(tmp_path, monkeypatch):
    recording = VoiceRecording(tmp_path)
    monkeypatch.setattr(
        VoiceRecording,
        "from_environment",
        lambda live: recording,
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def close(_live):
        entered.set()
        await release.wait()

    class Coordinator:
        async def events(self):
            yield ProviderEvent(
                "session.closed",
                "closed",
                {"reason": "idle_timeout"},
            )

    live = SimpleNamespace(
        generation=1,
        config=SimpleNamespace(max_session_seconds=60),
        chat=SimpleNamespace(id="chat"),
    )
    service = SimpleNamespace(
        consume_grant=AsyncMock(return_value=live),
        connect=AsyncMock(return_value=Coordinator()),
        end_session=AsyncMock(side_effect=close),
    )

    async def receive():
        await asyncio.Event().wait()

    websocket = SimpleNamespace(
        query_params={"token": "token"},
        app=SimpleNamespace(
            state=SimpleNamespace(realtime_voice_service=service),
        ),
        accept=AsyncMock(),
        receive=receive,
        send_json=AsyncMock(),
        close=AsyncMock(),
    )
    running = asyncio.create_task(realtime_voice_stream(websocket, "voice"))
    await asyncio.wait_for(entered.wait(), 1)
    assert not recording._closed
    assert [
        c.args[0]["type"] for c in websocket.send_json.await_args_list
    ] == [
        "session.connected",
    ]
    release.set()
    await asyncio.wait_for(running, 1)
    assert websocket.send_json.await_args.args[0]["type"] == "session.closed"
    service.end_session.assert_awaited_once()
    assert recording._closed
    events = [
        json.loads(line)["event"]
        for line in (tmp_path / "events.jsonl").read_text().splitlines()
    ]
    assert [event["type"] for event in events] == [
        "session.closed",
        "recording.closed",
    ]
    assert events[0]["reason"] == "idle_timeout"
