import asyncio

from qwenpaw.runtime_status.stream_events import emit_stream_event_status
from qwenpaw.runtime_status.stream_events import emit_runtime_final_status
from qwenpaw.runtime_status.stream_events import stream_with_runtime_status


def test_terminal_stream_event_clears_runtime_status_before_yield():
    emitted: list[dict] = []

    seen_first_event = emit_stream_event_status(
        lambda **payload: emitted.append(payload),
        session_id="session-1",
        root_session_id="root-1",
        chat_id="chat-1",
        seen_first_event=False,
        last=True,
    )

    assert seen_first_event is True
    assert [item["stage"] for item in emitted] == [
        "model_streaming",
        "completed",
    ]
    assert emitted[-1]["status"] == "completed"


def test_non_terminal_stream_event_keeps_runtime_status_running():
    emitted: list[dict] = []

    seen_first_event = emit_stream_event_status(
        lambda **payload: emitted.append(payload),
        session_id="session-1",
        root_session_id="root-1",
        chat_id=None,
        seen_first_event=False,
        last=False,
    )

    assert seen_first_event is True
    assert [item["stage"] for item in emitted] == ["model_streaming"]
    assert emitted[0].get("status", "running") == "running"


def test_closing_stream_clears_runtime_status_without_last_event():
    emitted: list[dict] = []

    async def source():
        yield "response", False

    async def scenario():
        stream = stream_with_runtime_status(
            source(),
            lambda **payload: emitted.append(payload),
            session_id="session-1",
            root_session_id="root-1",
            chat_id="chat-1",
        )
        assert await anext(stream) == ("response", False)
        await stream.aclose()

    asyncio.run(scenario())

    assert [item["stage"] for item in emitted] == [
        "model_streaming",
        "completed",
    ]
    assert emitted[-1]["status"] == "completed"


def test_runtime_finalizer_clears_tool_status_after_success():
    emitted: list[dict] = []

    emit_runtime_final_status(
        lambda **payload: emitted.append(payload),
        session_id="session-1",
        root_session_id="root-1",
        chat_id="chat-1",
        error=None,
    )

    assert emitted == [
        {
            "session_id": "session-1",
            "root_session_id": "root-1",
            "chat_id": "chat-1",
            "stage": "completed",
            "status": "completed",
            "message": "任务已完成。",
        },
    ]
