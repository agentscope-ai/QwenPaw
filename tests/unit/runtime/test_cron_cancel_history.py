"""Cron cancellation must preserve persisted history, not just the new turn."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.hooks.cron.cron_hook import (
    CronContextHook,
    CronMemoryIsolateHook,
    CronMemoryRestoreHook,
)
from qwenpaw.hooks.session.session_hook import SessionLoadHook, SessionSaveHook
from qwenpaw.runtime.hooks import HookRegistry
from qwenpaw.runtime.runtime import Runtime


def message(text, role="user"):
    return Msg(name=role, role=role, content=[TextBlock(text=text)])


class Agent:
    def __init__(self, state):
        self.state = state

    def state_dict(self):
        return {"state": self.state.model_dump(mode="json")}


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["success", "timeout", "stop"])
async def test_runtime_keeps_old_history_on_disk(
    tmp_path, monkeypatch, ending
):
    """Use the real lifecycle and JSON store; replace only model execution."""
    old = [
        message("输出1"),
        message("1", "assistant"),
        message("输出2"),
        message("2", "assistant"),
    ]
    state = AgentState(
        session_id="cron:test", context=old, summary="old summary"
    )
    session = SafeJSONSession(save_dir=str(tmp_path))
    await session.save_session_state(
        "cron:test", "user", "console", agent=Agent(state)
    )
    hooks = HookRegistry()
    for hook in [
        CronContextHook(),
        SessionLoadHook(),
        CronMemoryIsolateHook(),
        CronMemoryRestoreHook(),
        SessionSaveHook(),
    ]:
        hooks.register(hook)
    workspace = SimpleNamespace(
        session=session,
        plugins=SimpleNamespace(
            hook_registry=hooks,
            modes=[],
            slash_command_registry=SimpleNamespace(
                dispatch=AsyncMock(return_value=None)
            ),
        ),
    )
    started = asyncio.Event()

    class Builder:
        def __init__(self, **kwargs):
            pass

        async def build(self, ctx):
            return Agent(AgentState.model_validate(ctx.session_state["state"]))

    class Executor:
        def __init__(self, agent, envelope):
            self.agent = agent

        async def run(self, inputs):
            # Isolation must still prevent the model from seeing old turns.
            assert not self.agent.state.context
            self.agent.state.context.extend(inputs)
            self.agent.state.context.append(
                message("本次已产生的内容", "assistant")
            )
            started.set()
            if ending != "success":
                await asyncio.Event().wait()
            if False:
                yield

    monkeypatch.setattr("qwenpaw.runtime.runtime.AgentBuilder", Builder)
    monkeypatch.setattr("qwenpaw.runtime.runtime.AgentExecutor", Executor)
    runtime = Runtime(workspace=workspace, app_services=None)

    async def consume():
        async for _ in runtime.run(
            {
                "session_id": "cron:test",
                "user_id": "user",
                "channel": "console",
                "session_source": "cron",
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "长任务"}],
                    }
                ],
            }
        ):
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 2)
    if ending == "timeout":
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(task, 0.01)
    elif ending == "stop":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task

    saved = await session.get_session_state_dict(
        "cron:test", "user", "console"
    )
    result = saved["agent"]["state"]
    assert [m["id"] for m in result["context"][:4]] == [m.id for m in old]
    assert len(result["context"]) == 6
    assert result["context"][-1]["content"][0]["text"] == "本次已产生的内容"
    assert result["summary"] == "old summary"


@pytest.mark.asyncio
@pytest.mark.parametrize("previous_count", [0, 2])
async def test_restoration_is_not_duplicated_on_cancel(
    tmp_path, previous_count
):
    old = [message(str(i)) for i in range(previous_count)]
    agent = Agent(AgentState(context=old, summary="old summary"))
    session = SafeJSONSession(save_dir=str(tmp_path))
    ctx = SimpleNamespace(
        extras={"is_cron": True},
        agent=agent,
        session_id="cron:test",
        request=SimpleNamespace(user_id="user", channel="console"),
        workspace=SimpleNamespace(session=session),
    )
    await CronMemoryIsolateHook().run(ctx)
    new = message("new")
    agent.state.context.append(new)
    await CronMemoryRestoreHook().run(ctx)
    # Cancellation may happen after restoration but before the normal save.
    runtime = Runtime(workspace=ctx.workspace, app_services=None)
    await runtime._try_save_on_cancel(ctx)
    saved = await session.get_session_state_dict(
        "cron:test", "user", "console"
    )
    assert [m["id"] for m in saved["agent"]["state"]["context"]] == [
        m.id for m in [*old, new]
    ]
    assert saved["agent"]["state"]["summary"] == "old summary"


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_restore_failure_does_not_overwrite_session(tmp_path, cancelled):
    old = message("history must survive")
    agent = Agent(AgentState(context=[old]))
    session = SafeJSONSession(save_dir=str(tmp_path))
    await session.save_session_state(
        "cron:test", "user", "console", agent=agent
    )
    ctx = SimpleNamespace(
        extras={"is_cron": True},
        agent=agent,
        session_id="cron:test",
        request=SimpleNamespace(user_id="user", channel="console"),
        workspace=SimpleNamespace(session=session),
        mode_state={},
    )
    await CronMemoryIsolateHook().run(ctx)

    class BrokenState:
        summary = ""

        @property
        def context(self):
            return [message("isolated new turn")]

        @context.setter
        def context(self, value):
            raise RuntimeError("restoration failed")

        def model_dump(self, **kwargs):
            return AgentState(context=self.context).model_dump(**kwargs)

    agent.state = BrokenState()
    if cancelled:
        runtime = Runtime(workspace=ctx.workspace, app_services=None)
        await runtime._try_save_on_cancel(ctx)
    else:
        await SessionSaveHook().run(ctx)
    saved = await session.get_session_state_dict(
        "cron:test", "user", "console"
    )
    assert [m["id"] for m in saved["agent"]["state"]["context"]] == [old.id]
    # A failed restore must retain the snapshot for a possible retry.
    with pytest.raises(RuntimeError, match="restoration failed"):
        await CronMemoryRestoreHook().run(ctx)
