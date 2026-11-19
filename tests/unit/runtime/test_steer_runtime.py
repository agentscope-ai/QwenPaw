# -*- coding: utf-8 -*-
"""Exercise steering through the real agent loop and transcript writer."""

import asyncio
from types import SimpleNamespace

import pytest
from agentscope.agent import Agent, ReActConfig
from agentscope.message import Msg, TextBlock, ToolCallBlock
from agentscope.tool import FunctionTool, Toolkit, ToolResponse
from agentscope.permission import PermissionDecision, PermissionBehavior
from agentscope.model import ChatModelBase, ChatResponse

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_recorder import TranscriptRecorder
from qwenpaw.runtime.envelope import Envelope
from qwenpaw.runtime.executor import AgentExecutor
from qwenpaw.runtime.steer import SteerControl, SteerMiddleware
from qwenpaw.schemas import Message, TextContent


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
