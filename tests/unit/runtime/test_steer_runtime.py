# -*- coding: utf-8 -*-
"""Exercise steering through the real agent loop and transcript writer."""

import asyncio
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.agent import Agent, ReActConfig
from agentscope.message import Msg, TextBlock, ToolCallBlock
from agentscope.tool import FunctionTool, Toolkit, ToolResponse
from agentscope.permission import PermissionDecision, PermissionBehavior
from agentscope.model import ChatModelBase, ChatResponse

from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw.app.workspace import workspace as workspace_module
from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_recorder import TranscriptRecorder
from qwenpaw.runtime.envelope import Envelope
from qwenpaw.runtime.executor import AgentExecutor
from qwenpaw.runtime.steer import (
    SteerControl,
    SteerMiddleware,
    current_steer,
)
from qwenpaw.schemas import AgentRequest, Message, RunStatus, TextContent


class ControlledModel(ChatModelBase):
    """Replace only the remote provider, retaining the real agent loop."""

    def __init__(self, control, content=None):
        super().__init__(None, "test", self.Parameters(), stream=False)
        self.formatter = SimpleNamespace(supported_input_media_types=set())
        self.control = control
        self.content = content or [{"type": "text", "text": "use green"}]
        self.inputs = []

    async def count_tokens(self, *args, **kwargs):
        return 1

    async def __call__(self, messages, **kwargs):
        self.inputs.append([m.model_dump() for m in messages])
        if len(self.inputs) == 1:
            await self.control.accept("correction", self.content)
        return ChatResponse(
            content=[TextBlock(text=f"answer {len(self.inputs)}")],
            is_last=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("max_iters", [1, 3])
@pytest.mark.parametrize("attachment", [False, True])
async def test_normal_exit_continues_same_run_with_steer_in_model_input(
    tmp_path,
    max_iters,
    attachment,
):
    store = TranscriptStore(tmp_path / "s.db")
    request = SimpleNamespace(
        session_id="s",
        user_id="u",
        channel="console",
        request_context={},
        input=[
            Message(id="u1", role="user", content=[TextContent(text="go")]),
        ],
    )
    recorder = TranscriptRecorder(store=store, request=request)
    await recorder.start()
    control = SteerControl(recorder)
    content = [{"type": "text", "text": "use green"}]
    if attachment:
        file = tmp_path / "steer.txt"
        file.write_text("ATTACHMENT_GREEN")
        content.append(
            {"type": "file", "file_url": str(file), "file_name": "steer.txt"},
        )
    model = ControlledModel(control, content)
    agent = Agent(
        "test",
        "help",
        model,
        middlewares=[SteerMiddleware(control)],
        react_config=ReActConfig(max_iters=max_iters),
    )
    envelope = Envelope("s")
    envelope.bind_turn(recorder.turn_id, "u1", "scope")
    control.envelope = envelope
    executor = AgentExecutor(agent, envelope)
    async for item in executor.run(
        [
            Msg(
                name="user",
                content=[TextBlock(text="go")],
                role="user",
                id="u1",
            ),
        ],
    ):
        # Console streaming dispatches every envelope by this discriminator.
        assert item.object in {"message", "content", "response"}
        await recorder.observe(item)
    result = [item async for item in envelope.finalize()][-1]
    if max_iters == 1:
        assert len(model.inputs) == 1
        assert all(message.role != "user" for message in result.output)
        receipt = store.list_steers(session_id="s")[0]
        assert receipt["status"] == "failed"
        assert receipt["reason"] == "iteration_limit"
        store.close()
        return
    assert len(model.inputs) == 2
    assert any(
        m["role"] == "user" and "use green" in str(m["content"])
        for m in model.inputs[1]
    )
    assert [m.role for m in result.output] == [
        "assistant",
        "user",
        "assistant",
    ]
    assert result.output[0].id != result.output[-1].id
    assert (
        result.output[-1].metadata["after_user_message_id"]
        == result.output[1].id
    )
    assert store.list_steers(session_id="s")[0]["status"] == "applied"
    if attachment:
        assert result.output[1].content[1].file_url == str(file)
        assert "steer.txt" in str(model.inputs[1])
        user = next(
            m for m in agent.state.context if m.id == result.output[1].id
        )
        assert "steer.txt" in str(user.metadata)
    store.write_runtime_state(
        session_id="s",
        user_id="u",
        channel="console",
        turn_id=recorder.turn_id,
        state={"agent": {"state": agent.state.model_dump(mode="json")}},
    )
    store.finish_turn(
        session_id="s",
        turn_id=recorder.turn_id,
        status="completed",
    )
    assert store.can_fork_turn(session_id="s", turn_id=recorder.turn_id)
    store.close()


@pytest.mark.asyncio
async def test_stop_during_commit_drains_context_before_snapshot(tmp_path):
    store = TranscriptStore(tmp_path / "s.db")
    request = SimpleNamespace(
        session_id="s",
        user_id="u",
        channel="console",
        request_context={},
        input=[
            Message(id="u1", role="user", content=[TextContent(text="go")]),
        ],
    )
    recorder = TranscriptRecorder(store=store, request=request)
    await recorder.start()
    control = SteerControl(recorder)
    agent = Agent("test", "help", ControlledModel(control))
    control.agent = agent
    control.envelope = Envelope("s")
    control.envelope.bind_turn(recorder.turn_id, "u1", "scope")
    await control.accept("c", [{"type": "text", "text": "fix"}])
    entered, release = asyncio.Event(), asyncio.Event()
    original = recorder.apply_steers

    async def delayed(messages, step):
        await original(messages, step)
        entered.set()
        await release.wait()

    recorder.apply_steers = delayed

    async def apply():
        return [event async for event in control.apply(agent)]

    task = asyncio.create_task(apply())
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.list_steers(session_id="s")[0]["status"] == "applied"
    assert agent.state.context[-1].role == "user"
    assert agent.state.context[-1].content[0].text == "fix"
    assert control.envelope.response.output[-1].role == "user"
    await control.close("cancelled")
    assert store.list_steers(session_id="s")[0]["status"] == "applied"
    store.close()


@pytest.mark.asyncio
async def test_tool_round_finishes_before_steer_enters_context(tmp_path):
    store = TranscriptStore(tmp_path / "s.db")
    request = SimpleNamespace(
        session_id="s",
        user_id="u",
        channel="console",
        request_context={},
        input=[
            Message(id="u1", role="user", content=[TextContent(text="go")]),
        ],
    )
    recorder = TranscriptRecorder(store=store, request=request)
    await recorder.start()
    control = SteerControl(recorder)
    completed = []

    async def tool_one():
        """Finish the first tool and submit a correction."""
        await control.accept(
            "c",
            [{"type": "text", "text": "after both tools"}],
        )
        completed.append("one")
        return ToolResponse(content=[TextBlock(text="one done")])

    async def tool_two():
        """Ensure steering has not split the current tool round."""
        await asyncio.sleep(0)
        assert not any(
            m.role == "user" and m.id != "u1"
            for m in control.agent.state.context
        )
        completed.append("two")
        return ToolResponse(content=[TextBlock(text="two done")])

    class ToolModel(ControlledModel):
        async def __call__(self, messages, **kwargs):
            self.inputs.append([m.model_dump() for m in messages])
            if len(self.inputs) == 1:
                return ChatResponse(
                    content=[
                        ToolCallBlock(id="one", name="tool_one", input="{}"),
                        ToolCallBlock(id="two", name="tool_two", input="{}"),
                    ],
                    is_last=True,
                )
            assert sorted(completed) == ["one", "two"]
            assert messages[-1].role == "user"
            return ChatResponse(content=[TextBlock(text="done")], is_last=True)

    model = ToolModel(control)
    agent = Agent(
        "test",
        "help",
        model,
        toolkit=Toolkit(
            tools=[
                FunctionTool(
                    fn,
                    permission=PermissionDecision(
                        PermissionBehavior.ALLOW,
                        "test",
                    ),
                )
                for fn in (tool_one, tool_two)
            ],
        ),
        middlewares=[SteerMiddleware(control)],
    )
    control.envelope = envelope = Envelope("s")
    envelope.bind_turn(recorder.turn_id, "u1", "scope")
    async for item in AgentExecutor(agent, envelope).run(
        [
            Msg(
                id="u1",
                name="user",
                role="user",
                content=[TextBlock(text="go")],
            ),
        ],
    ):
        await recorder.observe(item)
    output = [item async for item in envelope.finalize()][-1].output
    steer_index = next(i for i, m in enumerate(output) if m.role == "user")
    results = [
        i for i, m in enumerate(output) if m.type == "plugin_call_output"
    ]
    assert len(results) == 2
    assert max(results) < steer_index
    assert len(model.inputs) == 2
    store.close()


@pytest.mark.asyncio
async def test_workspace_stop_at_steer_output_settles_history(
    tmp_path,
    monkeypatch,
):
    catalog = TranscriptCatalog(tmp_path)
    controls = []
    streams = []

    class Runtime(workspace_module.Runtime):
        def __init__(self, **kwargs):
            pass

        async def run(self, request):
            control = current_steer.get()
            controls.append(control)
            model = ControlledModel(control)
            agent = Agent(
                "test",
                "help",
                model,
                middlewares=[SteerMiddleware(control)],
                react_config=ReActConfig(max_iters=3),
            )
            envelope = Envelope("s")
            envelope.bind_turn(control.turn_id, "u1", "scope")
            control.envelope = envelope
            reply_stream = agent.reply_stream

            def retain_source(**kwargs):
                source = reply_stream(**kwargs)
                streams.append(source)
                return source

            agent.reply_stream = retain_source
            events = AgentExecutor(agent, envelope).run(
                [
                    Msg(
                        name="user",
                        role="user",
                        id="u1",
                        content=[TextBlock(text="go")],
                    ),
                ],
            )
            streams.append(events)
            async with aclosing(events):
                async for obj in events:
                    yield obj

    monkeypatch.setattr(workspace_module, "Runtime", Runtime)
    monkeypatch.setattr(
        workspace_module,
        "load_agent_config_async",
        AsyncMock(return_value=SimpleNamespace(backend="qwenpaw")),
    )
    workspace = SimpleNamespace(
        agent_id="test",
        workspace_dir=tmp_path,
        transcript_store=catalog,
        session=None,
        _app_services=None,
        steer_runs={},
        finalize_turn_usage=AsyncMock(),
    )
    identity = dict(session_id="s", user_id="u", channel="console")
    stream = workspace_module.Workspace._stream_query(
        workspace,
        AgentRequest(
            **identity,
            input=[
                Message(
                    id="u1",
                    role="user",
                    content=[TextContent(text="go")],
                ),
            ],
        ),
    )
    try:
        async for obj in stream:
            if (
                isinstance(obj, Message)
                and obj.role == "assistant"
                and obj.status == RunStatus.Completed
            ):
                break
        else:
            pytest.fail("steer boundary not reached")
        control = controls[0]
        assert not control.lock.locked()
        await asyncio.wait_for(stream.aclose(), 2)
        assert all(source.ag_frame is None for source in streams)
        assert not workspace.steer_runs
        assert not catalog._handles
        receipt = catalog.list_steers(**identity)[0]
        assert receipt["status"] == "failed"
        page = catalog.get_page(**identity)
        assert page.messages[0].metadata["qwenpaw_turn_state"]["status"] == (
            "canceled"
        )
        assert [m.role for m in page.messages] == ["user", "assistant"]
        catalog.close()
        catalog = TranscriptCatalog(tmp_path)
        assert [m.id for m in catalog.get_page(**identity).messages] == [
            m.id for m in page.messages
        ]
    finally:
        await stream.aclose()
        catalog.close()


@pytest.mark.asyncio
async def test_new_attachment_during_boundary_stays_in_next_batch(tmp_path):
    store = TranscriptStore(tmp_path / "s.db")
    request = SimpleNamespace(
        session_id="s",
        user_id="u",
        channel="console",
        request_context={},
        input=[],
    )
    recorder = TranscriptRecorder(store=store, request=request)
    await recorder.start()
    control = SteerControl(recorder)
    agent = Agent("test", "help", ControlledModel(control))
    control.agent = agent
    envelope = Envelope("s")
    envelope.bind_turn(recorder.turn_id, "u1", "scope")
    control.envelope = envelope

    async def boundary():
        yield Message(
            id="a1",
            role="assistant",
            content=[TextContent(text="before")],
            status=RunStatus.Completed,
        )

    envelope.close_input_segment = boundary
    await control.accept("first", [{"type": "text", "text": "first"}])
    stream = control.apply(agent)
    try:
        item = await anext(stream)
        await recorder.observe(item.output)
        file = tmp_path / "next.txt"
        file.write_text("NEXT_ATTACHMENT", encoding="utf-8")
        await asyncio.wait_for(
            control.accept(
                "next",
                [
                    {"type": "text", "text": "next"},
                    {
                        "type": "file",
                        "file_url": str(file),
                        "file_name": "next.txt",
                    },
                ],
            ),
            2,
        )
        async for item in stream:
            await recorder.observe(item.output)
        receipts = store.list_steers(session_id="s")
        assert [r["status"] for r in receipts] == ["applied", "accepted"]
        assert [r["client_message_id"] for r in control.pending] == ["next"]
        async for item in control.apply(agent):
            await recorder.observe(item.output)
        await recorder.finish("completed")
        page = store.get_page(session_id="s", user_id="u", channel="console")
        assert [m.role for m in page.messages] == ["assistant", "user", "user"]
        assert page.messages[-1].content[-1].file_url == str(file)
        assert "next.txt" in str(agent.state.context[-1].metadata)
        assert not control.pending
    finally:
        await stream.aclose()
        store.close()


@pytest.mark.asyncio
async def test_stop_drains_accepted_attachment_before_settling(tmp_path):
    store = TranscriptStore(tmp_path / "s.db")
    recorder = TranscriptRecorder(
        store=store,
        request=SimpleNamespace(
            session_id="s",
            user_id="u",
            channel="console",
            request_context={},
            input=[],
        ),
    )
    await recorder.start()
    control = SteerControl(recorder)
    control.agent = Agent("test", "help", ControlledModel(control))
    control.envelope = Envelope("s")
    entered, release = asyncio.Event(), asyncio.Event()
    original = recorder.steer_io

    async def delayed(method, **kwargs):
        result = await original(method, **kwargs)
        if method == "accept_steer":
            entered.set()
            await release.wait()
        return result

    recorder.steer_io = delayed
    attachment = tmp_path / "pending.txt"
    attachment.write_text("PENDING", encoding="utf-8")
    submit = asyncio.create_task(
        control.accept(
            "pending",
            [
                {
                    "type": "file",
                    "file_url": str(attachment),
                    "file_name": "pending.txt",
                },
            ],
        ),
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        control.closed = True
        closing = asyncio.create_task(control.close("cancelled"))
        submit.cancel()
        await asyncio.sleep(0)
        submit.cancel()
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await submit
        await asyncio.wait_for(closing, 2)
        await recorder.finish("cancelled")
        with pytest.raises(ValueError, match="no_active_turn"):
            await control.accept("late", [{"type": "text", "text": "late"}])
        receipts = store.list_steers(session_id="s")
        assert len(receipts) == 1
        assert receipts[0]["status"] == "failed"
        assert receipts[0]["reason"] == "cancelled"
        assert not control.pending
        assert not control.agent.state.context
        store.rebuild_projections()
        assert store.list_steers(session_id="s")[0]["status"] == "failed"
    finally:
        release.set()
        store.close()
