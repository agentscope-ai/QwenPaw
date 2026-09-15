import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.chats.timeline import (
    ChatTimelineJournal,
    order_timeline_messages,
    pending_timeline_messages,
)
from qwenpaw.app.chats.utils import agentscope_msg_to_message
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.schemas import Message, Role, TextContent


def build_journal(tmp_path):
    chat = SimpleNamespace(
        id="chat-1",
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    workspace = SimpleNamespace(
        session=SafeJSONSession(str(tmp_path)),
        task_tracker=TaskTracker(),
        chat_manager=SimpleNamespace(touch_chat=AsyncMock()),
    )
    return ChatTimelineJournal(workspace, chat), workspace, chat


@pytest.mark.asyncio
async def test_query_target_survives_duplicate_save_and_reconciliation(
    tmp_path,
):
    journal, workspace, chat = build_journal(tmp_path)
    order = await journal.reserve_order()
    for _ in range(2):
        await journal.append_voice_exchange(
            "query",
            "旧工作怎么样了？",
            timeline_order=order,
            query_target_input_ids=("original-input",),
        )
    pending = pending_timeline_messages(
        await workspace.session.get_session_state_dict(
            chat.session_id,
            chat.user_id,
            chat.channel,
        ),
    )
    assert len(pending) == 1
    assert pending[0].id == "query"
    assert pending[0].metadata["query_target_input_ids"] == ["original-input"]
    assert await journal.reconcile() == 1
    await journal.append_voice_exchange(
        "query",
        "旧工作怎么样了？",
        "查询的部分回答",
        timeline_order=order,
        generation_status="cancelled",
        query_target_input_ids=("original-input",),
    )
    assert await journal.reconcile() == 1
    restored = SafeJSONSession(str(tmp_path))
    state = await restored.get_session_state_dict(
        chat.session_id,
        chat.user_id,
        chat.channel,
    )
    messages = AgentState.model_validate(state["agent"]["state"]).context
    assert [message.id for message in messages] == ["query", "query_assistant"]
    assert messages[0].metadata["query_target_input_ids"] == ["original-input"]
    assert "query_target_input_ids" not in messages[1].metadata
    assert messages[1].metadata["responds_to_input_ids"] == ["query"]
    fresh, _, _ = build_journal(tmp_path)
    live = await journal.read_context(max_turns=1, max_chars=2000)
    cold = await fresh.read_context(max_turns=1, max_chars=2000)
    assert cold == live
    await journal.conversation_view().close()
    await fresh.conversation_view().close()


@pytest.mark.asyncio
async def test_early_voice_input_then_cancelled_generation_survives_reload(
    tmp_path,
):
    journal, workspace, chat = build_journal(tmp_path)
    order = await journal.reserve_order()
    early = await journal.append_voice_exchange(
        "spoken", "question", timeline_order=order
    )
    assert await journal.reconcile() == 1
    completed = await journal.append_voice_exchange(
        "spoken",
        "question",
        "partial answer",
        timeline_order=order,
        generation_status="cancelled",
    )
    await journal.reconcile()
    reloaded = SafeJSONSession(str(tmp_path))
    state = await reloaded.get_session_state_dict(
        chat.session_id, chat.user_id, chat.channel
    )
    messages = AgentState.model_validate(state["agent"]["state"]).context
    assert [msg.id for msg in messages] == ["spoken", "spoken_assistant"]
    assert messages[-1].metadata["voice_generation_status"] == "cancelled"
    assert messages[-1].get_text_content() == "partial answer"
    restored = agentscope_msg_to_message(messages)
    assert early[0].id == completed[0].id == restored[0].id
    assert completed[1].id == restored[1].id


@pytest.mark.asyncio
async def test_journal_reconciles_voice_exchange_into_agent_context(tmp_path):
    journal, workspace, chat = build_journal(tmp_path)

    order = await journal.reserve_order()
    visible = await journal.append_voice_exchange(
        "turn-1",
        "你好",
        "你好呀",
        timeline_order=order,
    )
    assert [message.role for message in visible] == ["user", "assistant"]
    pending_state = await workspace.session.get_session_state_dict(
        chat.session_id,
        chat.user_id,
        chat.channel,
    )
    assert [
        msg.get_text_content()
        for msg in pending_timeline_messages(pending_state)
    ] == [
        "你好",
        "你好呀",
    ]

    assert await journal.reconcile() == 2
    state = await workspace.session.get_session_state_dict(
        chat.session_id,
        chat.user_id,
        chat.channel,
    )
    agent_state = AgentState.model_validate(state["agent"]["state"])
    assert [msg.get_text_content() for msg in agent_state.context] == [
        "你好",
        "你好呀",
    ]
    assert state["chat_timeline"] == {"next_order": 2}


@pytest.mark.asyncio
async def test_journal_append_is_idempotent_by_turn(tmp_path):
    journal, workspace, chat = build_journal(tmp_path)

    order = await journal.reserve_order()
    await journal.append_voice_exchange(
        "turn-1", "你好", "你好呀", timeline_order=order
    )
    await journal.append_voice_exchange(
        "turn-1", "你好", "你好呀", timeline_order=order
    )

    state = await workspace.session.get_session_state_dict(
        chat.session_id,
        chat.user_id,
        chat.channel,
    )
    pending = pending_timeline_messages(state)
    assert [message.id for message in pending] == [
        "turn-1",
        "turn-1_assistant",
    ]


@pytest.mark.asyncio
async def test_reconcile_waits_until_active_chat_run_finishes(tmp_path):
    journal, workspace, chat = build_journal(tmp_path)
    release = asyncio.Event()

    async def run(_payload):
        await release.wait()
        yield "data: done\n\n"

    await workspace.task_tracker.attach_or_start(chat.id, None, run)
    order = await journal.reserve_order()
    await journal.append_voice_exchange(
        "turn-1", "你好", "你好呀", timeline_order=order
    )
    reconcile = asyncio.create_task(journal.reconcile())
    await asyncio.sleep(0)
    assert not reconcile.done()

    release.set()
    assert await asyncio.wait_for(reconcile, timeout=1) == 2


@pytest.mark.asyncio
async def test_order_reservations_are_atomic_and_monotonic(tmp_path):
    journal, _workspace, _chat = build_journal(tmp_path)

    orders = await asyncio.gather(
        *(journal.reserve_order() for _ in range(20))
    )

    assert sorted(orders) == list(range(1, 21))


@pytest.mark.asyncio
async def test_journal_recovers_from_invalid_timeline_state(tmp_path):
    journal, workspace, chat = build_journal(tmp_path)

    await workspace.session.mutate_session_state(
        chat.session_id,
        lambda state: state.update({"chat_timeline": "invalid"}),
        chat.user_id,
        chat.channel,
    )

    order = await journal.reserve_order()
    await journal.append_voice_exchange(
        "turn-1",
        "你好",
        timeline_order=order,
    )

    state = await workspace.session.get_session_state_dict(
        chat.session_id,
        chat.user_id,
        chat.channel,
    )
    assert state["chat_timeline"]["next_order"] == 2
    assert [message.id for message in pending_timeline_messages(state)] == [
        "turn-1"
    ]


@pytest.mark.asyncio
async def test_reserve_order_seeds_from_content_block_occurrences(tmp_path):
    journal, workspace, chat = build_journal(tmp_path)

    def seed_agent_state(state):
        agent_state = AgentState(
            session_id=chat.session_id,
            context=[
                Msg(
                    name="assistant",
                    role="assistant",
                    content=[
                        TextBlock(
                            text="late output",
                            metadata={"timeline_order": 8},
                        ),
                    ],
                ),
            ],
        )
        state["agent"] = {"state": agent_state.model_dump(mode="json")}

    await workspace.session.mutate_session_state(
        chat.session_id,
        seed_agent_state,
        chat.user_id,
        chat.channel,
    )

    assert await journal.reserve_order() == 9


@pytest.mark.asyncio
async def test_reconcile_inserts_voice_before_later_agent_group(tmp_path):
    journal, workspace, chat = build_journal(tmp_path)
    voice_order = await journal.reserve_order()
    await journal.append_voice_exchange(
        "voice-1",
        "任务状态怎么样",
        "还在处理中。",
        timeline_order=voice_order,
    )
    agent_order = await journal.reserve_order()

    def add_later_agent_message(state):
        agent_state = AgentState(
            session_id=chat.session_id,
            context=[
                Msg(
                    id="agent-input",
                    name="user",
                    role="user",
                    content=[TextBlock(type="text", text="继续运行测试")],
                    metadata={"timeline_order": agent_order},
                )
            ],
        )
        state["agent"] = {"state": agent_state.model_dump(mode="json")}

    await workspace.session.mutate_session_state(
        chat.session_id,
        add_later_agent_message,
        chat.user_id,
        chat.channel,
    )

    assert await journal.reconcile() == 2
    state = await workspace.session.get_session_state_dict(
        chat.session_id,
        chat.user_id,
        chat.channel,
    )
    context = AgentState.model_validate(state["agent"]["state"]).context
    assert [message.id for message in context] == [
        "voice-1",
        "voice-1_assistant",
        "agent-input",
    ]


def test_occurrence_order_interleaves_late_output_with_voice_exchange():
    def runtime_message(text: str, order: int) -> Message:
        message = Message(role=Role.ASSISTANT)
        message.content = [TextContent(text=text)]
        message.metadata = {"metadata": {"timeline_order": order}}
        return message

    ordered = order_timeline_messages(
        [
            runtime_message("task started", 2),
            runtime_message("task finished", 5),
            runtime_message("still running", 3),
            runtime_message("follow-up accepted", 4),
        ],
    )

    assert [message.content[0].text for message in ordered] == [
        "task started",
        "still running",
        "follow-up accepted",
        "task finished",
    ]


def test_durable_block_occurrences_interleave_with_voice_messages():
    agent_reply = Msg(
        name="assistant",
        role="assistant",
        metadata={
            "run_id": "run-1",
            "timeline_group_id": "task-1",
            "timeline_revision": 1,
        },
        content=[
            TextBlock(
                text="任务已开始",
                metadata={"timeline_order": 2},
            ),
            TextBlock(
                text="任务已完成",
                metadata={"timeline_order": 5},
            ),
        ],
    )
    voice_status = Msg(
        name="QwenPaw Voice",
        role="assistant",
        content=[TextBlock(text="任务仍在运行")],
        metadata={"timeline_order": 3},
    )
    voice_follow_up = Msg(
        name="QwenPaw Voice",
        role="assistant",
        content=[TextBlock(text="补充要求已接收")],
        metadata={"timeline_order": 4},
    )

    projected = agentscope_msg_to_message(
        [agent_reply, voice_status, voice_follow_up],
    )
    ordered = order_timeline_messages(projected)

    assert [message.content[0].text for message in ordered] == [
        "任务已开始",
        "任务仍在运行",
        "补充要求已接收",
        "任务已完成",
    ]
