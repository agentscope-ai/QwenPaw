import asyncio
import base64
import json
from collections.abc import Callable

import pytest

from qwenpaw.providers.realtime_voice import (
    EffectiveRealtimeVoiceConfig,
    RealtimeDelegationTool,
    RealtimeSessionConfig,
)
from qwenpaw.providers.realtime_voice.dashscope import (
    DASHSCOPE_REGISTRATION,
    DashScopeRealtimeSession,
    _InputTurnState,
)


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.events: asyncio.Queue[str | None] = asyncio.Queue()
        self.closed = False

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.events.put_nowait(None)

    def feed(self, payload: dict) -> None:
        self.events.put_nowait(json.dumps(payload))

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.events.get()
        if item is None:
            raise StopAsyncIteration
        return item


def config() -> EffectiveRealtimeVoiceConfig:
    return EffectiveRealtimeVoiceConfig.from_model(
        "dashscope",
        DASHSCOPE_REGISTRATION.models[0],
    )


async def eventually(predicate: Callable[[], bool]) -> None:
    for _attempt in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not become true")


async def connect_session(
    monkeypatch,
    *,
    native_delegation: bool = False,
) -> tuple[DashScopeRealtimeSession, FakeSocket]:
    socket = FakeSocket()
    socket.feed({"type": "session.created", "event_id": "created"})
    socket.feed({"type": "session.updated", "event_id": "updated"})

    async def fake_connect(*_args, **_kwargs):
        return socket

    monkeypatch.setattr(
        "qwenpaw.providers.realtime_voice.dashscope.connect",
        fake_connect,
    )
    session = DashScopeRealtimeSession(config(), "secret")
    await session.connect(
        RealtimeSessionConfig(
            instructions="present authoritative state",
            delegation_tool=(
                RealtimeDelegationTool() if native_delegation else None
            ),
        )
    )
    return session, socket


@pytest.mark.asyncio
@pytest.mark.parametrize("late_created", [False, True])
async def test_input_identity_survives_a_newer_turn(late_created):
    session = DashScopeRealtimeSession(config(), "unused")
    try:
        for item in ("first", "second"):
            await session._handle(
                {"type": "input_audio_buffer.speech_started", "item_id": item}
            )
            await session._handle(
                {"type": "input_audio_buffer.speech_stopped", "item_id": item}
            )
        if late_created:
            await session._handle(
                {
                    "type": "conversation.item.created",
                    "item": {"id": "first", "role": "user"},
                }
            )
        await session._handle(
            {
                "type": (
                    "conversation.item.input_audio_transcription.completed"
                ),
                "item_id": "first",
                "transcript": "first request",
            }
        )
        assert (
            session._input_item_turns["first"]
            != session._input_item_turns["second"]
        )
        assert session._input_turns[
            session._input_item_turns["first"]
        ].transcript_final
        assert not session._input_turns[
            session._input_item_turns["second"]
        ].transcript_final
        events = [session._events.get_nowait() for _ in range(5)]
        assert [event.correlation_id for event in events] == [
            "first",
            "first",
            "second",
            "second",
            "first",
        ]
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_empty_or_failed_input_has_an_explicit_terminal_event(failed):
    session = DashScopeRealtimeSession(config(), "unused")
    try:
        await session._handle(
            {"type": "input_audio_buffer.speech_started", "item_id": "input"}
        )
        terminal = {
            "type": "conversation.item.input_audio_transcription."
            + ("failed" if failed else "completed"),
            "item_id": "input",
            "transcript": "",
        }
        if failed:
            terminal["error"] = {
                "code": "asr_failure",
                "message": "recognition unavailable",
            }
        await session._handle(terminal)
        assert session._events.qsize() == 2
        session._events.get_nowait()
        event = session._events.get_nowait()
        assert event.kind == (
            "input_transcript.failed" if failed else "input_transcript.final"
        )
        assert event.correlation_id == "input"
        assert session._input_turns[
            session._input_item_turns["input"]
        ].transcript_final
        await session._handle(terminal)
        assert session._events.empty()
    finally:
        await session.close()


@pytest.mark.parametrize("suffix", ["delta", "text"])
async def test_input_preview_is_a_revisable_snapshot(monkeypatch, suffix):
    session, socket = await connect_session(monkeypatch)
    events = session.events()
    await anext(events)
    try:
        for index, (text, stash) in enumerate(
            [
                ("", "今天"),
                ("今天", "天汽"),
                ("今天", "天气"),
                ("今天", "天气"),
                ("今天", ""),
                ("", ""),
            ],
        ):
            socket.feed(
                {
                    "type": (
                        "conversation.item.input_audio_transcription."
                        f"{suffix}"
                    ),
                    "event_id": f"preview-{index}",
                    "item_id": "input-1",
                    "text": text,
                    "stash": stash,
                },
            )
            event = await asyncio.wait_for(anext(events), timeout=1)
            assert event.kind == "input_transcript.partial"
            assert event.correlation_id == "input-1"
            assert event.data == {"text": text + stash}
    finally:
        await session.close()


async def acknowledge_item(socket: FakeSocket, index: int) -> None:
    await eventually(
        lambda: (
            len(
                [
                    payload
                    for payload in socket.sent
                    if payload["type"] == "conversation.item.create"
                ]
            )
            > index
        )
    )
    item = [
        payload["item"]
        for payload in socket.sent
        if payload["type"] == "conversation.item.create"
    ][index]
    socket.feed(
        {
            "type": "conversation.item.created",
            "event_id": f"created-{item['id']}",
            "item": {"id": item["id"], "type": item["type"]},
        }
    )


async def start_application_response(
    session: DashScopeRealtimeSession,
    socket: FakeSocket,
    *,
    item_offset: int = 0,
    response_id: str = "response-app",
) -> asyncio.Task[None]:
    async def response_sequence() -> None:
        request_item = await session.create_message(
            "user",
            "authoritative state",
        )
        result = await session.request_response()
        await session.delete_items({request_item, *result.item_ids})

    presentation = asyncio.create_task(response_sequence())
    await acknowledge_item(socket, item_offset)
    await eventually(lambda: socket.sent[-1]["type"] == "response.create")
    socket.feed(
        {
            "type": "response.created",
            "event_id": f"created-{response_id}",
            "response": {"id": response_id},
        }
    )
    return presentation


async def finish_presentation(
    socket: FakeSocket,
    presentation: asyncio.Task[None],
) -> None:
    acknowledged: set[str] = set()
    for _attempt in range(200):
        for payload in socket.sent:
            if payload["type"] != "conversation.item.delete":
                continue
            item_id = payload["item_id"]
            if item_id in acknowledged:
                continue
            acknowledged.add(item_id)
            socket.feed(
                {
                    "type": "conversation.item.deleted",
                    "event_id": f"deleted-{item_id}",
                    "item_id": item_id,
                }
            )
        if presentation.done():
            await presentation
            return
        await asyncio.sleep(0)
    raise AssertionError("presentation did not finish")


@pytest.mark.asyncio
async def test_session_configures_speech_only_voice(monkeypatch):
    session, socket = await connect_session(monkeypatch)
    ready = await anext(session.events())

    assert ready.kind == "session.ready"
    [update] = socket.sent
    assert update["type"] == "session.update"
    assert update["session"]["turn_detection"] == {
        "type": "server_vad",
        "threshold": 0.5,
        "silence_duration_ms": 800,
    }
    assert update["session"]["instructions"] == "present authoritative state"
    assert update["session"]["tools"] == []

    await session.send_audio(b"\x01\x02")
    assert socket.sent[-1]["type"] == "input_audio_buffer.append"
    assert base64.b64decode(socket.sent[-1]["audio"]) == b"\x01\x02"
    await session.close()


@pytest.mark.asyncio
async def test_native_delegation_registers_signal_only_tool(monkeypatch):
    session, socket = await connect_session(
        monkeypatch,
        native_delegation=True,
    )
    await anext(session.events())

    [tool] = socket.sent[0]["session"]["tools"]
    assert tool["function"]["name"] == "delegate_to_agent"
    assert tool["function"]["parameters"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    await session.close()


@pytest.mark.asyncio
async def test_native_delegation_joins_call_to_source_and_accepts_output(
    monkeypatch,
):
    session, socket = await connect_session(
        monkeypatch,
        native_delegation=True,
    )
    events = session.events()
    await anext(events)

    socket.feed(
        {
            "type": "input_audio_buffer.speech_started",
            "event_id": "speech",
            "item_id": "audio-input",
        }
    )
    socket.feed(
        {
            "type": "response.created",
            "event_id": "auto-created",
            "response": {"id": "response-auto"},
        }
    )
    socket.feed(
        {
            "type": "response.function_call_arguments.done",
            "event_id": "tool-done",
            "item_id": "tool-item",
            "call_id": "call-1",
            "name": "delegate_to_agent",
            "arguments": '{"request":"must be ignored"}',
        }
    )
    socket.feed(
        {
            "type": "response.done",
            "event_id": "response-done",
            "response": {"id": "response-auto", "status": "completed"},
        }
    )
    socket.feed(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "event_id": "transcript",
            "item_id": "audio-input",
            "transcript": "最终识别文本",
        }
    )

    received = [await anext(events) for _ in range(5)]
    requested = next(
        event for event in received if event.kind == "delegation.requested"
    )
    assert requested.correlation_id == "audio-input"
    assert requested.data == {
        "call_id": "call-1",
        "name": "delegate_to_agent",
        "item_id": "tool-item",
    }

    completion = asyncio.create_task(
        session.complete_delegation(
            "call-1",
            {"accepted": True, "status": "preparing"},
        )
    )
    await acknowledge_item(socket, 0)
    await completion
    [created] = [
        payload["item"]
        for payload in socket.sent
        if payload["type"] == "conversation.item.create"
    ]
    assert created["type"] == "function_call_output"
    assert created["call_id"] == "call-1"
    assert json.loads(created["output"]) == {
        "accepted": True,
        "status": "preparing",
    }
    assert session._presentation_ready.is_set()
    await session.close()


@pytest.mark.asyncio
async def test_equal_transcripts_keep_distinct_stable_item_ids(monkeypatch):
    session, socket = await connect_session(monkeypatch)
    events = session.events()
    await anext(events)

    for item_id in ("item-one", "item-two"):
        socket.feed(
            {
                "type": (
                    "conversation.item.input_audio_transcription.completed"
                ),
                "event_id": f"event-{item_id}",
                "item_id": item_id,
                "transcript": "run tests",
            }
        )

    first = await anext(events)
    second = await anext(events)
    assert first.data["text"] == second.data["text"] == "run tests"
    assert first.correlation_id == "item-one"
    assert second.correlation_id == "item-two"
    await session.close()


@pytest.mark.asyncio
async def test_provider_auto_response_is_cancelled_without_output_leak(
    monkeypatch,
):
    session, socket = await connect_session(monkeypatch)
    events = session.events()
    await anext(events)

    socket.feed(
        {
            "type": "response.created",
            "event_id": "auto-created",
            "response": {"id": "response-auto"},
        }
    )
    socket.feed(
        {
            "type": "response.audio_transcript.delta",
            "event_id": "auto-text",
            "delta": "must not leak",
        }
    )
    socket.feed(
        {
            "type": "response.audio.delta",
            "event_id": "auto-audio",
            "delta": base64.b64encode(b"must not play").decode(),
        }
    )
    socket.feed(
        {
            "type": "response.done",
            "event_id": "auto-done",
            "response": {"id": "response-auto", "status": "cancelled"},
        }
    )

    started = await anext(events)
    finished = await anext(events)
    assert started.kind == "response.started"
    assert finished.kind == "response.finished"
    assert (
        started.response_origin == finished.response_origin == "provider_auto"
    )
    await eventually(lambda: socket.sent[-1]["type"] == "response.cancel")
    assert session._events.empty()
    await session.close()


@pytest.mark.asyncio
async def test_application_response_is_the_only_output_source(monkeypatch):
    session, socket = await connect_session(monkeypatch)
    events = session.events()
    await anext(events)
    presentation = await start_application_response(session, socket)
    [request_item] = [
        payload["item"]
        for payload in socket.sent
        if payload["type"] == "conversation.item.create"
    ]
    assert request_item["role"] == "user"
    assert [block["text"] for block in request_item["content"]] == [
        "authoritative state"
    ]

    socket.feed(
        {
            "type": "response.output_item.added",
            "event_id": "output-item",
            "item": {"id": "assistant-output", "role": "assistant"},
        }
    )

    socket.feed(
        {
            "type": "response.audio_transcript.delta",
            "event_id": "text",
            "delta": "accepted",
        }
    )
    socket.feed(
        {
            "type": "response.audio.delta",
            "event_id": "audio",
            "delta": base64.b64encode(b"pcm").decode(),
        }
    )
    socket.feed(
        {
            "type": "response.audio_transcript.done",
            "event_id": "text-done",
            "transcript": "accepted",
        }
    )
    socket.feed(
        {
            "type": "response.done",
            "event_id": "done",
            "response": {"id": "response-app", "status": "completed"},
        }
    )
    await finish_presentation(socket, presentation)
    deleted = {
        payload["item_id"]
        for payload in socket.sent
        if payload["type"] == "conversation.item.delete"
    }
    assert "assistant-output" in deleted

    received = [await anext(events) for _ in range(7)]
    assert [event.kind for event in received] == [
        "response.started",
        "output.started",
        "output_transcript.partial",
        "output.audio",
        "output_transcript.final",
        "output.stopped",
        "response.finished",
    ]
    assert received[3].audio == b"pcm"
    assert all(event.response_origin == "application" for event in received)
    await session.close()


@pytest.mark.asyncio
async def test_application_response_returns_its_final_transcript(monkeypatch):
    session, socket = await connect_session(monkeypatch)
    await anext(session.events())

    message = asyncio.create_task(session.create_message("user", "你好"))
    await acknowledge_item(socket, 0)
    await message
    response = asyncio.create_task(session.request_response())
    await eventually(lambda: socket.sent[-1]["type"] == "response.create")
    socket.feed(
        {
            "type": "response.created",
            "event_id": "response-created",
            "response": {"id": "response-text"},
        }
    )
    socket.feed(
        {
            "type": "response.audio_transcript.delta",
            "event_id": "delta-1",
            "delta": "你好，",
        }
    )
    socket.feed(
        {
            "type": "response.audio_transcript.delta",
            "event_id": "delta-2",
            "delta": "很高兴见到你。",
        }
    )
    socket.feed(
        {
            "type": "response.audio_transcript.done",
            "event_id": "transcript-done",
            "transcript": "你好，很高兴见到你。",
        }
    )
    socket.feed(
        {
            "type": "response.done",
            "event_id": "response-done",
            "response": {"id": "response-text", "status": "completed"},
        }
    )

    assert (await response).transcript == "你好，很高兴见到你。"
    await session.close()


@pytest.mark.asyncio
async def test_item_commands_are_acknowledged_between_responses(
    monkeypatch,
):
    session, socket = await connect_session(monkeypatch)
    events = session.events()
    await anext(events)
    first = await start_application_response(session, socket)

    async def second_sequence() -> None:
        item = await session.create_message("user", "second state")
        result = await session.request_response()
        await session.delete_items({item, *result.item_ids})

    socket.feed(
        {
            "type": "response.done",
            "event_id": "first-done",
            "response": {"id": "response-app", "status": "completed"},
        }
    )
    assert (await anext(events)).kind == "response.started"
    assert (await anext(events)).kind == "response.finished"
    await eventually(
        lambda: any(
            item["type"] == "conversation.item.delete" for item in socket.sent
        )
    )

    second = asyncio.create_task(second_sequence())
    await asyncio.sleep(0)
    assert (
        len(
            [
                item
                for item in socket.sent
                if item["type"] == "conversation.item.create"
            ]
        )
        == 1
    )

    await finish_presentation(socket, first)
    await acknowledge_item(socket, 1)
    await eventually(
        lambda: (
            len(
                [
                    item
                    for item in socket.sent
                    if item["type"] == "response.create"
                ]
            )
            == 2
        )
    )
    socket.feed(
        {
            "type": "response.created",
            "event_id": "second-created",
            "response": {"id": "response-second"},
        }
    )
    socket.feed(
        {
            "type": "response.done",
            "event_id": "second-done",
            "response": {"id": "response-second", "status": "completed"},
        }
    )
    await finish_presentation(socket, second)
    await session.close()


@pytest.mark.asyncio
async def test_speech_started_interrupts_application_output(monkeypatch):
    session, socket = await connect_session(monkeypatch)
    events = session.events()
    await anext(events)
    presentation = await start_application_response(session, socket)
    assert (await anext(events)).response_origin == "application"

    socket.feed(
        {
            "type": "input_audio_buffer.speech_started",
            "event_id": "speech",
        },
    )
    speech = await anext(events)
    assert speech.kind == "speech.started"
    assert not any(item["type"] == "response.cancel" for item in socket.sent)
    socket.feed(
        {
            "type": "response.done",
            "event_id": "cancelled",
            "response": {"id": "response-app", "status": "cancelled"},
        }
    )
    assert (await anext(events)).kind == "response.finished"
    await finish_presentation(socket, presentation)
    assert not any(item["type"] == "response.cancel" for item in socket.sent)
    await session.close()


@pytest.mark.asyncio
async def test_barge_in_uses_explicit_cancel_only_as_timeout_fallback(
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.providers.realtime_voice.dashscope."
        "_BARGE_IN_CANCEL_FALLBACK_SECONDS",
        0,
    )
    session, socket = await connect_session(monkeypatch)
    events = session.events()
    await anext(events)
    presentation = await start_application_response(session, socket)
    assert (await anext(events)).kind == "response.started"

    socket.feed(
        {
            "type": "input_audio_buffer.speech_started",
            "event_id": "speech",
        },
    )
    assert (await anext(events)).kind == "speech.started"
    await eventually(
        lambda: any(item["type"] == "response.cancel" for item in socket.sent)
    )
    socket.feed(
        {
            "type": "response.done",
            "event_id": "cancelled",
            "response": {"id": "response-app", "status": "cancelled"},
        }
    )
    assert (await anext(events)).kind == "response.finished"
    await finish_presentation(socket, presentation)
    await session.close()


@pytest.mark.asyncio
async def test_audio_turn_items_are_deleted_before_next_presentation(
    monkeypatch,
):
    session, socket = await connect_session(monkeypatch)
    events = session.events()
    await anext(events)

    socket.feed(
        {
            "type": "input_audio_buffer.speech_started",
            "event_id": "speech",
            "item_id": "audio-input",
        },
    )
    socket.feed(
        {
            "type": "conversation.item.created",
            "event_id": "input-created",
            "item": {"id": "audio-input", "role": "user"},
        }
    )
    socket.feed(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "event_id": "transcript",
            "item_id": "audio-input",
            "transcript": "new request",
        }
    )
    socket.feed(
        {
            "type": "response.created",
            "event_id": "auto-created",
            "response": {"id": "response-auto"},
        }
    )
    socket.feed(
        {
            "type": "response.output_item.added",
            "event_id": "auto-output",
            "item": {"id": "auto-assistant", "role": "assistant"},
        }
    )
    socket.feed(
        {
            "type": "response.done",
            "event_id": "auto-done",
            "response": {"id": "response-auto", "status": "cancelled"},
        }
    )

    assert (await anext(events)).kind == "speech.started"
    assert (await anext(events)).kind == "input_transcript.final"
    assert (await anext(events)).response_origin == "provider_auto"
    assert (await anext(events)).kind == "response.finished"
    deleted: set[str] = set()
    for _attempt in range(100):
        for payload in socket.sent:
            if payload["type"] != "conversation.item.delete":
                continue
            item_id = payload["item_id"]
            if item_id in deleted:
                continue
            deleted.add(item_id)
            socket.feed(
                {
                    "type": "conversation.item.deleted",
                    "event_id": f"deleted-{item_id}",
                    "item_id": item_id,
                }
            )
        if session._presentation_ready.is_set():
            break
        await asyncio.sleep(0)

    assert deleted == {"audio-input", "auto-assistant"}
    assert session._presentation_ready.is_set()
    await session.close()


@pytest.mark.asyncio
async def test_older_turn_cleanup_cannot_unlock_a_newer_speech_turn(
    monkeypatch,
):
    session, _socket = await connect_session(monkeypatch)
    session._presentation_ready.clear()
    session._active_input_turn = 2
    session._input_turns = {
        1: _InputTurnState(cleanup_scheduled=True),
        2: _InputTurnState(cleanup_scheduled=True),
    }

    await session._cleanup_input_turn(1, set())
    assert not session._presentation_ready.is_set()

    await session._cleanup_input_turn(2, set())
    assert session._presentation_ready.is_set()
    await session.close()


@pytest.mark.asyncio
async def test_native_turn_cannot_unlock_presentation_while_another_call_pending():
    session = DashScopeRealtimeSession(config(), "unused")
    session._session_config = RealtimeSessionConfig(
        instructions="native",
        delegation_tool=RealtimeDelegationTool(),
    )
    session._presentation_ready.clear()
    session._input_turns = {
        1: _InputTurnState(
            transcript_final=True,
            auto_response_terminal=True,
            pending_call_ids={"call-1"},
        ),
        2: _InputTurnState(
            transcript_final=True,
            auto_response_terminal=True,
        ),
    }
    try:
        session._schedule_input_cleanup_if_ready(2)
        assert not session._presentation_ready.is_set()

        session._input_turns[1].pending_call_ids.clear()
        session._schedule_input_cleanup_if_ready(1)
        assert session._presentation_ready.is_set()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_deleting_an_item_already_removed_by_provider_is_idempotent(
    monkeypatch,
):
    session, socket = await connect_session(monkeypatch)
    events = session.events()
    await anext(events)

    deletion = asyncio.create_task(session.delete_items({"missing-item"}))
    await eventually(
        lambda: any(
            payload.get("type") == "conversation.item.delete"
            and payload.get("item_id") == "missing-item"
            for payload in socket.sent
        )
    )
    socket.feed(
        {
            "type": "error",
            "event_id": "already-removed",
            "error": {
                "code": "invalid_value",
                "message": "Cannot find item with id: missing-item",
            },
        }
    )

    await asyncio.wait_for(deletion, timeout=1)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(events), timeout=0.01)
    await session.close()


@pytest.mark.asyncio
async def test_busy_server_vad_response_is_not_retried(monkeypatch):
    session, socket = await connect_session(monkeypatch)
    events = session.events()
    await anext(events)
    presentation = await start_application_response(session, socket)
    assert (await anext(events)).kind == "response.started"
    response_create_count = len(
        [item for item in socket.sent if item["type"] == "response.create"]
    )

    socket.feed(
        {
            "type": "error",
            "event_id": "busy",
            "error": {
                "code": "invalid_value",
                "param": "response.create",
                "message": "automatic response is busy",
            },
        }
    )
    socket.feed(
        {
            "type": "response.done",
            "event_id": "done",
            "response": {"id": "response-app", "status": "completed"},
        }
    )
    assert (await anext(events)).kind == "response.finished"
    await finish_presentation(socket, presentation)
    await asyncio.sleep(0)
    assert (
        len(
            [item for item in socket.sent if item["type"] == "response.create"]
        )
        == response_create_count
    )
    await session.close()


@pytest.mark.asyncio
async def test_idle_timeout_is_an_expected_session_close(monkeypatch):
    session, socket = await connect_session(monkeypatch)
    events = session.events()
    await anext(events)

    socket.feed(
        {
            "type": "error",
            "event_id": "idle-timeout",
            "error": {
                "code": "response_idle_timeout",
                "message": "The idle realtime session was closed.",
            },
        }
    )

    event = await asyncio.wait_for(anext(events), timeout=1)
    assert event.kind == "session.closed"
    assert event.data == {
        "reason": "idle_timeout",
        "recoverable": True,
    }
    assert session._expected_close_reason == "idle_timeout"
    await session.close()
