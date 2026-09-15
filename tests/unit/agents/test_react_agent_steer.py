import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agentscope.agent import Agent, ReActConfig
from agentscope.agent._utils import Exit, Reasoning
from agentscope.event import (
    ReplyEndEvent,
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
)
from agentscope.message import (
    HintBlock,
    Msg,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from agentscope.formatter import DashScopeChatFormatter, OpenAIChatFormatter
from agentscope.model import ChatResponse
from agentscope.tool import FunctionTool, Toolkit

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.manager import ScrollContextManager
from qwenpaw.agents.context.scroll.recall_tool import make_recall_history
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.app.task_tracker import RunInput, RunInputMailbox
from qwenpaw.constant import (
    CHAT_CONVERSATION_CONTEXT_KEY,
    QWENPAW_CLIENT_MESSAGE_ID_KEY,
)
from qwenpaw.loop.gates import StopAction, StopHandlerResult
from qwenpaw.runtime.reply_cycle import (
    InputStateEvent,
    ReplyCycleContext,
    reply_block_metadata,
)
from qwenpaw.schemas import TextContent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "formatter_name", ["OpenAIChatFormatter", "DashScopeChatFormatter"]
)
async def test_model_boundary_reads_updates_without_releasing_queue(
    monkeypatch, formatter_name
):
    import json
    import agentscope.formatter as formatters
    from qwenpaw.app.chats.utils import agentscope_msg_to_message
    from qwenpaw.runtime.input_context import ChatInputContext

    agent = object.__new__(QwenPawAgent)
    mailbox = agent._run_input_mailbox = RunInputMailbox()
    source = mailbox.input_context = ChatInputContext()
    agent._reply_cycle_context = ReplyCycleContext("run", "original")
    agent._context_manager = None
    agent.state = SimpleNamespace(
        context=[],
        reply_id="reply",
        summary="",
        tool_context=SimpleNamespace(activated_groups=[]),
    )
    agent._get_system_prompt = AsyncMock(return_value="Be helpful")
    agent.toolkit = SimpleNamespace(
        get_tool_schemas=AsyncMock(return_value=[])
    )
    agent._inject_pending_hints = AsyncMock()
    agent._model_rejects_media = lambda: False
    agent._model_rejects_audio = lambda: False
    agent._uses_request_time_media_normalization = lambda: False
    source.register_execution("original", "Run and print 3002")
    source.register("correction-source", "Correction: 302", target="original")
    source.bind("correction", "correction-source")
    for i in range(10):
        source.register_execution(f"future-{i}", f"Future job {i}")
        mailbox.submit(
            run_input(f"Future job {i}", f"future-{i}", mode="queue")
        )
    mailbox.submit(run_input("Correction: 302", "correction", mode="queue"))
    source.register(
        "constraint",
        "Do not rerun; only report actual output",
        target="original",
        context_only=True,
    )
    captured = []

    class ModelBoundary(Exception):
        pass

    async def model_boundary(_self, tool_choice=None):
        prepared = await agent._prepare_model_input()
        captured.extend(
            await getattr(formatters, formatter_name)().format(
                prepared["messages"]
            )
        )
        raise ModelBoundary
        yield

    monkeypatch.setattr(Agent, "_reasoning", model_boundary)
    monkeypatch.setattr(
        "qwenpaw.loop.gates.runner.check_pending_gates", lambda _: None
    )
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory._supports_multimodal_for_current_model",
        lambda: True,
    )
    before = agent._reply_cycle_context.snapshot
    with pytest.raises(ModelBoundary):
        async for _ in agent._reasoning():
            pass
    assert agent._reply_cycle_context.snapshot == before
    assert "Do not rerun" in json.dumps(captured)
    assert "Future job" in json.dumps(captured)
    assert "readonly_requests" in json.dumps(captured)
    # The context channel must not publish a second visible user message.
    assert agentscope_msg_to_message(agent.state.context) == []
    assert [
        mailbox.drain_after_reply()[0].idempotency_key for _ in range(10)
    ] == [f"future-{i}" for i in range(10)]
    assert agent._consume_pending_run_inputs() is True
    prepared = await agent._prepare_model_input()
    latest = json.loads(
        prepared["messages"][-1].content[0].hint.split("\n", 1)[1]
    )
    assert [row["source_id"] for row in latest["inputs"]] == [
        "original",
        "correction-source",
        "constraint",
    ]
    assert [row["text"] for row in latest["inputs"]][-2:] == [
        "Correction: 302",
        "Do not rerun; only report actual output",
    ]
    assert mailbox.drain_after_reply() == []
    assert agent._reply_cycle_context.terminated_input_ids("cancelled") == ()
    size = len(agent.state.context)
    again = await agent._prepare_model_input()
    assert len(agent.state.context) == size
    assert (
        again["messages"][-1].content[0].hint
        == prepared["messages"][-1].content[0].hint
    )
    assert not any(
        b.type == "hint" and b.source == "chat_input_context"
        for m in agent.state.context
        for b in m.content
    )


def run_input(
    text: str,
    event_id: str,
    metadata=None,
    mode="steer",
    timeline_order=0,
) -> RunInput:
    return RunInput(
        (TextContent(text=text),),
        event_id,
        metadata,
        mode=mode,
        timeline_order=timeline_order,
    )


def context_agent():
    from qwenpaw.runtime.input_context import ChatInputContext

    agent = object.__new__(QwenPawAgent)
    agent._run_input_mailbox = RunInputMailbox()
    owner = agent._run_input_mailbox.input_context = ChatInputContext()
    owner.register_execution("apple", "Run apple")
    owner.register_execution("banana", "Run banana")
    owner.observe_state(InputStateEvent("run", ("apple",), "processing"))
    owner.observe_state(InputStateEvent("run", ("banana",), "queued"))
    agent._reply_cycle_context = ReplyCycleContext("run", "apple")
    agent._context_manager = None
    agent._get_system_prompt = AsyncMock(return_value="Be helpful")
    agent.toolkit = SimpleNamespace(
        get_tool_schemas=AsyncMock(return_value=[])
    )
    agent.state = SimpleNamespace(
        context=[
            Msg(
                name="user", role="user", content=[TextBlock(text="Run apple")]
            )
        ],
        summary="",
        tool_context=SimpleNamespace(activated_groups=[]),
    )
    return agent


@pytest.mark.asyncio
async def test_request_filters_dynamic_blocks_and_reads_current_revision():
    import json

    agent = context_agent()
    old = HintBlock(source="chat_input_context", hint="OLD_DYNAMIC_FACTS")
    other = HintBlock(source="other_hint", hint="KEEP_OTHER_HINT")
    message = Msg(
        name="assistant",
        role="assistant",
        content=[old, TextBlock(text="KEEP_REAL_TEXT"), other],
    )
    agent.state.context.append(message)
    first = await agent._prepare_model_input()
    assert first["messages"][-2].content == [message.content[1], other]
    assert message.content == [old, message.content[1], other]
    assert "OLD_DYNAMIC_FACTS" not in str(first)
    owner = agent._run_input_mailbox.input_context
    owner.observe_state(InputStateEvent("run", ("banana",), "processing"))
    second = await agent._prepare_model_input()
    view = lambda prepared: json.loads(
        prepared["messages"][-1].content[0].hint.split("\n", 1)[1]
    )
    assert view(first)["readonly_requests"][0]["input_status"] == "queued"
    assert view(second)["readonly_requests"][0]["input_status"] == "processing"
    assert view(second)["revision"] > view(first)["revision"]
    assert agent._reply_cycle_context.snapshot.responds_to_input_ids == (
        "apple",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "formatter_name", ["OpenAIChatFormatter", "DashScopeChatFormatter"]
)
async def test_public_expression_hint_preserves_keyboard_detail_requests(
    formatter_name,
):
    import agentscope.formatter as formatters
    from qwenpaw.runtime.input_context import INPUT_CONTEXT_INSTRUCTION

    agent = context_agent()
    request = (
        "Please explain run_id, admission_status and coverage in detail, "
        "with a table and code."
    )
    agent.state.context[0].content = [TextBlock(text=request)]
    prepared = await agent._prepare_model_input()
    hint = prepared["messages"][-1].content[0].hint
    assert hint.startswith(INPUT_CONTEXT_INSTRUCTION)
    assert "explicitly requests technical or diagnostic details" in hint
    assert (
        "preserve requested depth, tables and code"
        in INPUT_CONTEXT_INSTRUCTION
    )
    formatted = await getattr(formatters, formatter_name)().format(
        prepared["messages"]
    )
    assert request in str(formatted)
    assert agent.state.context[0].content[0].text == request
    assert (
        len(agent.state.context) == 1
    )  # Internal guidance is not a visible reply.


@pytest.mark.asyncio
async def test_real_scroll_counts_view_without_persisting_or_truncating(
    tmp_path,
):
    import json
    from agentscope.formatter import OpenAIChatFormatter
    from qwenpaw.agents.context.scroll.history import HistoryStore
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager
    from qwenpaw.agents.context.types import ContextWindowUnfitError

    history = HistoryStore(tmp_path / "history.db")
    agent = context_agent()
    owner = agent._run_input_mailbox.input_context
    constraint = "Background. " * 2000 + "Do not rerun any task."
    owner.register("query", constraint, context_only=True)
    counted = []

    async def count_tokens(**kwargs):
        encoded = json.dumps(
            await OpenAIChatFormatter().format(kwargs["messages"]),
            ensure_ascii=False,
        )
        counted.append(encoded)
        return len(encoded)

    agent.model = SimpleNamespace(
        context_size=100000, count_tokens=count_tokens
    )
    agent.context_config = SimpleNamespace(
        trigger_ratio=0.8, reserve_ratio=0.5
    )
    try:
        manager = ScrollContextManager(history=history, session_id="probe")
        agent._context_manager = manager
        await manager.compress(agent)
        assert "Run banana" in counted[-1] and constraint in counted[-1]
        assert history.count("probe") == 1
        assert len(agent.state.context) == 1
        agent.state.context = [
            Msg.model_validate(m.model_dump()) for m in agent.state.context
        ]
        restored = ScrollContextManager(history=history, session_id="probe")
        agent._context_manager = restored
        owner.observe_state(InputStateEvent("run", ("banana",), "processing"))
        await restored.compress(agent)
        assert "processing" in counted[-1]
        assert history.count("probe") == 1
        assert await restored._live_tokens(agent) == len(counted[-1])
        agent.model.context_size = 1000
        with pytest.raises(ContextWindowUnfitError):
            await restored.compress(agent)
        assert (
            constraint in counted[-1]
        )  # Never silently trim user constraints.
        assert history.count("probe") == 1
    finally:
        history.close()


def test_busy_agent_consumes_frozen_snapshots_without_extra_input_identity():
    from qwenpaw.constant import CHAT_CONVERSATION_CONTEXT_KEY
    from qwenpaw.app.chats.utils import agentscope_msg_to_message

    mailbox = RunInputMailbox()
    for number, phrase in enumerate(("BLUE_CAT", "RED_CAT")):
        mailbox.submit(
            RunInput(
                (TextContent(text="Print it"),),
                f"input-{number}",
                request_context={
                    CHAT_CONVERSATION_CONTEXT_KEY: phrase,
                    "project_id": "project",
                },
                mode="queue",
            )
        )
    agent = object.__new__(QwenPawAgent)
    agent._run_input_mailbox = mailbox
    agent._context_manager = Mock()
    agent.state = SimpleNamespace(context=[])
    # Queue mode intentionally consumes one input at each reply boundary.
    assert agent._append_pending_run_inputs(activate=False) == ("input-0",)
    assert agent._append_pending_run_inputs(activate=False) == ("input-1",)
    hint1, input1, hint2, input2 = agent.state.context
    assert hint1.content[0].hint.endswith("BLUE_CAT")
    assert hint2.content[0].hint.endswith("RED_CAT")
    assert input1.get_text_content() == input2.get_text_content() == "Print it"
    for msg in (input1, input2):
        assert msg.metadata["request_context"] == {"project_id": "project"}
    assert len(agentscope_msg_to_message(agent.state.context)) == 2
    assert agent._context_manager.on_save.call_count == 4


@pytest.mark.parametrize("mode", ["queue", "steer"])
async def test_busy_agent_preserves_each_target_in_actual_formatter(mode):
    import json
    from agentscope.formatter import (
        DashScopeChatFormatter,
        OpenAIChatFormatter,
    )
    from qwenpaw.constant import CHAT_INPUT_TARGET_KEY
    from qwenpaw.app.chats.utils import agentscope_msg_to_message

    mailbox = RunInputMailbox()
    for number in (1, 2):
        context = {
            CHAT_INPUT_TARGET_KEY: json.dumps(
                {
                    "task_id": f"target-{number}",
                    "task_ref": f"TASK_{number}",
                    "relationship": "follow_up",
                }
            )
        }
        mailbox.submit(
            RunInput(
                (TextContent(text=f"append-{number}"),),
                f"input-{number}",
                {QWENPAW_CLIENT_MESSAGE_ID_KEY: f"input-{number}"},
                request_context=context,
                mode=mode,
            )
        )
        context[CHAT_INPUT_TARGET_KEY] = "MUTATED_AFTER_ADMISSION"
    agent = object.__new__(QwenPawAgent)
    agent._run_input_mailbox = mailbox
    agent._context_manager = Mock()
    agent.state = SimpleNamespace(context=[])
    consumed = agent._append_pending_run_inputs(activate=False)
    if mode == "queue":
        consumed += agent._append_pending_run_inputs(activate=False)
    assert consumed == ("input-1", "input-2")
    assert len(agent.state.context) == 4
    for index, number in enumerate((1, 2)):
        hint, user = agent.state.context[index * 2 : index * 2 + 2]
        assert hint.content[0].type == "hint" and user.id == f"input-{number}"
        assert f"target-{number}" in hint.content[0].hint
        assert f"target-{3 - number}" not in hint.content[0].hint
        assert "request_context" not in user.metadata
        for formatter in (DashScopeChatFormatter(), OpenAIChatFormatter()):
            wire = json.dumps(await formatter.format([hint, user]))
            assert f"target-{number}" in wire and f"append-{number}" in wire
            assert "MUTATED_AFTER_ADMISSION" not in wire
    visible = agentscope_msg_to_message(agent.state.context)
    assert len(visible) == 2 and "target-" not in str(visible)


def test_next_action_advances_queued_input_after_completed_exit(monkeypatch):
    mailbox = RunInputMailbox()
    mailbox.submit(run_input("继续检查测试", "event-1"))
    agent = object.__new__(QwenPawAgent)
    agent._run_input_mailbox = mailbox
    agent._context_manager = None
    previous_final = Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text="旧结果")],
    )
    agent.state = SimpleNamespace(context=[previous_final])
    captured = []

    def base_next_action(_self, final_msg=None):
        captured.append(final_msg)
        if final_msg is not None:
            return Exit(
                exit_msg=final_msg,
                exit_events=[
                    ReplyEndEvent(
                        session_id="s",
                        reply_id="r",
                        finished_reason="completed",
                    )
                ],
            )
        return Reasoning()

    monkeypatch.setattr(Agent, "_next_action", base_next_action)
    assert isinstance(
        QwenPawAgent._next_action(agent, previous_final), Reasoning
    )
    assert captured == [previous_final, None]
    assert len(agent.state.context) == 2
    assert agent.state.context[0] is previous_final
    steered = agent.state.context[1]
    assert steered.role == "user"
    assert steered.content[0].text == "继续检查测试"
    assert steered.metadata["admission_mode"] == "steer"


def test_next_action_closes_mailbox_before_publishing_final(monkeypatch):
    mailbox = RunInputMailbox()
    agent = object.__new__(QwenPawAgent)
    agent._run_input_mailbox = mailbox
    agent._context_manager = None
    agent.state = SimpleNamespace(context=[])
    monkeypatch.setattr(
        Agent,
        "_next_action",
        lambda _self, final_msg=None: Exit(exit_msg=final_msg),
    )
    final = Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text="done")],
    )

    assert isinstance(QwenPawAgent._next_action(agent, final), Exit)
    assert mailbox.submit(run_input("too late", "event-late")) == "closed"


def test_next_action_does_not_insert_steer_before_tool_result(monkeypatch):
    mailbox = RunInputMailbox()
    mailbox.submit(run_input("also inspect the disk", "event-tool"))
    agent = object.__new__(QwenPawAgent)
    agent._run_input_mailbox = mailbox
    agent._context_manager = None
    agent.state = SimpleNamespace(context=[])
    captured = []

    def base_next_action(_self, final_msg=None):
        captured.append(final_msg)
        return "tool"

    monkeypatch.setattr(Agent, "_next_action", base_next_action)

    assert QwenPawAgent._next_action(agent, None) == "tool"
    assert captured == [None]
    assert agent.state.context == []
    assert [
        item.content_parts[0].text for item in mailbox.drain_after_reply()
    ] == [
        "also inspect the disk",
    ]


def test_consume_steer_keeps_each_input_separate_and_ordered():
    mailbox = RunInputMailbox()
    mailbox.submit(run_input("first follow-up", "event-1"))
    mailbox.submit(run_input("second follow-up", "event-2"))
    agent = object.__new__(QwenPawAgent)
    agent._run_input_mailbox = mailbox
    agent._context_manager = None
    agent.state = SimpleNamespace(context=[])

    assert QwenPawAgent._consume_pending_run_inputs(agent) is True
    assert [msg.content[0].text for msg in agent.state.context] == [
        "first follow-up",
        "second follow-up",
    ]
    keys = [msg.metadata["idempotency_key"] for msg in agent.state.context]
    assert keys == ["event-1", "event-2"]


def test_consume_steer_preserves_message_metadata():
    mailbox = RunInputMailbox()
    mailbox.submit(
        run_input(
            "normalized provider request",
            "event-voice",
            {QWENPAW_CLIENT_MESSAGE_ID_KEY: "voice-event"},
        ),
    )
    agent = object.__new__(QwenPawAgent)
    agent._run_input_mailbox = mailbox
    agent._context_manager = None
    agent.state = SimpleNamespace(context=[])

    assert QwenPawAgent._consume_pending_run_inputs(agent) is True
    assert agent.state.context[0].metadata[QWENPAW_CLIENT_MESSAGE_ID_KEY] == (
        "voice-event"
    )


@pytest.mark.asyncio
async def test_reasoning_does_not_advance_input_before_exit_decision(
    monkeypatch,
):
    mailbox = RunInputMailbox()
    agent = object.__new__(QwenPawAgent)
    agent._run_input_mailbox = mailbox
    agent._context_manager = None
    agent._inject_pending_hints = AsyncMock()
    agent._model_rejects_media = lambda: False
    agent._model_rejects_audio = lambda: False
    agent._uses_request_time_media_normalization = lambda: False
    agent._run_stop_handlers = AsyncMock(
        return_value=StopHandlerResult(action=StopAction.TERMINATE)
    )
    agent.state = SimpleNamespace(context=[], reply_id="reply-1")

    final = Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text="completed tool result")],
    )
    start = TextBlockStartEvent(reply_id="reply-1", block_id="block-1")
    delta = TextBlockDeltaEvent(
        reply_id="reply-1",
        block_id="block-1",
        delta="completed tool result",
    )
    end = TextBlockEndEvent(reply_id="reply-1", block_id="block-1")

    async def base_reasoning(_self, tool_choice=None):
        del tool_choice
        agent.state.context.append(final)
        mailbox.submit(run_input("take a screenshot too", "event-2"))
        yield start
        yield delta
        yield end
        yield final

    monkeypatch.setattr(Agent, "_reasoning", base_reasoning)
    monkeypatch.setattr(
        "qwenpaw.loop.gates.runner.check_pending_gates",
        lambda _agent: None,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory._supports_multimodal_for_current_model",
        lambda: True,
    )

    events = [event async for event in QwenPawAgent._reasoning(agent)]

    assert events == [start, delta, end, final]
    assert agent.state.context[0] is final
    assert len(agent.state.context) == 1
    assert [item.idempotency_key for item in mailbox.drain_after_reply()] == [
        "event-2"
    ]


@pytest.mark.asyncio
async def test_reasoning_preserves_cycle_until_exit_boundary(
    monkeypatch,
):
    """Characterize the boundary needed by reply-cycle activation.

    Inputs accepted during one model call remain queued while its text and
    stop handlers finish.  The identity switch belongs to the later confirmed
    Exit decision, not mailbox submission or raw model completion.
    """
    mailbox = RunInputMailbox()
    agent = object.__new__(QwenPawAgent)
    agent._run_input_mailbox = mailbox
    agent._context_manager = None

    async def reserve_order():
        return 6

    agent._reply_cycle_context = ReplyCycleContext(
        "run-1",
        "event-a",
        reserve_order,
    )
    agent._inject_pending_hints = AsyncMock()
    agent._model_rejects_media = lambda: False
    agent._model_rejects_audio = lambda: False
    agent._uses_request_time_media_normalization = lambda: False
    agent._run_stop_handlers = AsyncMock(
        return_value=StopHandlerResult(action=StopAction.TERMINATE)
    )
    agent.state = SimpleNamespace(context=[], reply_id="reply-1")

    final = Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text="answer A")],
    )
    start = TextBlockStartEvent(reply_id="reply-1", block_id="block-a")
    delta = TextBlockDeltaEvent(
        reply_id="reply-1",
        block_id="block-a",
        delta="answer A",
    )
    end = TextBlockEndEvent(reply_id="reply-1", block_id="block-a")
    model_calls = 0

    async def base_reasoning(_self, tool_choice=None):
        nonlocal model_calls
        del tool_choice
        model_calls += 1
        agent.state.context.append(final)
        mailbox.submit(run_input("follow-up B", "event-b"))
        mailbox.submit(run_input("follow-up C", "event-c"))
        yield start
        yield delta
        yield end
        yield final

    monkeypatch.setattr(Agent, "_reasoning", base_reasoning)
    monkeypatch.setattr(
        "qwenpaw.loop.gates.runner.check_pending_gates",
        lambda _agent: None,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory._supports_multimodal_for_current_model",
        lambda: True,
    )

    events = [event async for event in QwenPawAgent._reasoning(agent)]

    assert events == [start, delta, end, final]
    assert model_calls == 1
    assert [msg.content[0].text for msg in agent.state.context] == [
        "answer A",
    ]
    assert agent._reply_cycle_context.snapshot.metadata() == {
        "run_id": "run-1",
        "timeline_group_id": "event-a",
        "timeline_revision": 1,
        "responds_to_input_ids": ["event-a"],
    }
    assert (
        agent._reply_cycle_context.output_snapshot.metadata()["timeline_order"]
        == 6
    )
    assert [item.idempotency_key for item in mailbox.drain_after_reply()] == [
        "event-b",
        "event-c",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["", "   ", '⟦ 任务完成｜echo 输出测试口令"蓝色小猫"｜无后续'])
@pytest.mark.parametrize("pending_work", [False, True])
async def test_empty_public_reply_is_diagnosed_without_retry_or_queue_loss(
    monkeypatch,
    raw,
    pending_work,
):
    from agentscope.state import AgentState
    from qwenpaw.app.chats.utils import agentscope_msg_to_message

    mailbox = RunInputMailbox()
    agent = object.__new__(QwenPawAgent)
    agent.name = "assistant"
    agent._run_input_mailbox = mailbox
    agent._context_manager = None
    agent._inject_pending_hints = AsyncMock()
    agent._model_rejects_media = lambda: False
    agent._model_rejects_audio = lambda: False
    agent._uses_request_time_media_normalization = lambda: False
    agent._run_stop_handlers = AsyncMock(
        return_value=StopHandlerResult(action=StopAction.TERMINATE),
    )
    agent.state = AgentState()
    agent.state.reply_id = "reply-1"
    states = []
    agent._reply_cycle_context = ReplyCycleContext(
        "run-1",
        "event-a",
        on_input_state=states.append,
        has_pending_work=lambda input_id: pending_work
        and input_id == "event-a",
    )
    agent._reply_cycle_context.start_inputs(("event-a",))
    final = Msg(
        name="assistant", role="assistant", content=[TextBlock(text=raw)]
    )
    calls = 0

    async def base_reasoning(_self, tool_choice=None):
        nonlocal calls
        calls += 1
        agent._model_reply_phase = "progress"
        agent._save_to_context(final.content)
        mailbox.submit(run_input("next task", "event-b", mode="queue"))
        yield final

    monkeypatch.setattr(Agent, "_reasoning", base_reasoning)
    monkeypatch.setattr(
        "qwenpaw.loop.gates.runner.check_pending_gates", lambda _: None
    )
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory._supports_multimodal_for_current_model",
        lambda: True,
    )
    events = [event async for event in agent._reasoning()]
    assert calls == 1
    assert final.metadata["reply_error"] == "empty_response"
    assert agent.state.context[-1].content[0].text == raw
    notice = next(
        e.delta for e in events if isinstance(e, TextBlockDeltaEvent)
    )
    assert "请稍后重试" in notice
    assert "不会自动重跑" in notice
    assert events[-1] is final
    assert notice in str(agentscope_msg_to_message(agent.state.context))

    def base_next_action(_self, final_msg=None):
        return (
            Exit(
                exit_msg=final_msg,
                exit_events=[
                    ReplyEndEvent(
                        session_id="session-1",
                        reply_id="reply-1",
                        finished_reason="completed",
                    )
                ],
            )
            if final_msg is not None
            else Reasoning()
        )

    monkeypatch.setattr(Agent, "_next_action", base_next_action)
    assert isinstance(agent._next_action(final), Reasoning)
    expected = "waiting" if pending_work else "failed"
    assert any(
        s.input_ids == ("event-a",) and s.status == expected for s in states
    )
    assert not any(
        s.input_ids == ("event-a",) and s.status == "completed" for s in states
    )
    assert agent._reply_cycle_context.snapshot.responds_to_input_ids == (
        "event-b",
    )
    assert calls == 1


@pytest.mark.parametrize(
    "media_type", ["image/png", "audio/wav", "video/mp4", "application/pdf"]
)
def test_media_only_reply_is_a_public_answer(media_type):
    from agentscope.message import DataBlock, Base64Source

    agent = object.__new__(QwenPawAgent)
    agent.state = SimpleNamespace()
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            DataBlock(
                source=Base64Source(data="YQ==", media_type=media_type),
            )
        ],
    )
    assert agent._has_public_reply(msg)


def test_structured_reply_does_not_require_public_text():
    agent = object.__new__(QwenPawAgent)
    agent.state = SimpleNamespace(
        reply_context=SimpleNamespace(structured_schema={})
    )
    assert agent._has_public_reply(
        Msg(name="assistant", role="assistant", content=[])
    )


def test_queue_consumes_one_independent_reply_cycle_at_a_time():
    mailbox = RunInputMailbox()
    mailbox.submit(
        run_input("first task", "event-1", mode="queue", timeline_order=2)
    )
    mailbox.submit(
        run_input("second task", "event-2", mode="queue", timeline_order=3)
    )
    agent = object.__new__(QwenPawAgent)
    agent._run_input_mailbox = mailbox
    agent._context_manager = None
    agent._reply_cycle_context = ReplyCycleContext("run-1", "initial")
    reset_reply_cycle = Mock()
    registration = SimpleNamespace(
        handler=SimpleNamespace(reset_reply_cycle=reset_reply_cycle),
        name="test-handler",
        priority=0,
        scope="",
        is_active=None,
    )
    agent._get_stop_handlers = lambda: [registration]
    agent.state = SimpleNamespace(context=[])

    assert QwenPawAgent._consume_pending_run_inputs(agent) is True
    assert [msg.content[0].text for msg in agent.state.context] == [
        "first task"
    ]
    assert agent._reply_cycle_context.snapshot.responds_to_input_ids == (
        "event-1",
    )
    assert agent.state.context[0].metadata["timeline_order"] == 2

    assert QwenPawAgent._consume_pending_run_inputs(agent) is True
    assert [msg.content[0].text for msg in agent.state.context] == [
        "first task",
        "second task",
    ]
    assert agent._reply_cycle_context.snapshot.responds_to_input_ids == (
        "event-2",
    )
    assert reset_reply_cycle.call_count == 2


@pytest.mark.asyncio
async def test_save_to_context_stamps_each_block_occurrence(monkeypatch):
    orders = iter((5,))

    async def reserve_order():
        return next(orders)

    agent = object.__new__(QwenPawAgent)
    agent._reply_cycle_context = ReplyCycleContext(
        "run-1",
        "input-a",
        reserve_order,
    )
    agent._context_manager = None
    saved = Msg(
        id="reply",
        name="assistant",
        role="assistant",
        content=[],
    )
    agent._get_last_msg = lambda: saved
    await agent._reply_cycle_context.start_occurrence()
    captured = []

    def save_blocks(_self, blocks, usage=None):
        del usage
        captured.extend(blocks)
        saved.content.extend(blocks)

    monkeypatch.setattr(Agent, "_save_to_context", save_blocks)
    blocks = [
        TextBlock(text="working"),
        ToolCallBlock(id="call-a", name="slow_tool", input="{}"),
    ]

    QwenPawAgent._save_to_context(agent, blocks)

    assert captured == blocks
    assert all(
        reply_block_metadata(saved, block)["timeline_order"] == 5
        for block in blocks
    )
    assert all(
        reply_block_metadata(saved, block)["timeline_group_id"] == "input-a"
        for block in blocks
    )


@pytest.mark.asyncio
async def test_save_to_context_does_not_leak_late_tool_owner(monkeypatch):
    orders = iter((5, 7))

    async def reserve_order():
        return next(orders)

    agent = object.__new__(QwenPawAgent)
    agent._reply_cycle_context = ReplyCycleContext(
        "run-1",
        "input-a",
        reserve_order,
    )
    agent._context_manager = None
    saved = Msg(
        id="reply",
        name="assistant",
        role="assistant",
        content=[],
    )
    agent._get_last_msg = lambda: saved
    await agent._reply_cycle_context.start_occurrence()
    agent._reply_cycle_context.bind_call("call-a")
    agent._reply_cycle_context.activate(["input-b"])
    await agent._reply_cycle_context.start_occurrence()

    def save_blocks(_self, blocks, usage=None):
        del usage
        saved.content.extend(blocks)

    monkeypatch.setattr(Agent, "_save_to_context", save_blocks)
    result = ToolResultBlock(
        id="call-a",
        name="slow_tool",
        output=[TextBlock(text="done")],
    )
    current_text = TextBlock(text="new reply")

    QwenPawAgent._save_to_context(agent, [result, current_text])

    result_metadata = reply_block_metadata(saved, result)
    current_metadata = reply_block_metadata(saved, current_text)
    assert result_metadata["timeline_group_id"] == "input-a"
    assert result_metadata["timeline_order"] == 5
    assert current_metadata["timeline_group_id"] == "input-b"
    assert current_metadata["timeline_order"] == 7


def test_queue_waits_for_reply_while_steer_can_enter_reasoning():
    mailbox = RunInputMailbox()
    mailbox.submit(run_input("queued task", "queue-1", mode="queue"))
    agent = object.__new__(QwenPawAgent)
    agent._run_input_mailbox = mailbox
    agent._context_manager = None
    agent.state = SimpleNamespace(context=[])

    assert (
        QwenPawAgent._consume_pending_run_inputs(agent, steer_only=True)
        is False
    )
    assert agent.state.context == []


# Integration boundary: real Agent, Scroll, SQLite, tool and formatter.
# Only model responses and token counts are scripted; this is not audio E2E.


class HistoryReadingModel:
    """Only model output is fixed; ordinary Agent executes the real tool."""

    model = "offline-shared-agent-preflight"
    context_size = 100000

    def __init__(self, formatter):
        self.formatter = formatter
        self.requests = []

    async def count_tokens(self, *args, **kwargs):
        return 100

    async def __call__(self, *, messages, tools, **kwargs):
        wire = await self.formatter.format(messages)
        self.requests.append({"messages": wire, "tools": tools})
        if len(self.requests) == 1:
            return ChatResponse(
                content=[
                    ToolCallBlock(
                        id="read-old-result",
                        name="recall_history",
                        input=json.dumps(
                            {
                                "op": "search",
                                "query": "ARCHIVE_K7",
                                "session_id": "chat-session",
                            }
                        ),
                    )
                ],
                is_last=True,
            )
        assert len(self.requests) == 2, "Unexpected extra model attempt"
        assert "HTTP 403: expired permission" in json.dumps(wire)
        return ChatResponse(
            content=[TextBlock(text="旧资料记录的是权限过期导致 HTTP 403；未重新执行任务。")],
            is_last=True,
        )


@pytest.fixture
def ordinary_history_store(tmp_path):
    history = HistoryStore(tmp_path / "history.db")
    try:
        for key, role, content in (
            ("old-user", "user", "检查 ARCHIVE_K7"),
            (
                "old-answer",
                "assistant",
                "ARCHIVE_K7 failed: HTTP 403: expired permission",
            ),
        ):
            history.append(
                session_id="chat-session",
                agent_id="fixture-agent",
                dedup_key=key,
                entry=LogEntry(kind="context_msg", role=role, content=content),
            )
        yield history
    finally:
        history.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "formatter_type", [OpenAIChatFormatter, DashScopeChatFormatter]
)
@pytest.mark.parametrize("mode", ["queue", "steer"])
async def test_ordinary_agent_handoff_uses_existing_history_tool(
    tmp_path, ordinary_history_store, formatter_type, mode, record_property
):
    recall = make_recall_history(
        history_db_path=str(tmp_path / "history.db"),
        session_id="chat-session",
        agent_id="fixture-agent",
    )
    mailbox = RunInputMailbox()
    original = "查之前资料失败的原因，不重新执行。"
    snapshot = "用户此前指的是 ARCHIVE_K7，不是当前任务。"
    mailbox.submit(
        RunInput(
            (TextContent(text=original),),
            "speech-input-1",
            mode=mode,
            message_metadata={QWENPAW_CLIENT_MESSAGE_ID_KEY: "speech-input-1"},
            request_context={CHAT_CONVERSATION_CONTEXT_KEY: snapshot},
        )
    )
    model = HistoryReadingModel(formatter_type())
    agent = QwenPawAgent(
        name="Preflight",
        model=model,
        system_prompt="Use the available history tool.",
        toolkit=Toolkit(tools=[FunctionTool(recall)]),
        react_config=ReActConfig(),
        middlewares=[],
        agent_config=SimpleNamespace(language="zh"),
        workspace_dir=tmp_path,
        request_context={"source": "realtime_voice"},
        run_input_mailbox=mailbox,
        context_manager=ScrollContextManager(
            history=ordinary_history_store,
            session_id="chat-session",
            agent_id="fixture-agent",
        ),
    )
    agent.state.context = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(text="这是当前 Chat 的普通前文。")],
        )
    ]
    assert agent._append_pending_run_inputs(activate=False) == (
        "speech-input-1",
    )
    result = await agent.reply()
    assert "HTTP 403" in result.get_text_content()
    assert len(model.requests) == 2
    first = json.dumps(model.requests[0], ensure_ascii=False)
    assert original in first and snapshot in first
    assert "当前 Chat 的普通前文" in first and "recall_history" in first
    assert first.count(original) == 1
    saved = [m for m in agent.state.context if m.id == "speech-input-1"]
    assert len(saved) == 1 and saved[0].get_text_content() == original
    calls = [
        b.name
        for m in agent.state.context
        for b in m.content
        if b.type == "tool_call"
    ]
    assert calls == ["recall_history"]
    record_property(
        "model_requests", json.dumps(model.requests, ensure_ascii=False)
    )
    record_property("scripted_model", "true")
    record_property("real_agent_scroll_sqlite_tool_formatter", "true")
