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
    realtime_voice_stream,
)
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
            ]
        )
    )
    coordinator = SimpleNamespace(playback_feedback=Mock())
    await _client_to_coordinator(
        websocket, asyncio.Lock(), SimpleNamespace(generation=2), coordinator
    )
    coordinator.playback_feedback.assert_called_once_with("current", "interrupted")


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
                {"type": "websocket.receive", "text": '{"type":"stop"}'},
            ]
        ),
        send_json=AsyncMock(),
    )
    coordinator = SimpleNamespace(
        send_audio=AsyncMock(),
        interrupt=AsyncMock(),
        observe_agent_run=AsyncMock(),
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
        )
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
        app=SimpleNamespace(state=SimpleNamespace(realtime_voice_service=service)),
        accept=AsyncMock(),
        receive=AsyncMock(return_value={"type": "websocket.receive", "bytes": frame}),
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
            if False:
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
        app=SimpleNamespace(state=SimpleNamespace(realtime_voice_service=service)),
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
