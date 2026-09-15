import asyncio
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
)
from qwenpaw.providers.realtime_voice import ProviderEvent


@pytest.mark.asyncio
async def test_playback_feedback_is_generation_scoped():
    websocket = SimpleNamespace(
        receive=AsyncMock(
            side_effect=[
                {
                    "type": "websocket.receive",
                    "text": '{"type":"output.playback","generation":1,"output_id":"old","status":"drained"}',
                },
                {
                    "type": "websocket.receive",
                    "text": '{"type":"output.playback","generation":2,"output_id":"current","status":"interrupted"}',
                },
                {"type": "websocket.disconnect"},
            ]
        )
    )
    coordinator = SimpleNamespace(playback_feedback=Mock())
    await _client_to_coordinator(
        websocket, asyncio.Lock(), SimpleNamespace(generation=2), coordinator
    )
    coordinator.playback_feedback.assert_called_once_with(
        "current", "interrupted"
    )


@pytest.mark.asyncio
async def test_client_audio_and_controls_are_relayed_without_semantics():
    frame = encode_audio_frame(
        AudioFrame(
            kind=AudioFrameKind.INPUT_PCM16,
            sequence=0,
            sample_rate=16000,
            channels=1,
            payload=b"pcm",
        )
    )
    websocket = SimpleNamespace(
        receive=AsyncMock(
            side_effect=[
                {"type": "websocket.receive", "bytes": frame},
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
                    "text": '{"type":"input.commit"}',
                },
                {
                    "type": "websocket.receive",
                    "text": '{"type":"admission.mode","mode":"steer"}',
                },
                {"type": "websocket.receive", "text": '{"type":"stop"}'},
            ]
        ),
        send_json=AsyncMock(),
    )
    coordinator = SimpleNamespace(
        send_audio=AsyncMock(),
        interrupt=AsyncMock(),
        observe_agent_run=AsyncMock(),
        commit_pending=AsyncMock(),
        set_admission_mode=AsyncMock(),
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
    )

    coordinator.send_audio.assert_awaited_once_with(b"pcm")
    coordinator.interrupt.assert_awaited_once_with()
    coordinator.observe_agent_run.assert_awaited_once_with()
    coordinator.commit_pending.assert_awaited_once_with()
    coordinator.set_admission_mode.assert_awaited_once_with("steer")


@pytest.mark.asyncio
async def test_coordinator_audio_and_state_use_one_renderer_protocol():
    class Coordinator:
        async def events(self):
            yield ProviderEvent(
                "output.audio",
                "audio-1",
                audio=b"pcm",
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
    )

    binary = websocket.send_bytes.await_args.args[0]
    decoded = decode_audio_frame(binary)
    assert decoded.kind == AudioFrameKind.OUTPUT_PCM16
    assert decoded.payload == b"pcm"
    websocket.send_json.assert_awaited_once_with(
        {
            "type": "agent.task.updated",
            "event_id": "task-1",
            "generation": 3,
            "chat_id": "chat-1",
            "task_id": "task-1",
            "status": "running",
            "run_id": "run-1",
        }
    )


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
            )
        ),
        encode_audio_frame(
            AudioFrame(
                kind=AudioFrameKind.INPUT_PCM16,
                sequence=2,
                sample_rate=16000,
                channels=1,
                payload=b"b",
            )
        ),
    ]
    websocket = SimpleNamespace(
        receive=AsyncMock(
            side_effect=[
                {"type": "websocket.receive", "bytes": frames[0]},
                {"type": "websocket.receive", "bytes": frames[1]},
            ]
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
