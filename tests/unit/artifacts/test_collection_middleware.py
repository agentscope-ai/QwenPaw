from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_collects_after_actual_tool_finishes_and_preserves_result(monkeypatch, fails):
    from qwenpaw.artifacts import middleware

    events = []
    context = {"user_id": "owner", "agent_id": "qa", "conversation_id": "chat"}

    async def collect(ctx):
        assert ctx is context
        events.append("collected")

    monkeypatch.setattr(middleware, "collect_safely", collect)

    async def execute():
        events.append("tool")
        yield "image-result"
        if fails:
            raise RuntimeError("tool failed")

    stream = middleware.ArtifactCollectionMiddleware().on_acting(
        SimpleNamespace(_request_context=context), {"tool_call": "render"}, execute,
    )
    assert await anext(stream) == "image-result"
    assert events == ["tool"]
    with pytest.raises(RuntimeError if fails else StopAsyncIteration):
        await anext(stream)
    assert events == ["tool", "collected"]


@pytest.mark.asyncio
async def test_archive_failure_does_not_break_chat_and_remains_observable(monkeypatch, caplog):
    from qwenpaw.artifacts import middleware
    from qwenpaw.artifacts import collection

    monkeypatch.setattr(collection, "collect_current_session_artifacts", AsyncMock(side_effect=OSError("database down")))
    await middleware.collect_safely({"user_id": "owner"})
    assert "artifact" in caplog.text.lower()


@pytest.mark.asyncio
async def test_cancellation_keeps_collection_running_without_skipping_final_cleanup(monkeypatch):
    from qwenpaw.artifacts import middleware, collection

    started, finish, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def collect(context):
        started.set()
        await finish.wait()
        completed.set()
        return SimpleNamespace(failures=())

    monkeypatch.setattr(collection, "collect_current_session_artifacts", collect)
    task = asyncio.create_task(middleware.collect_safely({}))
    await started.wait()
    task.cancel()
    await task
    finish.set()
    await asyncio.wait_for(completed.wait(), 1)


@pytest.mark.asyncio
async def test_runtime_archives_before_terminal_event_is_visible(monkeypatch):
    from qwenpaw.runtime.runtime import Runtime
    from qwenpaw.runtime import runtime
    from qwenpaw.runtime.hooks import HookAction, HookResult
    from qwenpaw.artifacts import middleware

    collected = AsyncMock()
    monkeypatch.setattr(middleware, "collect_safely", collected)
    hooks = SimpleNamespace(run=AsyncMock(return_value=HookResult(action=HookAction.SKIP_AGENT)))
    workspace = SimpleNamespace(plugins=SimpleNamespace(hook_registry=hooks, slash_command_registry=SimpleNamespace(dispatch=AsyncMock(return_value=None))))
    context = {"user_id": "owner", "agent_id": "qa", "conversation_id": "chat"}
    ctx = SimpleNamespace(session_id="s", root_session_id="s", agent_id="qa", request=SimpleNamespace(request_context=context), agent=SimpleNamespace(_request_context=context, close=AsyncMock()), input_msgs=[], error=None)

    class Envelope:
        def __init__(self, **kwargs):
            pass

        async def finalize(self):
            yield "completed"

    monkeypatch.setattr(runtime, "Envelope", Envelope)
    instance = Runtime(workspace=workspace, app_services=None)
    monkeypatch.setattr(instance, "_normalize", lambda request: request)
    monkeypatch.setattr(instance, "_build_context", lambda request: ctx)
    stream = instance.run(ctx.request)
    assert await anext(stream) == "completed"
    collected.assert_awaited_once_with(context)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    collected.assert_awaited_once_with(context)
