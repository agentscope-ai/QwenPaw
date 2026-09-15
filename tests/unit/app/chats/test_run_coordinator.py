import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from qwenpaw.app.chats.models import ChatSpec, SessionSource
from qwenpaw.app.chats.run_coordinator import (
    ChatInputRequest,
    ChatRunCoordinator,
)
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.chats.timeline import ChatTimelineJournal
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.constant import (
    QWENPAW_CLIENT_MESSAGE_ID_KEY,
    QWENPAW_RECEIVED_AT_KEY,
)
from qwenpaw.schemas import ImageContent, TextContent


class FakeConsoleChannel:
    def __init__(self) -> None:
        self.payload = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def stream_one(self, payload):
        self.payload = payload
        self.started.set()
        await self.release.wait()
        yield 'data: {"object":"response","status":"completed"}\n\n'


class FakeChannelManager:
    def __init__(self, channel) -> None:
        self.channel = channel

    async def get_channel(self, channel_id):
        return self.channel if channel_id == "console" else None


def workspace(tmp_path, channel):
    return SimpleNamespace(
        agent_id="default",
        workspace_dir=tmp_path,
        task_tracker=TaskTracker(),
        channel_manager=FakeChannelManager(channel),
        session=SafeJSONSession(str(tmp_path)),
    )


def chat() -> ChatSpec:
    return ChatSpec(
        id="chat-1",
        name="Existing Voice Chat",
        session_id="realtime_voice:chat-1",
        user_id="local-single-user",
        channel="console",
        source=SessionSource.realtime_voice,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("constraint_action", ["STATUS", "FOLLOW_UP"])
async def test_later_constraint_is_visible_during_bridge_preparation(tmp_path, monkeypatch, constraint_action):
    from qwenpaw.app.realtime_voice.task_bridge import VoiceTaskBridge
    from qwenpaw.app.realtime_voice.contracts import DelegateVoiceAction, FollowUpVoiceAction, StatusVoiceAction
    from unittest.mock import AsyncMock

    channel = FakeConsoleChannel()
    owner = workspace(tmp_path, channel)
    bridge = VoiceTaskBridge(owner, chat())
    bridge._attach_observer = AsyncMock()
    entered, release = asyncio.Event(), asyncio.Event()
    original_payload = ChatRunCoordinator._console_payload

    async def delayed_payload(workspace, chat_spec, request):
        if request.text() == "Correction: 302":
            entered.set()
            await release.wait()
        return await original_payload(workspace, chat_spec, request)

    monkeypatch.setattr(ChatRunCoordinator, "_console_payload", delayed_payload)
    try:
        first = await bridge.enqueue_action(DelegateVoiceAction("Print 3002"), idempotency_key="s1")
        receipt = await first.wait()
        await asyncio.wait_for(channel.started.wait(), 1)
        current = channel.payload["meta"]["request_context"]
        mailbox = current["_run_input_mailbox"]
        second = await bridge.enqueue_action(FollowUpVoiceAction(receipt.task_ref, "Correction: 302"), idempotency_key="s2")
        await asyncio.wait_for(entered.wait(), 1)
        action = (StatusVoiceAction(receipt.task_ref) if constraint_action == "STATUS"
                  else FollowUpVoiceAction(receipt.task_ref, "Do not rerun"))
        bridge.observe_input("s3", "Do not rerun", action)
        assert not second.completion.done()
        assert mailbox.drain_after_reply() == []
        during_prepare = json.loads(mailbox.input_context.capture((receipt.task_id,)))
        assert [r["text"] for r in during_prepare["inputs"]] == ["Print 3002", "Correction: 302", "Do not rerun"]
        assert during_prepare["inputs"][1]["kind"] == "related_input"
        release.set()
        await second.wait()
        correction = mailbox.drain_after_reply()[0]
        after_admission = json.loads(mailbox.input_context.capture((correction.idempotency_key,)))
        assert [r["text"] for r in after_admission["inputs"]] == ["Print 3002", "Correction: 302", "Do not rerun"]
        assert after_admission["inputs"][1]["kind"] == "active_input"
        assert mailbox.drain_after_reply() == []
    finally:
        release.set()
        channel.release.set()
        await owner.task_tracker.request_stop(chat().id)
        await bridge.close()


@pytest.mark.asyncio
async def test_live_conversation_observes_accepted_input_and_public_reply(
    tmp_path,
):
    from agentscope.message import Msg, TextBlock

    channel = FakeConsoleChannel()
    owner = workspace(tmp_path, channel)
    journal = ChatTimelineJournal(owner, chat())
    view = journal.conversation_view()
    try:
        await ChatRunCoordinator.submit(
            owner,
            chat(),
            ChatInputRequest(
                content_parts=(TextContent(text="keyboard question"),),
                client_message_id="keyboard-1",
                origin="keyboard",
            ),
        )
        await asyncio.wait_for(channel.started.wait(), 1)
        cycle = channel.payload["meta"]["request_context"][
            "_reply_cycle_context"
        ]
        for index in range(2):
            cycle.reply_content_changed(
                Msg(
                    id="shared",
                    name="assistant",
                    role="assistant",
                    content=[
                        TextBlock(
                            id=str(index),
                            text=f"answer-{index}",
                            metadata={
                                "run_id": cycle.run_id,
                                "responds_to_input_ids": ["keyboard-1"],
                                "timeline_order": index + 2,
                                "reply_phase": "final",
                            },
                        )
                    ],
                )
            )
        assert [item.text for item in view._ordered()] == [
            "keyboard question",
            "answer-0",
            "answer-1",
        ]
    finally:
        channel.release.set()
        await owner.task_tracker.request_stop(chat().id)


@pytest.fixture(autouse=True)
def project_resolution(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "qwenpaw.app.chats.run_coordinator.load_agent_config",
        lambda _agent_id: SimpleNamespace(project_dir=None),
    )
    monkeypatch.setattr(
        "qwenpaw.app.chats.run_coordinator.resolve_effective_project_dir",
        lambda *_args: (tmp_path, "workspace"),
    )


@pytest.mark.asyncio
async def test_starts_agent_without_losing_rich_input(tmp_path):
    channel = FakeConsoleChannel()
    owner = workspace(tmp_path, channel)
    request = ChatInputRequest(
        content_parts=(
            TextContent(text="describe this"),
            ImageContent(image_url="file:///tmp/example.png"),
        ),
        client_message_id="client-1",
        message_metadata={"trace_id": "trace-1"},
        request_context={"approval_level": "always"},
        model_slot_override={"provider_id": "test", "model": "model-1"},
        origin="keyboard",
    )

    result = await ChatRunCoordinator.submit(owner, chat(), request)
    await asyncio.wait_for(channel.started.wait(), timeout=1)

    assert result.status == "started"
    assert result.run_id
    assert result.input_id == "client-1"
    assert channel.payload["message_metadata"] == {
        QWENPAW_CLIENT_MESSAGE_ID_KEY: "client-1",
        "trace_id": "trace-1",
        "timeline_order": 1,
        QWENPAW_RECEIVED_AT_KEY: channel.payload["message_metadata"][
            QWENPAW_RECEIVED_AT_KEY
        ],
    }
    assert channel.payload["content_parts"] == list(request.content_parts)
    assert (
        channel.payload["model_slot_override"] == request.model_slot_override
    )
    context = channel.payload["meta"]["request_context"]
    assert context["approval_level"] == "always"
    assert context["input_origin"] == "keyboard"
    assert context["source"] == "realtime_voice"
    assert context["project_dir_source"] == "workspace"

    stream = owner.task_tracker.stream_from_queue(result.events, "chat-1")
    initial_user = json.loads((await anext(stream)).removeprefix("data: "))
    assert initial_user["id"] == "client-1"
    assert [part["type"] for part in initial_user["content"]] == [
        "text",
        "image",
    ]
    channel.release.set()
    assert "completed" in await anext(stream)
    await stream.aclose()


@pytest.mark.asyncio
async def test_atomically_steers_active_run_with_the_same_typed_input(
    tmp_path,
):
    channel = FakeConsoleChannel()
    owner = workspace(tmp_path, channel)
    first = await ChatRunCoordinator.submit(
        owner,
        chat(),
        ChatInputRequest(
            content_parts=(TextContent(text="先检查项目"),),
            client_message_id="client-1",
            origin="speech",
        ),
    )
    await asyncio.wait_for(channel.started.wait(), timeout=1)
    second_request = ChatInputRequest(
        content_parts=(TextContent(text="再截取桌面"),),
        client_message_id="client-2",
        request_context={"trace_id": "trace-2"},
        model_slot_override={"provider_id": "test", "model": "model-2"},
        origin="keyboard",
    )
    second = await ChatRunCoordinator.submit(owner, chat(), second_request)

    assert first.status == "started"
    assert second.status == "accepted"
    assert second.run_id == first.run_id
    assert second.input_id == "client-2"
    mailbox = channel.payload["meta"]["request_context"]["_run_input_mailbox"]
    [steer] = mailbox.drain_after_reply()
    assert steer.content_parts == second_request.content_parts
    assert steer.message_metadata == {
        QWENPAW_CLIENT_MESSAGE_ID_KEY: "client-2",
        "timeline_order": 2,
        QWENPAW_RECEIVED_AT_KEY: steer.message_metadata[
            QWENPAW_RECEIVED_AT_KEY
        ],
    }
    assert steer.timeline_order == 2
    assert steer.request_context["trace_id"] == "trace-2"
    assert steer.request_context["input_origin"] == "keyboard"
    assert steer.model_slot_override == second_request.model_slot_override

    stream = owner.task_tracker.stream_from_queue(first.events, "chat-1")
    _ = await anext(stream)
    user_event = json.loads((await anext(stream)).removeprefix("data: "))
    assert user_event["id"] == "client-2"
    assert user_event["content"][0]["text"] == "再截取桌面"
    from qwenpaw.runtime.message_convert import _request_input_to_msgs
    from qwenpaw.schemas import Message
    from qwenpaw.app.chats.utils import agentscope_msg_to_message

    [stored] = _request_input_to_msgs(
        [
            Message(
                role="user",
                content=list(steer.content_parts),
                metadata=steer.message_metadata,
            )
        ]
    )
    received_at = steer.message_metadata[QWENPAW_RECEIVED_AT_KEY]
    assert stored.created_at == received_at
    assert stored.content[0].created_at == received_at
    assert (
        user_event["created_at"]
        == datetime.fromisoformat(received_at).timestamp()
    )
    [visible] = agentscope_msg_to_message(stored)
    assert datetime.fromisoformat(
        visible.metadata["timestamp"]
    ).timestamp() == (user_event["created_at"])
    await stream.aclose()
    await owner.task_tracker.detach_subscriber("chat-1", second.events)
    await owner.task_tracker.request_stop("chat-1")
